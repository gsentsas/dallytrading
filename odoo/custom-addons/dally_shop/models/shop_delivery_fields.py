# -*- coding: utf-8 -*-
"""Champs liés stockés utiles aux vues et domaines du workflow de remise."""

from odoo import fields, models

from .shop_delivery import DELIVERY_KINDS


class SaleOrderShopDeliveryViewFields(models.Model):
    _inherit = "sale.order"

    dally_shop_delivery_kind = fields.Selection(
        selection=DELIVERY_KINDS,
        related="dally_shop_delivery_method_id.kind",
        string="Type de remise",
        store=True,
        readonly=True,
    )
    dally_shop_delivery_requires_address = fields.Boolean(
        related="dally_shop_delivery_method_id.requires_address",
        string="Adresse de livraison requise",
        store=True,
        readonly=True,
    )
