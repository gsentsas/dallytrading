# -*- coding: utf-8 -*-
"""Correction contrôlée de l'adresse de livraison avant préparation.

Les commandes historiques du Lot B pouvaient demander une livraison sans avoir
une adresse exploitable, et un client peut aussi demander une correction après le
checkout. L'adresse figée reste donc modifiable par une action métier dédiée tant
que la préparation n'a pas été autorisée. Elle n'est jamais rendue génériquement
éditable sur ``sale.order``.

Si des frais avaient déjà été cotés pour une méthode ``quote``, modifier l'adresse
invalide cette cotation : l'état repasse à ``pending_quote`` et le client est
informé qu'un nouveau montant doit être confirmé. Conserver l'ancien prix après
un changement de destination donnerait une cohérence apparente mais fausse.
"""

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class SaleOrderShopShippingManagement(models.Model):
    _inherit = "sale.order"

    dally_shop_shipping_updated_at = fields.Datetime(
        string="Adresse de livraison mise à jour le",
        copy=False,
        readonly=True,
    )
    dally_shop_shipping_updated_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Adresse de livraison mise à jour par",
        copy=False,
        readonly=True,
        ondelete="restrict",
    )

    def _dally_shop_shipping_edit_preconditions(self):
        self.ensure_one()
        self._dally_shop_require_workflow_operator()
        method = self.dally_shop_delivery_method_id
        if not method or not method.requires_address:
            raise ValidationError(_("Cette commande ne nécessite pas d'adresse de livraison."))
        if self.dally_shop_fulfillment_authorized:
            raise ValidationError(
                _("L'adresse ne peut plus être modifiée après autorisation de la préparation.")
            )
        if self.dally_shop_workflow_state not in ("received", "validated"):
            raise ValidationError(
                _("L'état commercial de la commande ne permet plus de modifier l'adresse.")
            )

    def action_dally_shop_open_shipping_address(self):
        self.ensure_one()
        self._dally_shop_shipping_edit_preconditions()
        partner = self.partner_id
        return {
            "type": "ir.actions.act_window",
            "name": _("Adresse de livraison"),
            "res_model": "dally.shop.shipping.address.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "dally_shop.view_dally_shop_shipping_address_wizard"
            ).id,
            "target": "new",
            "context": {
                "default_order_id": self.id,
                "default_name": self.dally_shop_shipping_name or partner.name or "",
                "default_phone": self.dally_shop_shipping_phone or partner.phone or "",
                "default_street": self.dally_shop_shipping_street or partner.street or "",
                "default_street2": self.dally_shop_shipping_street2 or partner.street2 or "",
                "default_city": self.dally_shop_shipping_city or partner.city or "",
                "default_zip": self.dally_shop_shipping_zip or partner.zip or "",
                "default_country_code": self.dally_shop_shipping_country_code
                or (partner.country_id.code if partner.country_id else ""),
            },
        }

    def _dally_shop_set_shipping_address(self, values):
        self.ensure_one()
        self._dally_shop_shipping_edit_preconditions()
        snapshot = self._dally_shop_shipping_snapshot(self.partner_id, values)
        quote_invalidated = (
            self.dally_shop_delivery_method_id.fee_policy == "quote"
            and self.dally_shop_delivery_fee_state == "quoted"
        )
        update_values = {
            "dally_shop_shipping_name": snapshot["name"],
            "dally_shop_shipping_phone": snapshot["phone"] or False,
            "dally_shop_shipping_street": snapshot["street"],
            "dally_shop_shipping_street2": snapshot["street2"] or False,
            "dally_shop_shipping_city": snapshot["city"],
            "dally_shop_shipping_zip": snapshot["zip"] or False,
            "dally_shop_shipping_country_code": snapshot["country_code"] or False,
            "dally_shop_shipping_updated_at": fields.Datetime.now(),
            "dally_shop_shipping_updated_by_id": self.env.user.id,
        }
        if quote_invalidated:
            update_values.update({
                "dally_shop_delivery_fee_state": "pending_quote",
                "dally_shop_delivery_fee": 0.0,
            })

        self.sudo().write(update_values)

        if quote_invalidated:
            self._dally_shop_queue_delivery_notification(
                _("Adresse de livraison mise à jour"),
                _(
                    "L'adresse de livraison de la commande %(reference)s a été "
                    "mise à jour. Les frais de remise doivent être confirmés à nouveau.",
                    reference=self.name,
                ),
            )
        return True


class DallyShopShippingAddressWizard(models.TransientModel):
    _name = "dally.shop.shipping.address.wizard"
    _description = "Correction de l'adresse de livraison boutique"

    order_id = fields.Many2one(
        "sale.order",
        string="Commande",
        required=True,
        readonly=True,
    )
    name = fields.Char(string="Destinataire", required=True)
    phone = fields.Char(string="Téléphone")
    street = fields.Char(string="Adresse", required=True)
    street2 = fields.Char(string="Complément")
    city = fields.Char(string="Ville", required=True)
    zip = fields.Char(string="Code postal")
    country_code = fields.Char(string="Code pays")

    def action_apply(self):
        self.ensure_one()
        self.order_id._dally_shop_set_shipping_address({
            "name": self.name,
            "phone": self.phone,
            "street": self.street,
            "street2": self.street2,
            "city": self.city,
            "zip": self.zip,
            "country_code": self.country_code,
        })
        return {"type": "ir.actions.act_window_close"}
