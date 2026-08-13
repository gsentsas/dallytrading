# -*- coding: utf-8 -*-
"""Link purchase and sales orders back to the sourcing request that produced them.

One field on each, on purpose. Purchase and Sales are native Odoo applications and
stay that way: pricing, taxes, terms, receipts and invoicing are theirs (§23). What
Odoo cannot know is which sourcing case an order came out of, and that is the only
thing added here.

Kept in a single file because it is two nearly identical extensions; splitting them
would add navigation cost without adding clarity.
"""

from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    dally_sourcing_request_id = fields.Many2one(
        comodel_name="dally.sourcing.request",
        string="Sourcing Request",
        index=True,
        copy=False,
        ondelete="set null",
        help="The sourcing request this purchase answers. Set when the order is "
             "raised from the selected supplier offer.",
    )
    dally_sourcing_reference = fields.Char(
        related="dally_sourcing_request_id.reference",
        string="Sourcing Reference",
        store=True,
        index=True,
        readonly=True,
        help="Stored so a purchase can be found by the sourcing reference without a "
             "join — which is how support looks it up.",
    )


class SaleOrder(models.Model):
    _inherit = "sale.order"

    dally_sourcing_request_id = fields.Many2one(
        comodel_name="dally.sourcing.request",
        string="Sourcing Request",
        index=True,
        copy=False,
        ondelete="set null",
        help="The sourcing request this sale answers. Set when the order is raised "
             "from the accepted customer proposal.",
    )
    dally_sourcing_reference = fields.Char(
        related="dally_sourcing_request_id.reference",
        string="Sourcing Reference",
        store=True,
        index=True,
        readonly=True,
    )
