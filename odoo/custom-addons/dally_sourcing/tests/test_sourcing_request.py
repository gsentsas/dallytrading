# -*- coding: utf-8 -*-
"""Sourcing request: references, idempotency, contacts and CRM."""

import re
import uuid

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestSourcingRequest(TransactionCase):

    REFERENCE_RE = re.compile(r"^DT-SRC-\d{4}-\d{6}$")

    def setUp(self):
        super().setUp()
        self.Request = self.env["dally.sourcing.request"]
        self.Partner = self.env["res.partner"]
        self.Lead = self.env["crm.lead"]

    def _payload(self, **overrides):
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "service_code": "sourcing",
            "customer_name": "Aliou Ndiaye",
            "last_name": "Ndiaye",
            "first_name": "Aliou",
            "company_name": "Ndiaye Distribution",
            "email": "aliou.ndiaye@example.com",
            "phone": "+221 77 123 45 67",
            "product_name": "Groupes électrogènes 10 kVA",
            "product_description": "Pour alimentation de secours de commerces.",
            "specifications": "Insonorisés, démarrage automatique, 230 V.",
            "quantity": 25.0,
            "budget": 30000.0,
            "currency": "EUR",
            "preferred_origin_country": "CN",
            "destination_country": "SN",
            "notes": "Livraison souhaitée avant la saison des pluies.",
            "source_url": "https://dallytrading.com/sourcing",
            "referrer_url": "https://www.google.com/",
            "utm": {"source": "google", "medium": "cpc", "campaign": "sourcing-2026"},
        }
        payload.update(overrides)
        return payload

    # ─── References ───────────────────────────────────────────────────

    def test_reference_format(self):
        request = self.Request.dally_create_from_website(self._payload())
        self.assertRegex(request.reference, self.REFERENCE_RE)

    def test_references_are_unique(self):
        references = {
            self.Request.dally_create_from_website(self._payload()).reference
            for _ in range(10)
        }
        self.assertEqual(len(references), 10)

    def test_reference_is_immutable_in_practice(self):
        """It is readonly and not copied: a duplicate draws its own."""
        request = self.Request.dally_create_from_website(self._payload())
        original = request.reference
        duplicate = request.copy()
        self.assertNotEqual(duplicate.reference, original)
        self.assertRegex(duplicate.reference, self.REFERENCE_RE)
        self.assertEqual(request.reference, original)

    def test_reference_field_is_readonly(self):
        self.assertTrue(self.Request._fields["reference"].readonly)

    # ─── Intake ───────────────────────────────────────────────────────

    def test_creates_request_with_structured_data(self):
        request = self.Request.dally_create_from_website(self._payload())

        self.assertEqual(request.state, "new")
        self.assertEqual(request.product_name, "Groupes électrogènes 10 kVA")
        self.assertAlmostEqual(request.quantity, 25.0)
        self.assertAlmostEqual(request.target_total_budget, 30000.0)
        self.assertEqual(request.currency_id.name, "EUR")
        self.assertEqual(request.preferred_origin_country_id.code, "CN")
        self.assertEqual(request.destination_country_id.code, "SN")
        self.assertEqual(request.contact_name, "Aliou Ndiaye")
        self.assertEqual(request.company_name, "Ndiaye Distribution")
        self.assertEqual(request.source, "Website / Sourcing")

    def test_records_attribution(self):
        request = self.Request.dally_create_from_website(self._payload())
        self.assertEqual(request.utm_source_id.name, "google")
        self.assertEqual(request.utm_medium_id.name, "cpc")
        self.assertEqual(request.utm_campaign_id.name, "sourcing-2026")
        self.assertEqual(request.referrer_url, "https://www.google.com/")

    def test_unknown_currency_falls_back_to_company(self):
        request = self.Request.dally_create_from_website(
            self._payload(currency="ZZZ")
        )
        self.assertEqual(request.currency_id, self.env.company.currency_id)

    def test_unknown_country_is_ignored_not_fatal(self):
        request = self.Request.dally_create_from_website(
            self._payload(preferred_origin_country="ZZ")
        )
        self.assertFalse(request.preferred_origin_country_id)
        self.assertTrue(request.id)

    def test_unknown_service_is_rejected(self):
        with self.assertRaises(UserError):
            self.Request.dally_create_from_website(
                self._payload(service_code="no_such_service")
            )

    def test_request_needs_a_contact_channel(self):
        with self.assertRaises(ValidationError):
            self.Request.dally_create_from_website(
                self._payload(email="", phone="")
            )

    def test_quantity_must_be_positive(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.Request.create({
                "product_name": "Test",
                "quantity": -5.0,
                "contact_email": "a@example.com",
            })
            self.env.flush_all()

    def test_intake_is_logged_in_chatter(self):
        request = self.Request.dally_create_from_website(self._payload())
        bodies = " ".join(request.message_ids.mapped("body"))
        self.assertIn("google", bodies)
        self.assertIn("Website / Sourcing", bodies)

    # ─── Idempotency ──────────────────────────────────────────────────

    def test_same_uuid_returns_the_same_request(self):
        payload = self._payload()
        first = self.Request.dally_create_from_website(payload)
        second = self.Request.dally_create_from_website(payload)

        self.assertEqual(first, second)
        self.assertEqual(
            self.Request.search_count(
                [("request_uuid", "=", payload["request_uuid"])]
            ),
            1,
        )

    def test_replay_does_not_consume_a_reference(self):
        payload = self._payload()
        first = self.Request.dally_create_from_website(payload)
        reference = first.reference
        self.Request.dally_create_from_website(payload)
        self.assertEqual(first.reference, reference)

    def test_replay_of_an_archived_request_is_answered_not_duplicated(self):
        """The bug already found on quote requests, guarded here from the start.

        Without active_test=False in the intake search, the archived record would be
        invisible, create() would hit the UNIQUE constraint on request_uuid, and the
        caller would get a 500 instead of the original reference.
        """
        payload = self._payload()
        request = self.Request.dally_create_from_website(payload)
        request.active = False

        replay = self.Request.dally_create_from_website(payload)

        self.assertEqual(replay, request)
        self.assertEqual(
            self.Request.with_context(active_test=False).search_count(
                [("request_uuid", "=", payload["request_uuid"])]
            ),
            1,
        )

    def test_distinct_uuids_create_distinct_requests(self):
        first = self.Request.dally_create_from_website(self._payload())
        second = self.Request.dally_create_from_website(self._payload())
        self.assertNotEqual(first, second)

    # ─── Contacts ─────────────────────────────────────────────────────

    def test_matches_an_existing_contact_by_email(self):
        partner = self.Partner.create({
            "name": "Aliou Ndiaye", "email": "aliou.ndiaye@example.com",
        })
        request = self.Request.dally_create_from_website(self._payload())
        self.assertEqual(request.customer_id, partner)

    def test_matches_an_existing_contact_by_normalised_phone(self):
        partner = self.Partner.create({
            "name": "Known Customer", "phone": "00221771234567",
        })
        request = self.Request.dally_create_from_website(
            self._payload(email="a-different-address@example.com")
        )
        self.assertEqual(request.customer_id, partner)

    def test_creates_no_contact_on_intake(self):
        before = self.Partner.search_count([])
        self.Request.dally_create_from_website(
            self._payload(email="never-seen@example.com",
                          phone="+221 33 000 11 22",
                          company_name="Never Seen SARL")
        )
        self.assertEqual(self.Partner.search_count([]), before)

    def test_create_customer_action_creates_one(self):
        request = self.Request.dally_create_from_website(
            self._payload(email="fresh@example.com", phone="+221 33 222 11 00",
                          company_name="Fresh Company SARL")
        )
        self.assertFalse(request.customer_id)

        request.action_create_customer()

        self.assertTrue(request.customer_id)
        self.assertEqual(request.customer_id.email, "fresh@example.com")

    def test_create_customer_links_instead_of_duplicating(self):
        """Reuses the dally_crm deduplication helper rather than a second rule."""
        partner = self.Partner.create({
            "name": "Existing", "email": "aliou.ndiaye@example.com",
        })
        request = self.Request.dally_create_from_website(self._payload())
        request.customer_id = False

        before = self.Partner.search_count([])
        request.action_create_customer()

        self.assertEqual(request.customer_id, partner)
        self.assertEqual(self.Partner.search_count([]), before)

    def test_create_customer_is_idempotent(self):
        request = self.Request.dally_create_from_website(self._payload())
        request.action_create_customer()
        customer = request.customer_id
        request.action_create_customer()
        self.assertEqual(request.customer_id, customer)

    # ─── CRM ──────────────────────────────────────────────────────────

    def test_no_crm_opportunity_on_intake(self):
        """Not every raw internet request deserves a pipeline entry (§20)."""
        before = self.Lead.search_count([])
        request = self.Request.dally_create_from_website(self._payload())
        self.assertFalse(request.crm_lead_id)
        self.assertEqual(self.Lead.search_count([]), before)

    def test_create_crm_opportunity(self):
        request = self.Request.dally_create_from_website(self._payload())
        lead = request.action_create_crm_opportunity()

        self.assertTrue(lead)
        self.assertEqual(lead.type, "opportunity")
        self.assertEqual(request.crm_lead_id, lead)
        self.assertEqual(lead.dally_reference, request.reference)
        self.assertIn("Groupes électrogènes", lead.name)

    def test_create_crm_opportunity_is_idempotent(self):
        request = self.Request.dally_create_from_website(self._payload())
        first = request.action_create_crm_opportunity()
        count = self.Lead.search_count([])
        second = request.action_create_crm_opportunity()

        self.assertEqual(first, second)
        self.assertEqual(self.Lead.search_count([]), count)

    def test_opportunity_description_summarises_the_request(self):
        request = self.Request.dally_create_from_website(self._payload())
        lead = request.action_create_crm_opportunity()
        description = lead.description or ""
        self.assertIn(request.reference, description)
        self.assertIn("Groupes électrogènes", description)

    # ─── Dates and overdue ────────────────────────────────────────────

    def test_delivery_before_deadline_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.Request.dally_create_from_website(self._payload(
                requested_deadline="2026-06-01",
                required_delivery_date="2026-05-01",
            ))

    def test_is_overdue_and_is_searchable(self):
        overdue = self.Request.dally_create_from_website(
            self._payload(requested_deadline="2020-01-01")
        )
        on_time = self.Request.dally_create_from_website(
            self._payload(requested_deadline="2999-01-01")
        )
        self.assertTrue(overdue.is_overdue)
        self.assertFalse(on_time.is_overdue)

        found = self.Request.search([("is_overdue", "=", True)])
        self.assertIn(overdue, found)
        self.assertNotIn(on_time, found)

    def test_closed_request_is_not_overdue(self):
        request = self.Request.dally_create_from_website(
            self._payload(requested_deadline="2020-01-01")
        )
        request.action_qualify()
        request.action_cancel()
        self.assertFalse(request.is_overdue)

    # ─── Public payload ───────────────────────────────────────────────

    def test_public_payload_exposes_nothing_internal(self):
        import json
        request = self.Request.dally_create_from_website(self._payload())
        request.internal_notes = "SECRET internal margin note"

        serialised = json.dumps(request._dally_public_payload())

        self.assertNotIn("SECRET", serialised)
        self.assertNotIn("internal", serialised.lower())
        self.assertNotIn('"id"', serialised)
        self.assertNotIn("Ndiaye Distribution", serialised)
        self.assertIn(request.reference, serialised)
