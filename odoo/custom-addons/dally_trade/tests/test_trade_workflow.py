# -*- coding: utf-8 -*-
"""The workflow and the approval gate.

The refusals matter more than the acceptances. A deal that can jump from `draft` to
`closed` is a file closed with no counterparty, no price and no approval behind it —
and nobody notices until someone asks what was actually traded.
"""

from odoo.exceptions import UserError

from .common import TradeCase
from odoo.tests import tagged

from odoo.addons.dally_trade.models.dally_trade_opportunity import (
    ALLOWED_TRANSITIONS,
    HOLDABLE_STATES,
    TERMINAL_STATES,
    TRADE_STATES,
)


@tagged("post_install", "-at_install", "dally")
class TestTradeWorkflow(TradeCase):

    # ─── The transition map itself ────────────────────────────────────

    def test_every_state_has_a_transition_entry(self):
        for key, _label in TRADE_STATES:
            self.assertIn(
                key, ALLOWED_TRANSITIONS,
                f"State '{key}' has no entry in the transition map, so nothing "
                f"constrains what it can become.",
            )

    def test_transitions_only_target_declared_states(self):
        known = {key for key, _label in TRADE_STATES}
        for source, targets in ALLOWED_TRANSITIONS.items():
            for target in targets:
                self.assertIn(target, known, f"{source} → unknown state {target}")

    def test_terminal_states_have_no_transitions(self):
        for state in TERMINAL_STATES:
            self.assertEqual(
                ALLOWED_TRANSITIONS[state], (),
                f"'{state}' is terminal but can still move on its own.",
            )

    def test_there_are_sixteen_states(self):
        self.assertEqual(len(TRADE_STATES), 16)

    # ─── Refusals ─────────────────────────────────────────────────────

    def test_cannot_skip_from_draft_to_contracted(self):
        deal = self._deal()
        with self.assertRaises(UserError):
            deal.action_contract()
        self.assertEqual(deal.state, "draft")

    def test_cannot_price_a_deal_with_no_lines(self):
        deal = self._deal()
        deal.action_qualify()
        deal.action_structure()
        with self.assertRaises(UserError):
            deal.action_start_pricing()

    def test_a_closed_deal_does_not_move(self):
        deal = self._deal()
        self._line(deal)
        self._to_contracted(deal)
        deal.action_start_execution()
        deal.action_start_settlement()
        deal.action_close()

        self.assertEqual(deal.state, "closed")
        with self.assertRaises(UserError):
            deal.action_start_execution()

    def test_reopening_is_explicit(self):
        deal = self._deal()
        self._line(deal)
        self._to_contracted(deal)
        deal.action_start_execution()
        deal.action_start_settlement()
        deal.action_close()

        deal.action_reopen()
        self.assertEqual(deal.state, "negotiating")
        self.assertFalse(deal.actual_close_date)

    # ─── Hold and resume ──────────────────────────────────────────────

    def test_hold_returns_to_where_it_was_paused_from(self):
        deal = self._deal()
        self._line(deal)
        deal.action_qualify()
        deal.action_structure()
        deal.action_start_pricing()

        deal.action_put_on_hold()
        self.assertEqual(deal.state, "on_hold")
        self.assertEqual(deal.state_before_hold, "pricing")

        deal.action_resume()
        self.assertEqual(deal.state, "pricing")
        self.assertFalse(deal.state_before_hold)

    def test_a_draft_cannot_be_put_on_hold(self):
        deal = self._deal()
        self.assertNotIn("draft", HOLDABLE_STATES)
        with self.assertRaises(UserError):
            deal.action_put_on_hold()

    # ─── Required parties, per type ───────────────────────────────────

    def test_a_commission_deal_requires_a_principal(self):
        from odoo.exceptions import ValidationError
        deal = self._deal(
            operation_type="commission", supplier_id=False, customer_id=False,
        )
        deal.action_qualify()
        with self.assertRaises(ValidationError):
            deal.action_structure()

    def test_parties_are_not_required_at_intake(self):
        """A public enquiry cannot know who the supplier will be."""
        deal = self._deal(supplier_id=False, customer_id=False)
        self.assertEqual(deal.state, "draft")
        deal.action_qualify()
        self.assertEqual(deal.state, "qualifying")

    # ─── Approval ─────────────────────────────────────────────────────

    def test_a_negative_margin_requires_approval_without_any_configuration(self):
        """No threshold needed: losing money should never be committed silently."""
        deal = self._deal()
        self._line(deal, purchase_unit_price=20.0, sale_unit_price=14.0)

        self.assertTrue(deal.approval_required)
        self.assertIn("négative", deal.approval_reason)

    def test_no_threshold_is_invented_when_configuration_is_empty(self):
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("dally_trade.approval_revenue_threshold", "")
        parameters.set_param("dally_trade.approval_min_margin_rate", "")

        deal = self._deal()
        self._line(deal)  # healthy margin
        deal.invalidate_recordset()

        self.assertFalse(
            deal.approval_required,
            "An approval was demanded although no threshold is configured.",
        )

    def test_a_configured_revenue_threshold_triggers_approval(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "dally_trade.approval_revenue_threshold", "1000",
        )
        deal = self._deal()
        self._line(deal)  # sale 1400
        deal.invalidate_recordset()

        self.assertTrue(deal.approval_required)
        self.assertIn("seuil", deal.approval_reason)

    def test_a_configured_margin_floor_triggers_approval(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "dally_trade.approval_min_margin_rate", "0.5",
        )
        deal = self._deal()
        self._line(deal)  # margin rate ≈ 0.286
        deal.invalidate_recordset()

        self.assertTrue(deal.approval_required)

    def test_an_unapproved_sensitive_deal_cannot_be_proposed(self):
        deal = self._deal()
        self._line(deal, purchase_unit_price=20.0, sale_unit_price=14.0)
        deal.action_qualify()
        deal.action_structure()
        deal.action_start_pricing()
        deal.action_request_approval()
        # Reach `approved` in the state machine without the approval flag.
        deal.state = "approved"

        with self.assertRaises(UserError):
            deal.action_send_proposal()

    def test_an_unapproved_sensitive_deal_cannot_be_contracted(self):
        deal = self._deal()
        self._line(deal, purchase_unit_price=20.0, sale_unit_price=14.0)
        deal.action_qualify()
        deal.action_structure()
        deal.action_start_pricing()
        deal.state = "proposal_sent"

        with self.assertRaises(UserError):
            deal.action_contract()

    def test_approval_records_who_and_when(self):
        deal = self._deal()
        self._line(deal, purchase_unit_price=20.0, sale_unit_price=14.0)
        deal.action_qualify()
        deal.action_structure()
        deal.action_start_pricing()
        deal.action_request_approval()

        deal.action_approve()

        self.assertEqual(deal.approval_status, "approved")
        self.assertEqual(deal.approved_by_id, self.env.user)
        self.assertTrue(deal.approved_on)
        self.assertEqual(deal.state, "approved")

    def test_a_deal_whose_margin_cannot_be_computed_cannot_be_approved(self):
        """Approving an unknown figure is not approving."""
        deal = self._deal(purchase_currency_id=self.other_currency.id)
        self._line(deal)
        deal.action_qualify()
        deal.action_structure()
        deal.action_start_pricing()
        # Force the approval requirement without a computable margin.
        deal.state = "approval_pending"
        deal.approval_required = True

        with self.assertRaises(UserError):
            deal.action_approve()

    def test_refusing_an_approval_returns_the_deal_to_pricing(self):
        deal = self._deal()
        self._line(deal, purchase_unit_price=20.0, sale_unit_price=14.0)
        deal.action_qualify()
        deal.action_structure()
        deal.action_start_pricing()
        deal.action_request_approval()

        deal.action_refuse_approval()

        self.assertEqual(deal.state, "pricing")
        self.assertEqual(deal.approval_status, "refused")
        self.assertFalse(deal.approved_by_id)
