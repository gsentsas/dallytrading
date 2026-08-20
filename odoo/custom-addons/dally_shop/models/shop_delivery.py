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
