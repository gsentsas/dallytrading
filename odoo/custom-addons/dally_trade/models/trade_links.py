# -*- coding: utf-8 -*-
"""Link native documents and shipments back to the trade opportunity behind them.

One field on each, and nothing else. Purchase, Sales, Accounting and Inventory are
native Odoo applications and stay that way: pricing, taxes, terms, receipts, invoicing
and stock are theirs. What Odoo cannot know is which trade deal a document came out of,
and that is the only thing added here.

The extension of ``dally.shipment`` lives in this module rather than in
``dally_freight``, so that freight has no knowledge of trade. The dependency runs one
way: trade knows about freight, freight does not know about trade. Reversing it would
mean a freight-only deployment could not exist.
"""

from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    dally_trade_opportunity_id = fields.Many2one(
        comodel_name="dally.trade.opportunity",
        string="Opération de trading",
        index=True,
        copy=False,
        ondelete="set null",
        help="The trade deal this purchase belongs to. Set when the order is raised "
             "from the deal's purchase side.",
    )
    dally_trade_reference = fields.Char(
        related="dally_trade_opportunity_id.reference",
        string="Référence trading",
        store=True,
        index=True,
        readonly=True,
        help="Stored so a purchase can be found by the trade reference without a join "
             "— which is how support looks it up.",
    )


class SaleOrder(models.Model):
    _inherit = "sale.order"

    dally_trade_opportunity_id = fields.Many2one(
        comodel_name="dally.trade.opportunity",
        string="Opération de trading",
        index=True,
        copy=False,
        ondelete="set null",
        help="The trade deal this sale belongs to.",
    )
    dally_trade_reference = fields.Char(
        related="dally_trade_opportunity_id.reference",
        string="Référence trading",
        store=True,
        index=True,
        readonly=True,
    )


class DallyShipment(models.Model):
    _inherit = "dally.shipment"

    dally_trade_opportunity_id = fields.Many2one(
        comodel_name="dally.trade.opportunity",
        string="Opération de trading",
        index=True,
        copy=False,
        ondelete="set null",
        help="The trade deal that generated this shipment, when it came from one. "
             "Most shipments do not: freight is a business in its own right.",
    )
