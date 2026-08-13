# -*- coding: utf-8 -*-
"""Conversions into native documents — a real line, or no document at all.

The same rule as dally_sourcing (ADR-013), and for the same reason: an order with no
usable line can be confirmed and reported on while nobody can tell what was meant to
be bought, and a zero-priced sale line can additionally be invoiced.

The type rules are tested here too, because they are the thing that distinguishes this
module from a duplicated sourcing: a courtage must not be able to produce a purchase
order.
"""

from odoo.exceptions import UserError, ValidationError

from .common import TradeCase
from odoo.tests import tagged


@tagged("post_install", "-at_install", "dally")
class TestTradeConversions(TradeCase):

    # ─── Purchase order ───────────────────────────────────────────────

    def test_purchase_order_carries_usable_lines(self):
        deal = self._deal()
        self._line(deal)
        self._to_contracted(deal)

        deal.action_create_purchase_order()
        order = deal.purchase_order_ids

        self.assertEqual(len(order), 1)
        self.assertEqual(len(order.order_line), 1, "The purchase order has no line.")
        line = order.order_line
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.product_qty, 100.0)
        self.assertEqual(line.price_unit, 10.0)
        self.assertTrue(line.name)
        self.assertEqual(order.partner_id, self.supplier)
        self.assertEqual(order.dally_trade_opportunity_id, deal)
        self.assertEqual(deal.state, "purchasing")

    def test_a_brokerage_refuses_to_produce_a_purchase_order(self):
        """It would record a liability DallyTrading does not have."""
        deal = self._deal(operation_type="brokerage")
        self._line(deal, purchase_unit_price=0.0)
        self._to_contracted(deal)

        with self.assertRaises(UserError):
            deal.action_create_purchase_order()

        self.assertFalse(deal.purchase_order_ids)
        self.assertFalse(self.env["purchase.order"].search([
            ("dally_trade_opportunity_id", "=", deal.id),
        ]))

    def test_a_commission_deal_refuses_to_produce_a_purchase_order(self):
        deal = self._deal(
            operation_type="commission",
            principal_id=self.principal.id,
            supplier_id=False,
        )
        self._line(deal, purchase_unit_price=0.0)
        self._to_contracted(deal)

        with self.assertRaises(UserError):
            deal.action_create_purchase_order()

    def test_purchase_order_refused_without_a_product(self):
        deal = self._deal()
        self._line(deal, product_id=False)
        self._to_contracted(deal)

        with self.assertRaises(UserError):
            deal.action_create_purchase_order()

        self.assertFalse(deal.purchase_order_ids)

    def test_purchase_order_refused_with_a_zero_price(self):
        deal = self._deal()
        self._line(deal, purchase_unit_price=0.0)
        self._to_contracted(deal)

        with self.assertRaises(UserError):
            deal.action_create_purchase_order()

        self.assertFalse(deal.purchase_order_ids)

    def test_purchase_order_refused_before_the_deal_is_contracted(self):
        deal = self._deal()
        self._line(deal)
        deal.action_qualify()
        deal.action_structure()

        with self.assertRaises(UserError):
            deal.action_create_purchase_order()

    def test_a_partially_usable_deal_produces_no_order_at_all(self):
        """Half an order is worse than none: the missing half is invisible."""
        deal = self._deal()
        self._line(deal)
        self._line(deal, description="Ligne sans produit", product_id=False)
        self._to_contracted(deal)

        with self.assertRaises(UserError):
            deal.action_create_purchase_order()

        self.assertFalse(deal.purchase_order_ids)

    def test_purchase_conversion_is_idempotent(self):
        deal = self._deal()
        self._line(deal)
        self._to_contracted(deal)
        deal.action_create_purchase_order()
        first = deal.purchase_order_ids

        deal.action_create_purchase_order()

        self.assertEqual(
            deal.purchase_order_ids, first,
            "A second purchase order was raised against the same deal.",
        )

    # ─── Sales order ──────────────────────────────────────────────────

    def test_sale_order_carries_usable_lines(self):
        deal = self._deal()
        self._line(deal)
        self._to_contracted(deal)

        deal.action_create_sale_order()
        order = deal.sale_order_ids

        self.assertEqual(len(order), 1)
        self.assertEqual(len(order.order_line), 1)
        line = order.order_line
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.product_uom_qty, 100.0)
        self.assertEqual(line.price_unit, 14.0)
        self.assertEqual(order.partner_id, self.customer)
        self.assertEqual(order.dally_trade_opportunity_id, deal)

    def test_a_brokerage_may_still_invoice(self):
        """A courtage does not buy, but it does bill its fee."""
        deal = self._deal(operation_type="brokerage")
        self._line(deal, purchase_unit_price=0.0, sale_unit_price=2500.0,
                   quantity=1.0)
        self._to_contracted(deal)

        deal.action_create_sale_order()

        self.assertEqual(len(deal.sale_order_ids), 1)
        self.assertEqual(deal.sale_order_ids.order_line.price_unit, 2500.0)

    def test_sale_order_refused_with_a_zero_price(self):
        deal = self._deal()
        self._line(deal, sale_unit_price=0.0)
        with self.assertRaises(UserError):
            self._to_contracted(deal)

        self.assertFalse(deal.sale_order_ids)

    def test_sale_order_refused_without_a_customer(self):
        deal = self._deal(operation_type="purchase_resale")
        self._line(deal)
        self._to_contracted(deal)
        with self.assertRaises(ValidationError):
            deal.customer_id = False

        self.assertTrue(deal.customer_id)
        self.assertFalse(deal.sale_order_ids)

    def test_sale_conversion_is_idempotent(self):
        deal = self._deal()
        self._line(deal)
        self._to_contracted(deal)
        deal.action_create_sale_order()
        first = deal.sale_order_ids

        deal.action_create_sale_order()

        self.assertEqual(deal.sale_order_ids, first)

    def test_line_description_keeps_the_specification(self):
        deal = self._deal()
        self._line(deal, specifications="Monocristallin 400 W, garantie 10 ans")
        self._to_contracted(deal)

        deal.action_create_sale_order()
        description = deal.sale_order_ids.order_line.name

        self.assertIn("Traded goods", description)
        self.assertIn("Monocristallin", description)

    # ─── Freight stays in dally_freight ───────────────────────────────

    def test_shipment_is_created_in_dally_freight(self):
        deal = self._deal()
        self._line(deal)
        self._to_contracted(deal)

        deal.action_create_shipment()

        self.assertEqual(len(deal.shipment_ids), 1)
        shipment = deal.shipment_ids
        self.assertEqual(shipment._name, "dally.shipment")
        self.assertEqual(shipment.partner_id, self.customer)
        self.assertEqual(shipment.dally_trade_opportunity_id, deal)

    def test_shipment_creation_is_idempotent(self):
        deal = self._deal()
        self._line(deal)
        self._to_contracted(deal)
        deal.action_create_shipment()
        first = deal.shipment_ids

        deal.action_create_shipment()

        self.assertEqual(deal.shipment_ids, first)

    def test_the_trade_module_defines_no_shipment_model_of_its_own(self):
        """Freight has one home. A parallel model would give two answers."""
        trade_models = [
            name for name in self.env
            if name.startswith("dally.trade.")
        ]
        for name in trade_models:
            self.assertNotIn(
                "shipment", name,
                f"{name} duplicates dally_freight's responsibility.",
            )
            self.assertNotIn(
                "product", name,
                f"{name} duplicates product.product.",
            )
