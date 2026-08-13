# -*- coding: utf-8 -*-
"""The model itself: reference, intake, idempotency, and the public projection."""

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TradeCase

from odoo.addons.dally_trade.models.dally_trade_opportunity import (
    DallyTradeOpportunity,
)
from odoo.addons.dally_trade.models.dally_trade_rules import (
    OPERATION_TYPES,
    OPERATION_TYPE_KEYS,
    operation_rules,
)


@tagged("post_install", "-at_install", "dally")
class TestTradeOpportunity(TradeCase):

    # ─── Reference ────────────────────────────────────────────────────

    def test_reference_uses_the_shared_engine(self):
        deal = self._deal()
        self.assertTrue(deal.reference.startswith("DT-TRD-"))
        self.assertRegex(deal.reference, r"^DT-TRD-\d{4}-\d{6}$")

    def test_references_are_unique(self):
        first, second = self._deal(), self._deal()
        self.assertNotEqual(first.reference, second.reference)

    def test_a_copy_gets_its_own_reference(self):
        deal = self._deal()
        copy = deal.copy()
        self.assertNotEqual(copy.reference, deal.reference)

    # ─── Operation types ──────────────────────────────────────────────

    def test_every_type_has_a_complete_rule_set(self):
        expected = {
            "revenue_model", "requires_supplier", "requires_customer",
            "requires_principal", "has_purchase_side", "has_sale_side",
            "allows_purchase_order", "allows_sale_order", "allows_commission",
            "description",
        }
        for key in OPERATION_TYPE_KEYS:
            self.assertEqual(
                set(operation_rules(key)), expected,
                f"The rule set for '{key}' is incomplete, so some behaviour falls "
                f"through to whatever the calling code happens to do.",
            )

    def test_there_are_six_types_with_french_labels(self):
        self.assertEqual(len(OPERATION_TYPES), 6)
        labels = dict(OPERATION_TYPES)
        self.assertEqual(labels["purchase_resale"], "Achat-revente")
        self.assertEqual(labels["brokerage"], "Courtage")
        self.assertEqual(labels["commercial_representation"],
                         "Représentation commerciale")

    def test_an_unknown_type_raises_rather_than_defaulting(self):
        """A silent fallback would make an unknown type behave as achat-revente."""
        with self.assertRaises(KeyError):
            operation_rules("franchise")

    def test_types_that_do_not_buy_cannot_raise_a_purchase_order(self):
        for key in ("brokerage", "commission", "commercial_representation"):
            self.assertFalse(
                operation_rules(key)["allows_purchase_order"],
                f"'{key}' would be allowed to record a purchase it never made.",
            )

    # ─── Text limits ──────────────────────────────────────────────────

    def test_free_text_is_bounded(self):
        deal = self._deal()
        with self.assertRaises(ValidationError):
            deal.description = "x" * 10_001

    # ─── Public intake ────────────────────────────────────────────────

    def _payload(self, **overrides):
        values = {
            "request_uuid": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "subject": "Import de riz parfumé",
            "operation_type": "import_export",
            "contact_name": "Aminata Diallo",
            "email": "aminata@example.com",
            "phone": "+221771234567",
        }
        values.update(overrides)
        return values

    def test_intake_creates_a_deal_with_no_internal_state(self):
        deal = self.Deal.dally_create_from_website(self._payload())

        self.assertEqual(deal.state, "draft")
        self.assertFalse(deal.responsible_id, "Intake assigned an owner by itself.")
        self.assertFalse(deal.customer_id, "Intake created a contact by itself.")
        self.assertFalse(deal.crm_lead_id, "Intake created a pipeline entry.")
        self.assertFalse(deal.supplier_id)
        self.assertEqual(deal.operation_type, "import_export")
        self.assertEqual(deal.name, "Import de riz parfumé")

    def test_intake_defaults_the_type_rather_than_leaving_it_empty(self):
        deal = self.Deal.dally_create_from_website(
            self._payload(operation_type=None),
        )
        self.assertEqual(deal.operation_type, "purchase_resale")

    def test_intake_is_idempotent_on_request_uuid(self):
        payload = self._payload()
        first = self.Deal.dally_create_from_website(payload)
        second = self.Deal.dally_create_from_website(payload)

        self.assertEqual(first, second)
        self.assertEqual(
            self.Deal.with_context(active_test=False).search_count([
                ("request_uuid", "=", payload["request_uuid"]),
            ]),
            1,
        )

    def test_idempotency_survives_archiving(self):
        """A submission archived as spam and then replayed must not hit the constraint.

        Without `active_test=False` the search misses the archived record, `create`
        runs, and the unique index surfaces as a 500 rather than a replay.
        """
        payload = self._payload()
        first = self.Deal.dally_create_from_website(payload)
        first.active = False

        second = self.Deal.dally_create_from_website(payload)

        self.assertEqual(first, second)

    def test_intake_does_not_invent_a_country(self):
        deal = self.Deal.dally_create_from_website(self._payload())
        self.assertFalse(deal.contact_country_id)
        self.assertFalse(deal.origin_country_id)
        self.assertFalse(deal.destination_country_id)

    def test_intake_resolves_a_country_code_when_given(self):
        senegal = self.env["res.country"].search([("code", "=", "SN")], limit=1)
        if not senegal:
            self.skipTest("res.country data not loaded")
        deal = self.Deal.dally_create_from_website(
            self._payload(destination_country="sn"),
        )
        self.assertEqual(deal.destination_country_id, senegal)

    def test_intake_falls_back_to_a_subject_rather_than_failing(self):
        deal = self.Deal.dally_create_from_website(self._payload(subject=""))
        self.assertTrue(deal.name)

    # ─── Public payload ───────────────────────────────────────────────

    def test_public_payload_matches_the_allowlist_exactly(self):
        deal = self._deal()
        payload = deal._dally_public_payload()

        self.assertEqual(
            set(payload), set(DallyTradeOpportunity.PUBLIC_PAYLOAD_KEYS),
            "The payload drifted from the allowlist that defines the contract.",
        )

    def test_public_payload_contains_no_internal_field(self):
        deal = self._deal()
        self._line(deal)
        self.env["dally.trade.cost"].create({
            "opportunity_id": deal.id,
            "category": "freight",
            "name": "Fret",
            "amount": 100.0,
            "currency_id": self.company_currency.id,
        })

        payload = deal._dally_public_payload()
        serialised = repr(payload).lower()

        for forbidden in DallyTradeOpportunity.FORBIDDEN_PUBLIC_FIELDS:
            self.assertNotIn(
                forbidden.lower(), serialised,
                f"'{forbidden}' reached a public payload.",
            )

    def test_public_payload_exposes_no_database_id(self):
        deal = self._deal()
        payload = deal._dally_public_payload()

        self.assertNotIn("id", payload)
        for key, value in payload.items():
            self.assertNotIsInstance(
                value, int,
                f"'{key}' carries a raw integer, which is how ids leak.",
            )

    def test_public_payload_does_not_name_the_counterparty(self):
        deal = self._deal()
        payload = deal._dally_public_payload()
        serialised = repr(payload)

        self.assertNotIn(self.supplier.name, serialised)
        self.assertNotIn(self.customer.name, serialised)

    # ─── Links stay optional ──────────────────────────────────────────

    def test_a_deal_needs_no_sourcing_request(self):
        deal = self._deal()
        self.assertFalse(deal.sourcing_request_id)
        self._line(deal)
        self._to_contracted(deal)
        self.assertEqual(deal.state, "contracted")

    def test_a_deal_needs_no_crm_lead(self):
        deal = self._deal()
        self.assertFalse(deal.crm_lead_id)

    def test_crm_opportunity_is_created_once_on_request(self):
        deal = self._deal()
        deal.action_create_crm_opportunity()
        first = deal.crm_lead_id
        self.assertTrue(first)

        deal.action_create_crm_opportunity()
        self.assertEqual(deal.crm_lead_id, first)

    def test_creating_the_customer_reuses_the_anti_duplicate(self):
        deal = self.Deal.dally_create_from_website(self._payload(
            email=self.customer.email,
        ))
        deal.action_create_customer()

        self.assertEqual(
            deal.customer_id, self.customer,
            "A duplicate contact was created for an email already on file.",
        )
