# -*- coding: utf-8 -*-
"""The workflow: which transitions are allowed, and which must be refused.

The refusals matter more than the acceptances. A request that can jump from `new` to
`completed` is a file closed with no supplier, no offer and no purchase behind it —
and nobody notices until someone asks what was actually bought.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_sourcing.models.dally_sourcing_request import (
    ALLOWED_TRANSITIONS,
    SOURCING_STATES,
    TERMINAL_STATES,
)


@tagged("post_install", "-at_install", "dally")
class TestSourcingWorkflow(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Request = self.env["dally.sourcing.request"]
        self.partner = self.env["res.partner"].create({
            "name": "Workflow Customer", "email": "workflow@example.com",
        })
        self.supplier_partner = self.env["res.partner"].create({
            "name": "Factory Ltd", "is_company": True,
        })

    def _request(self, **overrides):
        values = {
            "product_name": "Test product",
            "quantity": 10.0,
            "contact_name": "Workflow Customer",
            "contact_email": "workflow@example.com",
            "customer_id": self.partner.id,
        }
        values.update(overrides)
        return self.Request.create(values)

    def _with_supplier(self, request):
        return self.env["dally.sourcing.supplier"].create({
            "request_id": request.id,
            "partner_id": self.supplier_partner.id,
        })

    def _with_offer(self, request, **overrides):
        supplier = request.supplier_ids[:1] or self._with_supplier(request)
        values = {
            "request_id": request.id,
            "supplier_id": supplier.id,
            "quantity": 10.0,
            "unit_price": 100.0,
        }
        values.update(overrides)
        return self.env["dally.sourcing.offer"].create(values)

    # ─── The transition map itself ────────────────────────────────────

    def test_every_state_appears_in_the_transition_map(self):
        """A state missing from the map would be a dead end nobody declared."""
        declared = {code for code, _label in SOURCING_STATES}
        mapped = set(ALLOWED_TRANSITIONS)
        self.assertEqual(declared, mapped)

    def test_transition_targets_are_all_valid_states(self):
        declared = {code for code, _label in SOURCING_STATES}
        for source, targets in ALLOWED_TRANSITIONS.items():
            for target in targets:
                self.assertIn(target, declared, f"{source} → {target}")

    def test_terminal_states_have_no_transitions(self):
        for state in TERMINAL_STATES:
            self.assertEqual(
                ALLOWED_TRANSITIONS[state], (),
                f"{state} must be terminal; reopening is an explicit action",
            )

    # ─── Valid path ───────────────────────────────────────────────────

    def test_full_happy_path(self):
        request = self._request()
        request.action_qualify()
        self.assertEqual(request.state, "to_qualify")

        request.action_start_research()
        self.assertEqual(request.state, "researching")

        self._with_supplier(request)
        request.action_mark_suppliers_identified()
        self.assertEqual(request.state, "suppliers_identified")

        self._with_offer(request)
        request.action_mark_offers_received()
        self.assertEqual(request.state, "offers_received")

        request.action_start_comparison()
        request.action_prepare_proposal()
        self.assertEqual(request.state, "proposal_ready")

        # A proposal with an amount is required before it can be marked sent.
        self.env["dally.sourcing.proposal"].create({
            "request_id": request.id,
            "product_name": "Test product",
            "quantity": 10.0,
            "selling_unit_price": 130.0,
        })
        request.action_send_proposal()
        self.assertEqual(request.state, "proposal_sent")

        request.action_start_negotiation()
        request.action_accept()
        self.assertEqual(request.state, "accepted")

        request.action_start_purchasing()
        request.action_start_execution()
        request.action_complete()
        self.assertEqual(request.state, "completed")

    def test_state_change_is_logged_and_stamped(self):
        request = self._request()
        before = len(request.message_ids)
        request.action_qualify()
        self.assertGreater(len(request.message_ids), before)
        self.assertTrue(request.state_changed_on)

    def test_repeating_an_action_is_harmless(self):
        """Two operators working the same queue must not produce an error."""
        request = self._request()
        request.action_qualify()
        request.action_qualify()
        self.assertEqual(request.state, "to_qualify")

    # ─── Refused transitions ──────────────────────────────────────────

    def test_new_cannot_jump_to_completed(self):
        request = self._request()
        with self.assertRaises(UserError):
            request.action_complete()

    def test_new_cannot_jump_to_purchasing(self):
        request = self._request()
        with self.assertRaises(UserError):
            request.action_start_purchasing()

    def test_cancelled_cannot_resume_purchasing(self):
        """§10: a cancelled request must not drift back into purchasing."""
        request = self._request()
        request.action_qualify()
        request.action_cancel()
        with self.assertRaises(UserError):
            request.action_start_purchasing()

    def test_completed_is_terminal(self):
        request = self._request()
        for action in ("action_qualify", "action_start_research"):
            getattr(request, action)()
        self._with_supplier(request)
        request.action_mark_suppliers_identified()
        self._with_offer(request)
        request.action_mark_offers_received()
        request.action_start_comparison()
        request.action_prepare_proposal()
        self.env["dally.sourcing.proposal"].create({
            "request_id": request.id, "product_name": "P",
            "quantity": 1.0, "selling_unit_price": 10.0,
        })
        request.action_send_proposal()
        request.action_accept()
        request.action_start_purchasing()
        request.action_start_execution()
        request.action_complete()

        with self.assertRaises(UserError):
            request.action_start_negotiation()

    def test_reopen_is_the_explicit_way_back(self):
        request = self._request()
        request.action_qualify()
        request.action_cancel()

        request.action_reopen()

        self.assertEqual(request.state, "to_qualify")

    def test_reopen_refuses_an_open_request(self):
        request = self._request()
        with self.assertRaises(UserError):
            request.action_reopen()

    def test_unknown_state_is_refused(self):
        request = self._request()
        with self.assertRaises(UserError):
            request._dally_set_state("teleported")

    # ─── Guards on business preconditions ─────────────────────────────

    def test_cannot_mark_suppliers_identified_without_a_supplier(self):
        request = self._request()
        request.action_qualify()
        request.action_start_research()
        with self.assertRaises(UserError):
            request.action_mark_suppliers_identified()

    def test_cannot_mark_offers_received_without_an_offer(self):
        request = self._request()
        request.action_qualify()
        request.action_start_research()
        self._with_supplier(request)
        request.action_mark_suppliers_identified()
        with self.assertRaises(UserError):
            request.action_mark_offers_received()

    def test_cannot_prepare_a_proposal_without_an_offer(self):
        """A proposal built on nothing is a number invented under pressure."""
        request = self._request()
        request.action_qualify()
        request.action_start_research()
        self._with_supplier(request)
        request.action_mark_suppliers_identified()
        self._with_offer(request)
        request.action_mark_offers_received()
        request.action_start_comparison()
        request.offer_ids.unlink()
        with self.assertRaises(UserError):
            request.action_prepare_proposal()

    def test_cannot_send_a_proposal_that_does_not_exist(self):
        """§10: no proposal may be sent without sufficient commercial data."""
        request = self._request()
        request.action_qualify()
        request.action_start_research()
        self._with_supplier(request)
        request.action_mark_suppliers_identified()
        self._with_offer(request)
        request.action_mark_offers_received()
        request.action_start_comparison()
        request.action_prepare_proposal()

        with self.assertRaises(UserError):
            request.action_send_proposal()

    def test_cannot_send_a_proposal_with_no_amount(self):
        request = self._request()
        request.action_qualify()
        request.action_start_research()
        self._with_supplier(request)
        request.action_mark_suppliers_identified()
        self._with_offer(request)
        request.action_mark_offers_received()
        request.action_start_comparison()
        request.action_prepare_proposal()

        self.env["dally.sourcing.proposal"].create({
            "request_id": request.id, "product_name": "P",
            "quantity": 1.0, "selling_unit_price": 0.0,
        })
        with self.assertRaises(UserError):
            request.action_send_proposal()

    # ─── Hold and resume ──────────────────────────────────────────────

    def test_hold_remembers_where_work_stopped(self):
        request = self._request()
        request.action_qualify()
        request.action_start_research()

        request.action_put_on_hold()
        self.assertEqual(request.state, "on_hold")
        self.assertEqual(request.state_before_hold, "researching")

        request.action_resume()
        self.assertEqual(request.state, "researching")
        self.assertFalse(request.state_before_hold)

    def test_cannot_hold_a_new_request(self):
        request = self._request()
        with self.assertRaises(UserError):
            request.action_put_on_hold()

    def test_cannot_resume_a_request_not_on_hold(self):
        request = self._request()
        with self.assertRaises(UserError):
            request.action_resume()

    # ─── Deletion ─────────────────────────────────────────────────────

    def test_in_progress_request_cannot_be_deleted(self):
        request = self._request()
        request.action_qualify()
        request.action_start_research()
        with self.assertRaises(UserError):
            request.unlink()

    def test_request_with_offers_cannot_be_deleted(self):
        request = self._request()
        self._with_offer(request)
        with self.assertRaises(UserError):
            request.unlink()

    def test_new_request_can_be_deleted(self):
        request = self._request()
        request.unlink()
        self.assertFalse(request.exists())
