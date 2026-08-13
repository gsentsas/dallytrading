# -*- coding: utf-8 -*-
"""The confidentiality boundary, asserted rather than assumed.

Every test here answers the same question from a different angle: can a user who
should not see a purchase price, a cost or a margin get at one anyway — through a
field, a related model, a search, or the API identity?

The ORM-level assertions matter most. A field hidden in a view is still in the query
result; a field with ``groups=`` the user does not hold is not loaded at all.
"""

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import TradeCase

from odoo.addons.dally_trade.models.dally_trade_opportunity import INTERNAL_GROUPS


@tagged("post_install", "-at_install", "dally")
class TestTradeSecurity(TradeCase):

    def setUp(self):
        super().setUp()
        self.trade_user = self.env["res.users"].create({
            "name": "Trade Operator",
            "login": "trade.operator@dallytrading.test",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("dally_trade.group_dally_trade_user").id,
            ])],
        })
        self.trade_manager = self.env["res.users"].create({
            "name": "Trade Manager",
            "login": "trade.manager@dallytrading.test",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("dally_trade.group_dally_trade_manager").id,
            ])],
        })
        self.api_user = self.env.ref("dally_trade.user_dally_api_trade")

    # ─── Field-level restriction ──────────────────────────────────────

    #: The fields that must never load for a trade user.
    INTERNAL_FIELDS = (
        "purchase_subtotal", "purchase_currency_id", "purchase_incoterm_id",
        "gross_margin", "net_margin", "margin_rate", "revenue_analysis",
        "cost_total_analysis", "commission_total_analysis", "supplier_id",
        "negotiation_notes", "approval_status", "approval_reason",
        "analysis_currency_id", "conversion_currency_id", "margin_computable",
    )

    def test_internal_fields_declare_the_same_group_string(self):
        """One boundary, not eleven that can drift apart."""
        model = self.env["dally.trade.opportunity"]
        drifted = []
        for name in self.INTERNAL_FIELDS:
            groups = model._fields[name].groups or ""
            if INTERNAL_GROUPS not in groups:
                drifted.append(f"{name}: {groups!r}")
        self.assertFalse(
            drifted,
            "These fields no longer carry the shared internal group string, so the "
            "confidentiality boundary has drifted: " + ", ".join(drifted),
        )

    def test_a_trade_user_cannot_read_the_margin(self):
        deal = self._deal()
        self._line(deal)

        readable = self.env["dally.trade.opportunity"].with_user(
            self.trade_user,
        ).browse(deal.id).read(["name", "state"])[0]

        for name in ("net_margin", "gross_margin", "purchase_subtotal"):
            self.assertNotIn(name, readable)

    def test_reading_a_restricted_field_explicitly_is_refused(self):
        deal = self._deal()
        self._line(deal)

        with self.assertRaises(AccessError):
            self.env["dally.trade.opportunity"].with_user(
                self.trade_user,
            ).browse(deal.id).read(["net_margin"])

    def test_a_trade_manager_does_see_the_margin(self):
        deal = self._deal()
        self._line(deal)

        readable = self.env["dally.trade.opportunity"].with_user(
            self.trade_manager,
        ).browse(deal.id).read(["net_margin", "purchase_subtotal"])[0]

        self.assertEqual(readable["net_margin"], 400.0)

    def test_a_trade_user_still_works_the_deal(self):
        """Restriction must not make the module unusable for its main audience."""
        deal = self.env["dally.trade.opportunity"].with_user(self.trade_user).create({
            "name": "Deal by an operator",
            "operation_type": "purchase_resale",
            "customer_id": self.customer.id,
        })
        deal.action_qualify()
        self.assertEqual(deal.state, "qualifying")

    # ─── Model-level restriction ──────────────────────────────────────

    def test_a_trade_user_cannot_reach_costs_at_all(self):
        deal = self._deal()
        self.env["dally.trade.cost"].create({
            "opportunity_id": deal.id,
            "category": "freight",
            "name": "Fret",
            "amount": 100.0,
            "currency_id": self.company_currency.id,
        })

        with self.assertRaises(AccessError):
            self.env["dally.trade.cost"].with_user(self.trade_user).search([])

    def test_a_trade_user_cannot_reach_commissions_at_all(self):
        with self.assertRaises(AccessError):
            self.env["dally.trade.commission"].with_user(self.trade_user).search([])

    def test_a_readonly_user_cannot_reach_costs(self):
        readonly = self.env["res.users"].create({
            "name": "Readonly",
            "login": "trade.readonly@dallytrading.test",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("dally_core.group_dally_readonly").id,
            ])],
        })
        with self.assertRaises(AccessError):
            self.env["dally.trade.cost"].with_user(readonly).search([])

    # ─── The API identity ─────────────────────────────────────────────

    def test_the_api_user_is_in_no_commercial_group(self):
        """ADR-011 applied to trade: a shared identity would widen the boundary."""
        for group in (
            "dally_core.group_dally_commercial",
            "dally_core.group_dally_readonly",
            "dally_core.group_dally_finance",
            "dally_core.group_dally_sourcing",
            "dally_trade.group_dally_trade_user",
            "dally_trade.group_dally_trade_manager",
        ):
            self.assertFalse(
                self.api_user.has_group(group),
                f"The trade API user holds {group}, which widens what a leaked key "
                f"can read.",
            )

    def test_the_api_user_sees_only_the_records_it_created(self):
        staff_deal = self._deal()
        api_deal = self.env["dally.trade.opportunity"].with_user(self.api_user).create({
            "name": "Enquiry from the website",
            "operation_type": "purchase_resale",
        })

        visible = self.env["dally.trade.opportunity"].with_user(
            self.api_user,
        ).search([])

        self.assertIn(api_deal, visible)
        self.assertNotIn(
            staff_deal, visible,
            "A leaked API key could enumerate deals created by staff.",
        )

    def test_the_api_user_cannot_read_internal_notes(self):
        deal = self.env["dally.trade.opportunity"].with_user(self.api_user).create({
            "name": "Enquiry",
            "operation_type": "purchase_resale",
        })
        with self.assertRaises(AccessError):
            deal.read(["internal_notes"])

    def test_the_api_user_cannot_reach_costs(self):
        with self.assertRaises(AccessError):
            self.env["dally.trade.cost"].with_user(self.api_user).search([])

    # ─── The controller's contract ────────────────────────────────────

    def test_the_controller_mirrors_the_module_operation_types(self):
        """dally_api duplicates the tuple rather than importing it; this keeps them equal."""
        from odoo.addons.dally_api.controllers.trade import (
            ACCEPTED_OPERATION_TYPES,
        )
        from odoo.addons.dally_trade.models.dally_trade_rules import (
            OPERATION_TYPE_KEYS,
        )
        self.assertEqual(
            set(ACCEPTED_OPERATION_TYPES), set(OPERATION_TYPE_KEYS),
            "The API's accepted types drifted from the module's. An enquiry would be "
            "refused for a type the system supports, or filed under one it does not.",
        )

    def test_the_controller_refuses_every_field_the_model_calls_forbidden(self):
        from odoo.addons.dally_api.controllers.trade import FORBIDDEN_FIELDS
        from odoo.addons.dally_trade.models.dally_trade_opportunity import (
            DallyTradeOpportunity,
        )
        for name in (
            "internal_cost", "purchase_margin", "internal_margin", "supplier_score",
            "internal_commission", "negotiation_notes", "approval_status",
        ):
            self.assertIn(
                name, FORBIDDEN_FIELDS,
                f"The endpoint would silently accept '{name}'.",
            )
            self.assertIn(name, DallyTradeOpportunity.FORBIDDEN_PUBLIC_FIELDS)

    def test_the_public_contract_writes_no_internal_field(self):
        """Every key the intake maps must be one a public caller may influence."""
        from odoo.addons.dally_trade.models.dally_trade_opportunity import (
            DallyTradeOpportunity,
        )
        prepared = self.env["dally.trade.opportunity"]._dally_prepare_values({
            "subject": "Test", "email": "x@example.com",
        })
        forbidden = {
            "state", "responsible_id", "approval_status", "approved_by_id",
            "negotiation_notes", "internal_notes", "supplier_id",
            "purchase_currency_id", "gross_margin", "net_margin",
        }
        self.assertFalse(
            forbidden & set(prepared),
            "Public intake maps onto an internal field: "
            + ", ".join(sorted(forbidden & set(prepared))),
        )
        self.assertTrue(DallyTradeOpportunity.PUBLIC_PAYLOAD_KEYS)
