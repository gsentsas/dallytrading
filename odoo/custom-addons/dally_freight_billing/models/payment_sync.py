# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    dally_external_payment_key = fields.Char(index=True, copy=False)
    dally_collected_by_id = fields.Many2one(
        "res.users",
        string="Collected By",
        domain=[("share", "=", False)],
        copy=False,
    )
    dally_freight_shipment_id = fields.Many2one(
        "dally.shipment",
        string="Freight Shipment",
        index=True,
        copy=False,
        ondelete="set null",
    )

    _dally_external_payment_key_unique = models.Constraint(
        "UNIQUE(dally_external_payment_key)",
        "The external freight payment key must be unique.",
    )
