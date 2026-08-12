# -*- coding: utf-8 -*-
"""Link a quotation back to the request it came from.

One field, on purpose. The quotation is a native ``sale.order`` and stays one:
pricing, taxes, terms and the whole sales workflow are Odoo's, not ours (§70).
What Odoo cannot know is which public request a quotation answers, and that is the
only thing added here.
"""

from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    dally_quote_request_id = fields.Many2one(
        comodel_name="dally.quote.request",
        string="Quote Request",
        index=True,
        copy=False,
        ondelete="set null",
        help="Public request this quotation answers. Set when the quotation is "
             "raised from the request during qualification.",
    )
    dally_reference = fields.Char(
        related="dally_quote_request_id.reference",
        string="DallyTrading Reference",
        store=True,
        index=True,
        readonly=True,
        help="The reference the customer quotes. Stored so a quotation can be "
             "found by it without a join.",
    )
