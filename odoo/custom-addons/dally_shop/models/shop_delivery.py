# -*- coding: utf-8 -*-
"""Méthodes de remise configurables et snapshot logistique des commandes boutique.

Le Lot C sépare trois décisions qui étaient auparavant confondues dans une
selection codée en dur :

* la méthode proposée au client (retrait ou livraison) ;
* la façon dont son coût est décidé (gratuit, fixe, à confirmer) ;
* le suivi opérationnel de la remise après validation commerciale.

Le navigateur ne fournit jamais de prix. Il envoie seulement le ``code`` public
d'une méthode active ; Odoo résout ce code et fige le coût applicable sur la
commande. Une modification ultérieure du catalogue de livraison ne réécrit donc
pas rétroactivement une commande déjà reçue.

La confirmation Vente native reste un geste distinct : ce module prépare les
invariants de livraison, mais aucune commande n'est confirmée automatiquement au
checkout ni à la validation commerciale.
"""

import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


DELIVERY_KINDS = [
    ("pickup", "Retrait sur place"),
    ("delivery", "Livraison"),
]

DELIVERY_FEE_POLICIES = [
    ("free", "Gratuit"),
    ("fixed", "Montant fixe"),
    ("quote", "Tarif à confirmer"),
]

DELIVERY_FEE_STATES = [
    ("free", "Sans frais"),
    ("fixed", "Frais fixes"),
    ("pending_quote", "Tarif à confirmer"),
    ("quoted", "Tarif confirmé"),
]

FULFILLMENT_STATES = [
    ("pending", "En attente de préparation"),
    ("preparing", "En préparation"),
    ("ready", "Prête"),
    ("out_for_delivery", "En cours de livraison"),
    ("delivered", "Livrée"),
    ("picked_up", "Retirée"),
]

FULFILLMENT_CLIENT_LABELS = {
    "pending": "En attente de préparation",
    "preparing": "En préparation",
    "ready": "Prête à être remise",
    "out_for_delivery": "En cours de livraison",
    "delivered": "Livrée",
    "picked_up": "Retirée",
}

_CODE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+|_[a-z0-9]+)*$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_SHIPPING_FIELDS = {
    "name",
    "phone",
    "street",
    "street2",
    "city",
    "zip",
    "country_code",
}


class DallyShopDeliveryMethod(models.Model):
    _name = "dally.shop.delivery.method"
    _description = "Méthode de remise boutique"
    _order = "sequence, id"

    name = fields.Char(string="Nom", required=True, translate=True)
    code = fields.Char(
        string="Code public",
        required=True,
        index=True,
        copy=False,
        help="Identifiant stable exposé au frontend. Minuscules, chiffres, tirets ou underscores.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    kind = fields.Selection(
        selection=DELIVERY_KINDS,
        string="Type",
        required=True,
        default="delivery",
    )
    requires_address = fields.Boolean(
        string="Adresse requise",
        compute="_compute_requires_address",
        store=True,
        readonly=True,
    )
    fee_policy = fields.Selection(
        selection=DELIVERY_FEE_POLICIES,
        string="Politique de frais",
        required=True,
        default="quote",
    )
    fixed_fee = fields.Monetary(
        string="Frais fixes",
        currency_field="currency_id",
        default=0.0,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Devise",
        required=True,
        default=lambda self: self.env.company.currency_id.id,
    )
    client_help = fields.Char(
        string="Aide client",
        translate=True,
        help="Phrase courte affichée au checkout. Ne pas y placer d'information interne.",
    )

    _code_unique = models.Constraint(
        "UNIQUE (code)",
        "Le code public d'une méthode de remise doit être unique.",
    )

    @api.depends("kind")
    def _compute_requires_address(self):
        for method in self:
            method.requires_address = method.kind == "delivery"

    @api.constrains("code")
    def _check_code(self):
        for method in self:
            code = (method.code or "").strip()
            if not _CODE.match(code):
                raise ValidationError(
                    _(
                        "Le code de remise doit contenir uniquement des minuscules, "
                        "chiffres, tirets ou underscores."
                    )
                )
            if method.code != code:
                method.code = code

    @api.constrains("fee_policy", "fixed_fee")
    def _check_fee(self):
        for method in self:
            if method.fixed_fee < 0:
                raise ValidationError(_("Les frais de livraison ne peuvent pas être négatifs."))
            if method.fee_policy == "free" and method.fixed_fee:
                raise ValidationError(_("Une méthode gratuite doit avoir des frais nuls."))

    @api.model
    def _dally_shop_resolve(self, code):
        """Résout un code public actif, sans exposer d'identifiant technique."""
        if not isinstance(code, str) or not _CODE.match(code):
            return self.browse()
        return self.sudo().search([("code", "=", code), ("active", "=", True)], limit=1)

    @api.model
    def _dally_shop_public_methods(self):
        methods = self.sudo().search([("active", "=", True)], order="sequence, id")
        return methods._dally_shop_public_projection()

    def _dally_shop_public_projection(self):
        return [
            {
                "code": method.code,
                "name": method.name,
                "kind": method.kind,
                "requiresAddress": bool(method.requires_address),
                "feePolicy": method.fee_policy,
                "feeAmount": (
                    method.fixed_fee
                    if method.fee_policy == "fixed"
                    else 0.0 if method.fee_policy == "free" else None
                ),
                "currency": method.currency_id.name,
                "help": method.client_help or "",
            }
            for method in self
        ]

    def _dally_shop_fee_snapshot(self):
        self.ensure_one()
        if self.fee_policy == "free":
            return "free", 0.0
        if self.fee_policy == "fixed":
            return "fixed", float(self.fixed_fee)
        return "pending_quote", 0.0


class SaleOrderShopDelivery(models.Model):
    _inherit = "sale.order"

    dally_shop_delivery_method_id = fields.Many2one(
        comodel_name="dally.shop.delivery.method",
        string="Méthode de remise",
        copy=False,
        readonly=True,
        ondelete="restrict",
    )
    dally_shop_delivery_fee_state = fields.Selection(
        selection=DELIVERY_FEE_STATES,
        string="État des frais de remise",
        copy=False,
        readonly=True,
    )
    dally_shop_delivery_fee = fields.Monetary(
        string="Frais de remise",
        currency_field="currency_id",
        copy=False,
        readonly=True,
        default=0.0,
    )
    dally_shop_shipping_name = fields.Char(string="Destinataire", copy=False, readonly=True)
    dally_shop_shipping_phone = fields.Char(string="Téléphone livraison", copy=False, readonly=True)
    dally_shop_shipping_street = fields.Char(string="Adresse livraison", copy=False, readonly=True)
    dally_shop_shipping_street2 = fields.Char(string="Complément livraison", copy=False, readonly=True)
    dally_shop_shipping_city = fields.Char(string="Ville livraison", copy=False, readonly=True)
    dally_shop_shipping_zip = fields.Char(string="Code postal livraison", copy=False, readonly=True)
    dally_shop_shipping_country_code = fields.Char(string="Pays livraison", copy=False, readonly=True)
    dally_shop_fulfillment_state = fields.Selection(
        selection=FULFILLMENT_STATES,
        string="État de remise",
        default="pending",
        copy=False,
        readonly=True,
        index=True,
    )
    dally_shop_fulfillment_authorized = fields.Boolean(
        string="Préparation autorisée",
        default=False,
        copy=False,
        readonly=True,
    )
    dally_shop_fulfillment_authorized_at = fields.Datetime(
        string="Préparation autorisée le",
        copy=False,
        readonly=True,
    )
    dally_shop_fulfillment_authorized_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Préparation autorisée par",
        copy=False,
        readonly=True,
        ondelete="restrict",
    )

    @api.model
    def dally_shop_place_order(
        self,
        cart_uuid,
        partner,
        lignes,
        mode_remise,
        invite=False,
        shipping=None,
    ):
        """Ajoute la décision de remise au checkout historique sans casser son idempotence.

        ``mode_remise`` devient le code public de la méthode configurable. Le
        champ historique ``dally_shop_delivery_mode`` reste alimenté avec l'un des
        deux anciens codes afin de garder les commandes et extensions existantes
        compatibles ; l'autorité du Lot C est ``dally_shop_delivery_method_id``.
        """
        existante = self._dally_shop_find_by_cart(cart_uuid)
        if existante:
            return existante

        method = self.env["dally.shop.delivery.method"]._dally_shop_resolve(mode_remise)
        if not method:
            raise ValidationError(_("La méthode de remise demandée n'est pas disponible."))

        delivery_values = self._dally_shop_delivery_values(method, partner, shipping)
        legacy_mode = "pickup" if method.kind == "pickup" else "delivery_to_confirm"

        order = super().dally_shop_place_order(
            cart_uuid,
            partner,
            lignes,
            legacy_mode,
            invite=invite,
        )
        if not order.dally_shop_delivery_method_id:
            order.sudo().write(delivery_values)
        return order

    @api.model
    def _dally_shop_delivery_values(self, method, partner, shipping):
        method.ensure_one()
        fee_state, fee_amount = method._dally_shop_fee_snapshot()
        values = {
            "dally_shop_delivery_method_id": method.id,
            "dally_shop_delivery_fee_state": fee_state,
            "dally_shop_delivery_fee": fee_amount,
            "dally_shop_fulfillment_state": "pending",
        }

        if not method.requires_address:
            return values

        snapshot = self._dally_shop_shipping_snapshot(partner, shipping)
        values.update({
            "dally_shop_shipping_name": snapshot["name"],
            "dally_shop_shipping_phone": snapshot["phone"] or False,
            "dally_shop_shipping_street": snapshot["street"],
            "dally_shop_shipping_street2": snapshot["street2"] or False,
            "dally_shop_shipping_city": snapshot["city"],
            "dally_shop_shipping_zip": snapshot["zip"] or False,
            "dally_shop_shipping_country_code": snapshot["country_code"] or False,
        })
        return values

    @api.model
    def _dally_shop_shipping_snapshot(self, partner, shipping):
        if shipping is not None and not isinstance(shipping, dict):
            raise ValidationError(_("L'adresse de livraison est invalide."))

        if shipping:
            unknown = set(shipping) - _SHIPPING_FIELDS
            if unknown:
                raise ValidationError(_("L'adresse de livraison contient des champs interdits."))

        source = shipping or {}
        values = {
            "name": (source.get("name") or partner.name or "").strip(),
            "phone": (source.get("phone") or partner.phone or "").strip(),
            "street": (source.get("street") or partner.street or "").strip(),
            "street2": (source.get("street2") or partner.street2 or "").strip(),
            "city": (source.get("city") or partner.city or "").strip(),
            "zip": (source.get("zip") or partner.zip or "").strip(),
            "country_code": (
                source.get("country_code")
                or (partner.country_id.code if partner.country_id else "")
                or ""
            ).strip().upper(),
        }

        if not values["name"] or not values["street"] or not values["city"]:
            raise ValidationError(
                _("Un destinataire, une adresse et une ville sont requis pour la livraison.")
            )
        if values["country_code"] and not _COUNTRY.match(values["country_code"]):
            raise ValidationError(_("Le code pays de livraison doit contenir deux lettres."))

        limits = {
            "name": 128,
            "phone": 32,
            "street": 200,
            "street2": 200,
            "city": 100,
            "zip": 20,
            "country_code": 2,
        }
        for field_name, limit in limits.items():
            if len(values[field_name]) > limit:
                raise ValidationError(_("Un champ de l'adresse de livraison est trop long."))
        return values

    def _dally_shop_shipping_projection(self):
        self.ensure_one()
        method = self.dally_shop_delivery_method_id
        if not method or not method.requires_address:
            return None
        return {
            "name": self.dally_shop_shipping_name or "",
            "phone": self.dally_shop_shipping_phone or "",
            "street": self.dally_shop_shipping_street or "",
            "street2": self.dally_shop_shipping_street2 or "",
            "city": self.dally_shop_shipping_city or "",
            "zip": self.dally_shop_shipping_zip or "",
            "countryCode": self.dally_shop_shipping_country_code or "",
        }

    def _dally_shop_delivery_projection(self):
        self.ensure_one()
        method = self.dally_shop_delivery_method_id
        if not method:
            return None
        fee_known = self.dally_shop_delivery_fee_state != "pending_quote"
        return {
            "method": {
                "code": method.code,
                "name": method.name,
                "kind": method.kind,
                "requiresAddress": bool(method.requires_address),
            },
            "fee": {
                "status": self.dally_shop_delivery_fee_state or "pending_quote",
                "amount": self.dally_shop_delivery_fee if fee_known else None,
                "currency": self.currency_id.name,
            },
            "shippingAddress": self._dally_shop_shipping_projection(),
            "fulfillment": {
                "state": self.dally_shop_fulfillment_state or "pending",
                "label": FULFILLMENT_CLIENT_LABELS.get(
                    self.dally_shop_fulfillment_state or "pending", ""
                ),
            },
        }

    def _dally_shop_delivery_grand_total(self):
        self.ensure_one()
        if self.dally_shop_delivery_fee_state == "pending_quote":
            return None
        return self.amount_total + self.dally_shop_delivery_fee

    def _dally_shop_projection(self):
        self.ensure_one()
        projection = super()._dally_shop_projection()
        method = self.dally_shop_delivery_method_id
        if not method:
            return projection
        projection.update({
            "deliveryMode": method.code,
            "deliveryModeLabel": method.name,
            "delivery": self._dally_shop_delivery_projection(),
            "grandTotal": self._dally_shop_delivery_grand_total(),
        })
        return projection
