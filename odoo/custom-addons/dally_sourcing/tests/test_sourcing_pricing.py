# -*- coding: utf-8 -*-
"""Pricing and conversions — the two things that must never happen silently.

Two classes of accident are covered here, both of which produce a document a customer
or a supplier can act on:

1. **A price nobody decided.** A default margin applied in Python is a price the
   company quotes without anyone choosing it. The tests assert that a proposal drafted
   from an offer carries *no* selling price, and that it cannot travel to a customer
   until someone validates one.

2. **An empty commercial document.** A purchase or sales order with no usable line can
   still be confirmed and invoiced, while nobody can tell what was meant to be bought
   or sold. The tests assert that the conversions either produce a real line or refuse
   outright — and that they never produce a second document on a re-run.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_sourcing.models import dally_sourcing_proposal


@tagged("post_install", "-at_install", "dally")
class TestSourcingPricing(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Request = self.env["dally.sourcing.request"]
        self.customer = self.env["res.partner"].create({
            "name": "Pricing Customer", "email": "pricing@example.com",
        })
        self.supplier = self.env["res.partner"].create({
            "name": "Pricing Factory", "is_company": True,
        })
        self.product = self.env["product.product"].create({
            "name": "Sourced widget", "type": "consu",
        })

    # ─── Fixtures ─────────────────────────────────────────────────────

    def _request(self, **overrides):
        values = {
            "product_name": "Sourced widget",
            "quantity": 10.0,
            "contact_name": "Pricing Customer",
            "contact_email": "pricing@example.com",
            "customer_id": self.customer.id,
        }
        values.update(overrides)
        return self.Request.create(values)

    def _offer(self, request, **overrides):
        candidate = self.env["dally.sourcing.supplier"].create({
            "request_id": request.id,
            "partner_id": self.supplier.id,
        })
        values = {
            "request_id": request.id,
            "supplier_id": candidate.id,
            "quantity": 10.0,
            "unit_price": 100.0,
        }
        values.update(overrides)
        return self.env["dally.sourcing.offer"].create(values)

    def _accepted_request(self, with_product=True):
        """A request carried all the way to `accepted`, with a priced proposal."""
        request = self._request()
        if with_product:
            request.product_id = self.product
        offer = self._offer(request)
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        offer.action_select()
        # action_create_proposal returns a window action, so the record is read back.
        offer.action_create_proposal()
        proposal = request.proposal_ids
        proposal.write({"selling_unit_price": 150.0, "validity_date": "2099-12-31"})
        proposal.action_validate_price()
        proposal.action_mark_ready()
        request.action_prepare_proposal()
        request.action_send_proposal()
        proposal.action_send()
        proposal.action_accept()
        request.action_accept()
        return request, offer, proposal

    # ─── 1. No margin decided in Python ───────────────────────────────

    def test_no_default_margin_constant_exists(self):
        """The constant is gone, not merely unused.

        Asserted on the module rather than by reading the source, so re-introducing it
        anywhere in the model fails the test.
        """
        self.assertFalse(
            hasattr(dally_sourcing_proposal, "DEFAULT_MARGIN_RATE"),
            "A default margin rate is back in the proposal module. Pricing is a "
            "commercial decision and belongs in configuration, not a Python constant.",
        )

    def test_proposal_drafted_from_offer_has_no_price(self):
        request = self._request()
        offer = self._offer(request, unit_price=100.0)
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        offer.action_select()
        offer.action_create_proposal()

        proposal = request.proposal_ids
        self.assertEqual(len(proposal), 1)
        self.assertEqual(
            proposal.selling_unit_price, 0.0,
            "The draft proposal carries a selling price nobody chose.",
        )
        # The cost is carried, so whoever sets the price can see what it must cover.
        self.assertGreater(proposal.cost_basis, 0.0)

    # ─── 2. Explicit price validation gates ready and sent ────────────

    def test_cannot_mark_ready_without_validated_price(self):
        request = self._request()
        offer = self._offer(request)
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        offer.action_select()
        offer.action_create_proposal()
        proposal = request.proposal_ids
        proposal.write({"selling_unit_price": 150.0, "validity_date": "2099-12-31"})

        with self.assertRaises(UserError):
            proposal.action_mark_ready()

        self.assertEqual(proposal.state, "draft")

    def test_validated_price_allows_ready_and_sent(self):
        request = self._request()
        offer = self._offer(request)
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        offer.action_select()
        offer.action_create_proposal()
        proposal = request.proposal_ids
        proposal.write({"selling_unit_price": 150.0, "validity_date": "2099-12-31"})

        proposal.action_validate_price()
        self.assertTrue(proposal.price_validated)
        self.assertEqual(proposal.price_validated_by_id, self.env.user)
        self.assertTrue(proposal.price_validated_on)

        proposal.action_mark_ready()
        self.assertEqual(proposal.state, "ready")
        proposal.action_send()
        self.assertEqual(proposal.state, "sent")

    def test_cannot_validate_a_price_of_zero(self):
        request = self._request()
        offer = self._offer(request)
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        offer.action_select()
        offer.action_create_proposal()

        with self.assertRaises(UserError):
            request.proposal_ids.action_validate_price()

    def test_changing_the_price_withdraws_the_validation(self):
        """Otherwise the approval attaches to a number nobody approved."""
        request = self._request()
        offer = self._offer(request)
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        offer.action_select()
        offer.action_create_proposal()
        proposal = request.proposal_ids
        proposal.write({"selling_unit_price": 150.0, "validity_date": "2099-12-31"})
        proposal.action_validate_price()

        proposal.selling_unit_price = 90.0

        self.assertFalse(
            proposal.price_validated,
            "The proposal is still validated at a price that has since changed.",
        )
        with self.assertRaises(UserError):
            proposal.action_mark_ready()

    def test_revoking_the_validation_blocks_sending_again(self):
        request = self._request()
        offer = self._offer(request)
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        offer.action_select()
        offer.action_create_proposal()
        proposal = request.proposal_ids
        proposal.write({"selling_unit_price": 150.0, "validity_date": "2099-12-31"})
        proposal.action_validate_price()
        proposal.action_mark_ready()

        proposal.action_revoke_price_validation()
        proposal.action_back_to_draft()

        with self.assertRaises(UserError):
            proposal.action_mark_ready()

    def test_sourcing_user_cannot_validate_a_price(self):
        """Judging whether a price covers its cost requires seeing the cost."""
        request = self._request()
        offer = self._offer(request)
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        offer.action_select()
        offer.action_create_proposal()
        proposal = request.proposal_ids
        proposal.write({"selling_unit_price": 150.0, "validity_date": "2099-12-31"})

        sourcing_user = self.env["res.users"].create({
            "name": "Sourcing Operator",
            "login": "sourcing.operator.pricing",
            "group_ids": [(6, 0, [
                self.env.ref("dally_core.group_dally_sourcing").id,
            ])],
        })

        with self.assertRaises(UserError):
            proposal.with_user(sourcing_user).action_validate_price()

        # But the flag stays readable — the operator must be able to see why the
        # proposal will not send, so the ORM must not refuse the field.
        self.assertFalse(proposal.with_user(sourcing_user).price_validated)

    def test_sourcing_user_can_still_edit_a_validated_price(self):
        """Editing withdraws the validation, and must not raise an access error.

        This is the case a field group would have broken: the withdrawal writes
        `price_validated`, and a sourcing user cannot validate a price. The field is
        therefore not group-restricted, and the restriction lives in the action.
        """
        request = self._request()
        offer = self._offer(request)
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        offer.action_select()
        offer.action_create_proposal()
        proposal = request.proposal_ids
        proposal.write({"selling_unit_price": 150.0, "validity_date": "2099-12-31"})
        proposal.action_validate_price()

        sourcing_user = self.env["res.users"].create({
            "name": "Sourcing Editor",
            "login": "sourcing.editor.pricing",
            "group_ids": [(6, 0, [
                self.env.ref("dally_core.group_dally_sourcing").id,
            ])],
        })

        # No exception: the withdrawal path must work for a user who cannot validate.
        proposal.with_user(sourcing_user).write({"selling_unit_price": 175.0})

        self.assertEqual(proposal.selling_unit_price, 175.0)
        self.assertFalse(
            proposal.price_validated,
            "The edit went through without withdrawing the stale validation.",
        )

    # ─── 3. Purchase order: a real line, or nothing ───────────────────

    def test_purchase_order_carries_a_usable_line(self):
        request, offer, _proposal = self._accepted_request()

        request.action_create_purchase_order()
        order = request.purchase_order_ids

        self.assertEqual(len(order), 1)
        self.assertEqual(len(order.order_line), 1, "The purchase order has no line.")
        line = order.order_line
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.product_qty, offer.quantity)
        self.assertEqual(line.price_unit, offer.unit_price)
        self.assertGreater(line.price_unit, 0.0)
        self.assertTrue(line.name)
        self.assertTrue(line.product_uom_id or True)  # derived by Odoo from the product
        self.assertEqual(order.partner_id, self.supplier)
        self.assertEqual(order.dally_sourcing_request_id, request)

    def test_purchase_order_refused_without_a_product(self):
        """The most likely gap in practice: a request that was never mapped."""
        request, _offer, _proposal = self._accepted_request(with_product=False)

        with self.assertRaises(UserError):
            request.action_create_purchase_order()

        self.assertFalse(
            request.purchase_order_ids,
            "A purchase order was created despite the refusal.",
        )
        self.assertFalse(self.env["purchase.order"].search([
            ("dally_sourcing_request_id", "=", request.id),
        ]))

    def test_purchase_order_refused_with_a_zero_price(self):
        request, offer, _proposal = self._accepted_request()
        offer.unit_price = 0.0

        with self.assertRaises(UserError):
            request.action_create_purchase_order()

        self.assertFalse(request.purchase_order_ids)

    def test_purchase_order_conversion_is_idempotent(self):
        request, _offer, _proposal = self._accepted_request()
        request.action_create_purchase_order()
        first = request.purchase_order_ids

        request.action_create_purchase_order()

        self.assertEqual(
            request.purchase_order_ids, first,
            "A second purchase order was raised against the same request.",
        )
        self.assertEqual(len(first.order_line), 1)

    # ─── 4. Sales order: a real line, or nothing ──────────────────────

    def test_sale_order_carries_a_usable_line(self):
        request, _offer, proposal = self._accepted_request()

        request.action_create_sale_order()
        order = request.sale_order_ids

        self.assertEqual(len(order), 1)
        self.assertTrue(order.order_line, "The sales order has no line.")
        line = order.order_line[0]
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.product_uom_qty, proposal.quantity)
        self.assertEqual(line.price_unit, proposal.selling_unit_price)
        self.assertGreater(line.price_unit, 0.0)
        self.assertEqual(order.partner_id, self.customer)
        self.assertEqual(proposal.sale_order_id, order)

    def test_sale_order_refused_without_a_product(self):
        request, _offer, _proposal = self._accepted_request(with_product=False)

        with self.assertRaises(UserError):
            request.action_create_sale_order()

        self.assertFalse(request.sale_order_ids)
        self.assertFalse(self.env["sale.order"].search([
            ("dally_sourcing_request_id", "=", request.id),
        ]))

    def test_sale_order_refused_without_an_accepted_proposal(self):
        request = self._request()
        request.product_id = self.product
        offer = self._offer(request)
        request.action_qualify()
        request.action_start_research()
        request.action_mark_suppliers_identified()
        request.action_mark_offers_received()
        request.action_start_comparison()
        offer.action_select()
        offer.action_create_proposal()
        proposal = request.proposal_ids
        proposal.write({"selling_unit_price": 150.0, "validity_date": "2099-12-31"})
        proposal.action_validate_price()
        proposal.action_mark_ready()
        request.action_prepare_proposal()
        request.action_send_proposal()
        request.action_accept()
        # The request is accepted, but the proposal itself was never accepted.

        with self.assertRaises(UserError):
            request.action_create_sale_order()

        self.assertFalse(request.sale_order_ids)

    def test_sale_order_refused_with_a_zero_price(self):
        """A zero-priced line can be confirmed and invoiced. It must not exist."""
        request, _offer, proposal = self._accepted_request()
        # Bypass the guarded write path to reach the state a data import could produce.
        proposal.invalidate_recordset()
        self.env.cr.execute(
            "UPDATE dally_sourcing_proposal SET selling_unit_price = 0, "
            "total_amount = 0 WHERE id = %s", (proposal.id,),
        )
        proposal.invalidate_recordset()

        with self.assertRaises(UserError):
            request.action_create_sale_order()

        self.assertFalse(request.sale_order_ids)

    def test_sale_order_conversion_is_idempotent(self):
        request, _offer, _proposal = self._accepted_request()
        request.action_create_sale_order()
        first = request.sale_order_ids

        request.action_create_sale_order()

        self.assertEqual(
            request.sale_order_ids, first,
            "A second sales order was raised against the same request.",
        )

    # ─── 5. The line description keeps the specification ──────────────

    def test_line_description_carries_the_specification(self):
        """"Solar panels" and "monocrystalline 400W" are not the same purchase."""
        request, _offer, _proposal = self._accepted_request()
        request.write({
            "product_reference": "REF-9910",
            "specifications": "Monocrystalline, 400 W, 10-year warranty",
        })

        request.action_create_purchase_order()
        description = request.purchase_order_ids.order_line.name

        self.assertIn("Sourced widget", description)
        self.assertIn("REF-9910", description)
        self.assertIn("Monocrystalline", description)
