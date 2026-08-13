# -*- coding: utf-8 -*-
"""Suppliers, offers, proposals and the conversions."""

import re

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestSourcingSuppliersAndOffers(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Request = self.env["dally.sourcing.request"]
        self.Supplier = self.env["dally.sourcing.supplier"]
        self.Offer = self.env["dally.sourcing.offer"]
        self.Partner = self.env["res.partner"]

        self.customer = self.Partner.create({
            "name": "Offer Customer", "email": "offers@example.com",
        })
        self.factory_a = self.Partner.create({
            "name": "Factory A", "is_company": True,
            "email": "a@factory.example", "phone": "+86 10 0000 0001",
        })
        self.factory_b = self.Partner.create({
            "name": "Factory B", "is_company": True,
        })

        self.request = self.Request.create({
            "product_name": "Solar panels 400W",
            "quantity": 100.0,
            "contact_email": "offers@example.com",
            "customer_id": self.customer.id,
        })

        self.eur = self.env.ref("base.EUR", raise_if_not_found=False)
        self.usd = self.env.ref("base.USD", raise_if_not_found=False)

    def _supplier(self, partner=None, **overrides):
        values = {
            "request_id": self.request.id,
            "partner_id": (partner or self.factory_a).id,
        }
        values.update(overrides)
        return self.Supplier.create(values)

    def _offer(self, supplier=None, **overrides):
        values = {
            "request_id": self.request.id,
            "supplier_id": (supplier or self._supplier()).id,
            "quantity": 100.0,
            "unit_price": 80.0,
        }
        values.update(overrides)
        return self.Offer.create(values)

    # ─── Suppliers ────────────────────────────────────────────────────

    def test_supplier_reuses_res_partner(self):
        """No second supplier database (§12)."""
        supplier = self._supplier()
        self.assertEqual(supplier.partner_id, self.factory_a)
        self.assertEqual(supplier.status, "identified")

    def test_same_supplier_cannot_be_added_twice(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        self._supplier()
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._supplier()
            self.env.flush_all()

    def test_several_suppliers_on_one_request(self):
        self._supplier(self.factory_a)
        self._supplier(self.factory_b)
        self.assertEqual(len(self.request.supplier_ids), 2)
        self.assertEqual(self.request.supplier_count, 2)

    def test_country_defaults_from_the_partner(self):
        senegal = self.env.ref("base.sn", raise_if_not_found=False)
        if not senegal:
            self.skipTest("Country data unavailable")
        self.factory_b.country_id = senegal
        supplier = self._supplier(self.factory_b)
        self.assertEqual(supplier.country_id, senegal)

    def test_verified_requires_a_date(self):
        """"Verified" with no date says nothing six months later."""
        with self.assertRaises(ValidationError):
            self._supplier(verified=True)

    def test_mark_verified_stamps_the_date(self):
        supplier = self._supplier()
        supplier.action_mark_verified()
        self.assertTrue(supplier.verified)
        self.assertTrue(supplier.verification_date)

    def test_shortlist_and_reject(self):
        supplier = self._supplier()
        supplier.action_shortlist()
        self.assertEqual(supplier.status, "shortlisted")
        supplier.action_reject()
        self.assertEqual(supplier.status, "rejected")

    def test_negative_moq_is_rejected(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._supplier(minimum_order_quantity=-1)
            self.env.flush_all()

    # ─── Offers ───────────────────────────────────────────────────────

    def test_landed_cost_computation(self):
        offer = self._offer(
            quantity=100.0, unit_price=80.0,
            shipping_cost=1200.0, insurance_cost=150.0,
            customs_estimate=900.0, other_costs=50.0,
        )
        self.assertAlmostEqual(offer.subtotal, 8000.0)
        self.assertAlmostEqual(offer.total_landed_cost, 10300.0)
        self.assertAlmostEqual(offer.landed_unit_cost, 103.0)

    def test_landed_unit_cost_is_what_compares_offers(self):
        """A low unit price with high freight is not a cheap offer."""
        cheap_goods = self._offer(
            supplier=self._supplier(self.factory_a),
            unit_price=70.0, shipping_cost=5000.0,
        )
        pricier_goods = self._offer(
            supplier=self._supplier(self.factory_b),
            unit_price=90.0, shipping_cost=500.0,
        )
        self.assertLess(cheap_goods.unit_price, pricier_goods.unit_price)
        self.assertGreater(
            cheap_goods.landed_unit_cost, pricier_goods.landed_unit_cost,
            "The cheaper unit price lands more expensively",
        )

    def test_offers_in_different_currencies(self):
        if not self.eur or not self.usd:
            self.skipTest("Currency data unavailable")
        first = self._offer(
            supplier=self._supplier(self.factory_a), currency_id=self.eur.id,
        )
        second = self._offer(
            supplier=self._supplier(self.factory_b), currency_id=self.usd.id,
        )
        self.assertNotEqual(first.currency_id, second.currency_id)
        # Each keeps its own currency: converting silently would hide the rate used.
        self.assertEqual(first.currency_id, self.eur)
        self.assertEqual(second.currency_id, self.usd)

    def test_offer_must_belong_to_the_same_request(self):
        """Otherwise one client's supplier and price could land in another's file."""
        other_request = self.Request.create({
            "product_name": "Other", "quantity": 1.0,
            "contact_email": "other@example.com",
        })
        foreign_supplier = self.Supplier.create({
            "request_id": other_request.id, "partner_id": self.factory_b.id,
        })
        with self.assertRaises(ValidationError):
            self.Offer.create({
                "request_id": self.request.id,
                "supplier_id": foreign_supplier.id,
                "quantity": 1.0, "unit_price": 1.0,
            })

    def test_quantity_below_moq_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._offer(quantity=10.0, minimum_order_quantity=50.0)

    def test_negative_costs_are_rejected(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._offer(shipping_cost=-10.0)
            self.env.flush_all()

    def test_sample_cost_without_a_sample_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._offer(sample_cost=50.0, sample_available=False)

    def test_expiry_is_computed_and_searchable(self):
        expired = self._offer(
            supplier=self._supplier(self.factory_a), validity_date="2020-01-01",
        )
        valid = self._offer(
            supplier=self._supplier(self.factory_b), validity_date="2999-01-01",
        )
        self.assertTrue(expired.is_expired)
        self.assertFalse(valid.is_expired)

        found = self.Offer.search([("is_expired", "=", True)])
        self.assertIn(expired, found)
        self.assertNotIn(valid, found)

    # ─── Scores ───────────────────────────────────────────────────────

    def test_overall_score_averages_only_rated_criteria(self):
        """An unrated criterion must not drag the average down to zero."""
        offer = self._offer(quality_score="4", price_score="2")
        self.assertAlmostEqual(offer.overall_score, 3.0)

    def test_overall_score_is_zero_when_nothing_is_rated(self):
        self.assertAlmostEqual(self._offer().overall_score, 0.0)

    def test_all_four_criteria_average(self):
        offer = self._offer(
            quality_score="5", price_score="3",
            lead_time_score="4", reliability_score="4",
        )
        self.assertAlmostEqual(offer.overall_score, 4.0)

    # ─── Selection ────────────────────────────────────────────────────

    def test_select_an_offer(self):
        offer = self._offer()
        offer.action_select()
        self.assertTrue(offer.selected)
        self.assertEqual(offer.supplier_id.status, "selected")
        self.assertEqual(self.request.selected_offer_id, offer)

    def test_selecting_deselects_the_previous_one(self):
        first = self._offer(supplier=self._supplier(self.factory_a))
        second = self._offer(supplier=self._supplier(self.factory_b))

        first.action_select()
        second.action_select()

        self.assertFalse(first.selected)
        self.assertTrue(second.selected)
        self.assertEqual(self.request.selected_offer_id, second)

    def test_two_selected_offers_are_refused(self):
        """Ambiguity here would make purchase-order creation pick one silently."""
        first = self._offer(supplier=self._supplier(self.factory_a))
        first.action_select()
        second = self._offer(supplier=self._supplier(self.factory_b))
        with self.assertRaises(ValidationError):
            second.selected = True

    def test_expired_offer_cannot_be_selected(self):
        offer = self._offer(validity_date="2020-01-01")
        with self.assertRaises(UserError):
            offer.action_select()

    def test_deselect_reverts_the_supplier_status(self):
        offer = self._offer()
        offer.action_select()
        offer.action_deselect()
        self.assertFalse(offer.selected)
        self.assertEqual(offer.supplier_id.status, "shortlisted")


@tagged("post_install", "-at_install", "dally")
class TestSourcingProposalAndConversion(TransactionCase):

    PROPOSAL_RE = re.compile(r"^DT-SRP-\d{4}-\d{6}$")

    def setUp(self):
        super().setUp()
        self.env.user.write({"group_ids": [(4, self.env.ref(
            "dally_sourcing.group_dally_sourcing_manager"
        ).id)]})
        self.Request = self.env["dally.sourcing.request"]
        self.Proposal = self.env["dally.sourcing.proposal"]
        self.customer = self.env["res.partner"].create({
            "name": "Proposal Customer", "email": "proposal@example.com",
        })
        self.factory = self.env["res.partner"].create({
            "name": "Proposal Factory", "is_company": True,
        })
        self.product = self.env["product.product"].create({
            "name": "Water pumps", "type": "consu",
        })
        self.request = self.Request.create({
            "product_name": "Water pumps",
            "product_id": self.product.id,
            "quantity": 50.0,
            "contact_email": "proposal@example.com",
            "customer_id": self.customer.id,
        })
        self.supplier = self.env["dally.sourcing.supplier"].create({
            "request_id": self.request.id, "partner_id": self.factory.id,
        })
        self.offer = self.env["dally.sourcing.offer"].create({
            "request_id": self.request.id,
            "supplier_id": self.supplier.id,
            "quantity": 50.0,
            "unit_price": 200.0,
            "shipping_cost": 1000.0,
        })

    def _advance_to_accepted(self):
        request = self.request
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        request.action_prepare_proposal()
        proposal = self.Proposal.create({
            "request_id": request.id,
            "product_name": "Water pumps",
            "quantity": 50.0,
            "selling_unit_price": 250.0,
            "validity_date": "2999-01-01",
        })
        proposal.action_validate_price()
        request.action_send_proposal()
        request.action_accept()
        return proposal

    # ─── Proposal ─────────────────────────────────────────────────────

    def test_proposal_reference_format(self):
        proposal = self.Proposal.create({
            "request_id": self.request.id, "product_name": "P",
            "quantity": 1.0, "selling_unit_price": 10.0,
        })
        self.assertRegex(proposal.reference, self.PROPOSAL_RE)

    def test_draft_from_offer_requires_a_human_selling_price(self):
        self.offer.action_create_proposal()
        proposal = self.request.proposal_ids
        self.assertEqual(len(proposal), 1)
        self.assertEqual(proposal.selling_unit_price, 0.0)
        self.assertAlmostEqual(proposal.cost_basis, self.offer.total_landed_cost)

    def test_draft_from_offer_copies_no_cost_line(self):
        """The one bridge across the boundary copies a derived price, nothing else."""
        self.offer.action_create_proposal()
        proposal = self.request.proposal_ids

        self.assertAlmostEqual(proposal.estimated_shipping, 0.0)
        self.assertAlmostEqual(proposal.service_fee, 0.0)
        # The cost basis is carried for margin computation, and is group-restricted.
        self.assertAlmostEqual(proposal.cost_basis, self.offer.total_landed_cost)

    def test_margin_excludes_tax(self):
        """Tax is collected, not earned: including it would overstate every margin."""
        proposal = self.Proposal.create({
            "request_id": self.request.id, "product_name": "P",
            "quantity": 10.0, "selling_unit_price": 100.0,
            "tax_amount": 180.0, "cost_basis": 700.0,
        })
        self.assertAlmostEqual(proposal.total_amount, 1180.0)
        self.assertAlmostEqual(proposal.margin, 300.0)
        self.assertAlmostEqual(proposal.margin_rate, 30.0, places=2)

    def test_cannot_mark_ready_without_an_amount(self):
        proposal = self.Proposal.create({
            "request_id": self.request.id, "product_name": "P",
            "quantity": 1.0, "selling_unit_price": 0.0,
        })
        with self.assertRaises(UserError):
            proposal.action_mark_ready()

    def test_cannot_mark_ready_without_a_validity_date(self):
        """A quote with no expiry commits DallyTrading indefinitely."""
        proposal = self.Proposal.create({
            "request_id": self.request.id, "product_name": "P",
            "quantity": 1.0, "selling_unit_price": 100.0,
        })
        with self.assertRaises(UserError):
            proposal.action_mark_ready()

    def test_proposal_lifecycle(self):
        proposal = self.Proposal.create({
            "request_id": self.request.id, "product_name": "P",
            "quantity": 1.0, "selling_unit_price": 100.0,
            "validity_date": "2999-01-01",
        })
        proposal.action_validate_price()
        proposal.action_mark_ready()
        self.assertEqual(proposal.state, "ready")
        proposal.action_send()
        self.assertEqual(proposal.state, "sent")
        self.assertTrue(proposal.sent_date)
        proposal.action_accept()
        self.assertEqual(proposal.state, "accepted")
        self.assertTrue(proposal.decision_date)

    def test_proposal_refuses_an_invalid_transition(self):
        proposal = self.Proposal.create({
            "request_id": self.request.id, "product_name": "P",
            "quantity": 1.0, "selling_unit_price": 100.0,
        })
        with self.assertRaises(UserError):
            proposal.action_accept()

    def test_public_payload_hides_cost_and_margin(self):
        import json
        self.offer.action_create_proposal()
        proposal = self.request.proposal_ids
        proposal.internal_notes = "SECRET negotiation note"

        serialised = json.dumps(proposal._dally_public_payload())

        self.assertNotIn("SECRET", serialised)
        self.assertNotIn("costBasis", serialised)
        self.assertNotIn("margin", serialised)
        self.assertNotIn("Proposal Factory", serialised)
        self.assertNotIn('"id"', serialised)
        self.assertIn(proposal.reference, serialised)

    # ─── Purchase order ───────────────────────────────────────────────

    def test_purchase_order_requires_acceptance(self):
        with self.assertRaises(UserError):
            self.request.action_create_purchase_order()

    def test_purchase_order_requires_a_selected_offer(self):
        self._advance_to_accepted()
        with self.assertRaises(UserError):
            self.request.action_create_purchase_order()

    def test_purchase_order_is_created_from_the_selected_offer(self):
        self._advance_to_accepted()
        self.offer.action_select()

        self.request.action_create_purchase_order()

        self.assertEqual(len(self.request.purchase_order_ids), 1)
        order = self.request.purchase_order_ids
        self.assertEqual(order.partner_id, self.factory)
        self.assertEqual(order.dally_sourcing_request_id, self.request)
        self.assertEqual(order.dally_sourcing_reference, self.request.reference)
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.order_line.product_id, self.product)
        self.assertEqual(order.order_line.product_qty, self.offer.quantity)
        self.assertEqual(order.order_line.price_unit, self.offer.unit_price)
        self.assertEqual(self.request.state, "purchasing")

    def test_no_second_purchase_order(self):
        self._advance_to_accepted()
        self.offer.action_select()
        self.request.action_create_purchase_order()
        count = len(self.request.purchase_order_ids)

        self.request.action_create_purchase_order()

        self.assertEqual(len(self.request.purchase_order_ids), count)

    # ─── Sales order ──────────────────────────────────────────────────

    def test_sale_order_requires_acceptance(self):
        with self.assertRaises(UserError):
            self.request.action_create_sale_order()

    def test_sale_order_requires_an_accepted_proposal(self):
        self._advance_to_accepted()
        with self.assertRaises(UserError):
            self.request.action_create_sale_order()

    def test_sale_order_is_created_from_the_accepted_proposal(self):
        proposal = self._advance_to_accepted()
        proposal.action_mark_ready()
        proposal.action_send()
        proposal.action_accept()

        self.request.action_create_sale_order()

        self.assertEqual(len(self.request.sale_order_ids), 1)
        order = self.request.sale_order_ids
        self.assertEqual(order.partner_id, self.customer)
        self.assertEqual(order.dally_sourcing_request_id, self.request)
        self.assertEqual(proposal.sale_order_id, order)
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.order_line.product_id, self.product)
        self.assertEqual(order.order_line.product_uom_qty, proposal.quantity)
        self.assertEqual(order.order_line.price_unit, proposal.selling_unit_price)

    def test_no_second_sale_order(self):
        proposal = self._advance_to_accepted()
        proposal.action_mark_ready()
        proposal.action_send()
        proposal.action_accept()
        self.request.action_create_sale_order()
        count = len(self.request.sale_order_ids)

        self.request.action_create_sale_order()

        self.assertEqual(len(self.request.sale_order_ids), count)

    def test_no_shipment_is_created(self):
        """Freight stays with dally_freight; a shipment comes later (§24)."""
        before = self.env["dally.shipment"].search_count([])
        proposal = self._advance_to_accepted()
        self.offer.action_select()
        self.request.action_create_purchase_order()
        proposal.action_mark_ready()
        proposal.action_send()
        proposal.action_accept()
        self.request.action_create_sale_order()

        self.assertEqual(self.env["dally.shipment"].search_count([]), before)
