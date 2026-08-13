# -*- coding: utf-8 -*-
"""The margin — and, more importantly, the cases where it must refuse to exist.

A wrong margin is acted on: someone commits to a price because the screen said the
deal made money. A blank margin with a stated reason gets fixed. So most of these
tests assert a refusal, and check that the refusal says something the operator can act
on rather than just being empty.
"""

from odoo.exceptions import ValidationError

from .common import TradeCase
from odoo.tests import tagged


@tagged("post_install", "-at_install", "dally")
class TestTradeMargin(TradeCase):

    # ─── Single currency: plain arithmetic ────────────────────────────

    def test_margin_in_one_currency(self):
        deal = self._deal()
        self._line(deal)  # 100 × 10 purchase, 100 × 14 sale

        self.assertTrue(deal.margin_computable, deal.margin_blocker)
        self.assertEqual(deal.purchase_subtotal, 1000.0)
        self.assertEqual(deal.sale_subtotal, 1400.0)
        self.assertEqual(deal.gross_margin, 400.0)
        self.assertEqual(deal.net_margin, 400.0)
        self.assertAlmostEqual(deal.margin_rate, 400.0 / 1400.0, places=6)
        self.assertFalse(deal.margin_blocker)

    def test_costs_reduce_the_net_margin_but_not_the_gross(self):
        deal = self._deal()
        self._line(deal)
        self.env["dally.trade.cost"].create({
            "opportunity_id": deal.id,
            "category": "freight",
            "name": "Fret principal",
            "amount": 150.0,
            "currency_id": self.company_currency.id,
        })

        self.assertEqual(deal.gross_margin, 400.0)
        self.assertEqual(deal.cost_total_analysis, 150.0)
        self.assertEqual(deal.net_margin, 250.0)

    # ─── Multi-currency: no naive subtraction ─────────────────────────

    def test_different_currencies_without_conversion_refuse_to_compute(self):
        """The central guarantee: 1000 CNY and 1400 EUR do not subtract."""
        deal = self._deal(purchase_currency_id=self.other_currency.id)
        self._line(deal)

        self.assertFalse(
            deal.margin_computable,
            "A margin was computed across two currencies with no declared conversion.",
        )
        self.assertEqual(deal.gross_margin, 0.0)
        self.assertEqual(deal.net_margin, 0.0)
        self.assertIn(self.other_currency.name, deal.margin_blocker)

    def test_manual_conversion_produces_a_margin(self):
        deal = self._deal(purchase_currency_id=self.other_currency.id)
        self._line(deal)
        deal.write({
            "conversion_currency_id": deal.analysis_currency_id.id,
            "conversion_date": "2026-01-15",
            "conversion_rate_source": "manual",
            "purchase_conversion_rate": 0.5,
            "sale_conversion_rate": 1.0,
        })

        self.assertTrue(deal.margin_computable, deal.margin_blocker)
        # 1000 of the other currency at 0.5 = 500 in the analysis currency.
        self.assertEqual(deal.gross_margin, 1400.0 - 500.0)

    def test_conversion_currency_must_be_the_analysis_currency(self):
        """Otherwise the rate converts into a currency the margin is not expressed in."""
        deal = self._deal(purchase_currency_id=self.other_currency.id)
        self._line(deal)
        deal.write({
            "conversion_currency_id": self.other_currency.id,
            "conversion_date": "2026-01-15",
            "conversion_rate_source": "manual",
            "purchase_conversion_rate": 0.5,
            "sale_conversion_rate": 1.0,
        })

        self.assertFalse(deal.margin_computable)
        self.assertIn(self.other_currency.name, deal.margin_blocker)

    def test_incomplete_conversion_is_refused_at_write_time(self):
        """A rate without a date cannot be audited, so it is not a conversion."""
        deal = self._deal(purchase_currency_id=self.other_currency.id)
        with self.assertRaises(ValidationError):
            deal.write({
                "conversion_currency_id": deal.analysis_currency_id.id,
                # no date, no source
            })

    def test_manual_source_requires_a_positive_rate(self):
        deal = self._deal(purchase_currency_id=self.other_currency.id)
        with self.assertRaises(ValidationError):
            deal.write({
                "conversion_currency_id": deal.analysis_currency_id.id,
                "conversion_date": "2026-01-15",
                "conversion_rate_source": "manual",
                "purchase_conversion_rate": 0.0,
                "sale_conversion_rate": 1.0,
            })

    def test_a_cost_in_a_third_currency_blocks_and_names_itself(self):
        deal = self._deal()
        self._line(deal)
        self.env["dally.trade.cost"].create({
            "opportunity_id": deal.id,
            "category": "customs",
            "name": "Droits de douane",
            "amount": 90.0,
            "currency_id": self.other_currency.id,
        })

        self.assertFalse(deal.margin_computable)
        self.assertIn(self.other_currency.name, deal.margin_blocker)

    # ─── Revenue model per operation type ─────────────────────────────

    def test_brokerage_has_no_purchase_side_in_the_margin(self):
        """A courtage never bought anything, so nothing is subtracted."""
        deal = self._deal(
            operation_type="brokerage", supplier_id=self.supplier.id,
        )
        self.env["dally.trade.commission"].create({
            "opportunity_id": deal.id,
            "name": "Commission d'apport",
            "direction": "receivable",
            "partner_id": self.supplier.id,
            "basis": "fixed",
            "fixed_amount": 2500.0,
            "currency_id": self.company_currency.id,
        })

        self.assertTrue(deal.margin_computable, deal.margin_blocker)
        self.assertEqual(deal.revenue_analysis, 2500.0)
        self.assertEqual(deal.gross_margin, 2500.0)
        self.assertEqual(deal.net_margin, 2500.0)

    def test_a_brokerage_line_may_not_carry_a_purchase_price(self):
        deal = self._deal(operation_type="brokerage")
        with self.assertRaises(ValidationError):
            self._line(deal, purchase_unit_price=10.0)

    def test_payable_commission_reduces_the_margin(self):
        deal = self._deal()
        self._line(deal)
        self.env["dally.trade.commission"].create({
            "opportunity_id": deal.id,
            "name": "Commission d'intermédiaire",
            "direction": "payable",
            "partner_id": self.broker.id,
            "basis": "fixed",
            "fixed_amount": 100.0,
            "currency_id": self.company_currency.id,
        })

        self.assertEqual(deal.commission_total_analysis, 100.0)
        self.assertEqual(deal.net_margin, 300.0)

    # ─── Commissions: the arithmetic is resolved once ─────────────────

    def test_percentage_commission_on_the_sale_total(self):
        deal = self._deal()
        self._line(deal)
        commission = self.env["dally.trade.commission"].create({
            "opportunity_id": deal.id,
            "name": "Commission 3 %",
            "direction": "receivable",
            "partner_id": self.customer.id,
            "basis": "percentage",
            "rate": 0.03,
            "base_field": "sale_subtotal",
            "currency_id": self.company_currency.id,
        })

        self.assertAlmostEqual(commission.computed_amount, 1400.0 * 0.03, places=6)

    def test_percentage_commission_needs_a_base(self):
        deal = self._deal()
        with self.assertRaises(ValidationError):
            self.env["dally.trade.commission"].create({
                "opportunity_id": deal.id,
                "name": "Commission sans base",
                "direction": "receivable",
                "partner_id": self.customer.id,
                "basis": "percentage",
                "rate": 0.03,
                "currency_id": self.company_currency.id,
            })

    def test_a_rate_above_one_is_refused_as_a_unit_mistake(self):
        """3 instead of 0,03 would inflate every margin below it."""
        deal = self._deal()
        with self.assertRaises(ValidationError):
            self.env["dally.trade.commission"].create({
                "opportunity_id": deal.id,
                "name": "Commission mal saisie",
                "direction": "receivable",
                "partner_id": self.customer.id,
                "basis": "percentage",
                "rate": 3.0,
                "base_field": "sale_subtotal",
                "currency_id": self.company_currency.id,
            })

    def test_percentage_on_a_base_in_another_currency_is_refused(self):
        """It would silently assert a 1:1 exchange rate."""
        deal = self._deal()
        self._line(deal)
        with self.assertRaises(ValidationError):
            self.env["dally.trade.commission"].create({
                "opportunity_id": deal.id,
                "name": "Commission en devise tierce",
                "direction": "receivable",
                "partner_id": self.customer.id,
                "basis": "percentage",
                "rate": 0.03,
                "base_field": "sale_subtotal",
                "currency_id": self.other_currency.id,
            })

    def test_no_default_commission_rate(self):
        """A commission created without a rate has none, not a house default."""
        deal = self._deal()
        commission = self.env["dally.trade.commission"].create({
            "opportunity_id": deal.id,
            "name": "Commission forfaitaire",
            "direction": "receivable",
            "partner_id": self.customer.id,
            "basis": "fixed",
            "fixed_amount": 500.0,
            "currency_id": self.company_currency.id,
        })
        self.assertEqual(commission.rate, 0.0)

    # ─── No margin policy in the code ─────────────────────────────────

    def test_no_default_margin_is_applied_to_a_line(self):
        """A sale price is entered, never derived from the purchase price."""
        deal = self._deal()
        line = self._line(deal, sale_unit_price=0.0)

        self.assertEqual(
            line.sale_unit_price, 0.0,
            "A sale price appeared without anyone entering one.",
        )
        self.assertEqual(deal.sale_subtotal, 0.0)

    def test_costs_are_not_negative(self):
        deal = self._deal()
        with self.assertRaises(ValidationError):
            self.env["dally.trade.cost"].create({
                "opportunity_id": deal.id,
                "category": "other",
                "name": "Remboursement",
                "amount": -50.0,
                "currency_id": self.company_currency.id,
            })
