# -*- coding: utf-8 -*-
"""Shared fixtures.

Kept in one place because every test file needs a deal in a given state, and building
one inline five times is how the files drift apart until a change breaks four of them
for unrelated reasons.
"""

from odoo.tests import TransactionCase


class TradeCase(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env.user.write({"group_ids": [(4, self.env.ref(
            "dally_trade.group_dally_trade_manager"
        ).id)]})
        self.Deal = self.env["dally.trade.opportunity"]
        self.customer = self.env["res.partner"].create({
            "name": "Trade Customer", "email": "trade.customer@example.com",
            "is_company": True,
        })
        self.supplier = self.env["res.partner"].create({
            "name": "Trade Supplier", "is_company": True,
        })
        self.principal = self.env["res.partner"].create({
            "name": "Trade Principal", "is_company": True,
        })
        self.broker = self.env["res.partner"].create({"name": "Introducer"})
        self.product = self.env["product.product"].create({
            "name": "Traded goods", "type": "consu",
        })
        self.company_currency = self.env.company.currency_id
        self.other_currency = self.env["res.currency"].search(
            [("id", "!=", self.company_currency.id)], limit=1,
        ) or self.env["res.currency"].create({"name": "TST", "symbol": "T"})

    def _deal(self, **overrides):
        values = {
            "name": "Deal under test",
            "operation_type": "purchase_resale",
            "customer_id": self.customer.id,
            "supplier_id": self.supplier.id,
        }
        values.update(overrides)
        return self.Deal.create(values)

    def _line(self, deal, **overrides):
        values = {
            "opportunity_id": deal.id,
            "product_id": self.product.id,
            "description": "Traded goods, grade A",
            "quantity": 100.0,
            "purchase_unit_price": 10.0,
            "sale_unit_price": 14.0,
        }
        values.update(overrides)
        return self.env["dally.trade.line"].create(values)

    def _to_contracted(self, deal):
        """Carry a deal to `contracted`, approving it if it needs approving."""
        deal.action_qualify()
        deal.action_structure()
        deal.action_start_pricing()
        if deal.approval_required:
            deal.action_request_approval()
            deal.action_approve()
        else:
            deal.action_approve()
        deal.action_send_proposal()
        deal.action_contract()
        return deal
