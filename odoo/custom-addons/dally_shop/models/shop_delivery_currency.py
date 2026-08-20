# -*- coding: utf-8 -*-
"""Conversion des frais fixes vers la devise réelle de la commande.

Une méthode de remise peut être configurée dans une devise différente du tarif
boutique. Additionner directement son ``fixed_fee`` au total de la commande
mélangerait alors deux monnaies. Le snapshot Lot C convertit donc le montant fixe
vers la devise de la pricelist boutique au moment du checkout, puis le fige sur la
commande. La projection publique de la méthode reste dans sa devise de
configuration ; la projection de commande, elle, est toujours cohérente avec
``sale.order.currency_id``.
"""

from odoo import api, fields, models


class SaleOrderShopDeliveryCurrency(models.Model):
    _inherit = "sale.order"

    @api.model
    def _dally_shop_delivery_values(self, method, partner, shipping):
        values = super()._dally_shop_delivery_values(method, partner, shipping)
        if method.fee_policy != "fixed":
            return values

        pricelist = self.env["product.template"]._dally_shop_pricelist()
        target_currency = pricelist.currency_id
        values["dally_shop_delivery_fee"] = method.currency_id._convert(
            method.fixed_fee,
            target_currency,
            self.env.company,
            fields.Date.context_today(self),
        )
        return values
