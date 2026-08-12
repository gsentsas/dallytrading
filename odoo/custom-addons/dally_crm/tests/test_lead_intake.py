# -*- coding: utf-8 -*-
import re
import uuid

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestLeadIntake(TransactionCase):
    """Covers the validation criteria of §89 and the idempotency rule of §41."""

    REFERENCE_RE = re.compile(r"^DT-\d{4}-\d{6}$")

    def setUp(self):
        super().setUp()
        self.Lead = self.env["crm.lead"]
        self.Partner = self.env["res.partner"]

    def _payload(self, **overrides):
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "service_code": "freight_sea",
            "first_name": "Aliou",
            "last_name": "Ndiaye",
            "company_name": "Ndiaye Import Export",
            "email": "aliou.ndiaye@example.com",
            "phone": "+221 77 123 45 67",
            "whatsapp": "+221 77 123 45 67",
            "city": "Dakar",
            "country_code": "SN",
            "message": "I would like a quote for a 40ft container from Le Havre.",
            "source_url": "https://dallytrading.com/fret-maritime",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "fret-2026",
        }
        payload.update(overrides)
        return payload

    # ─── §89 : a website request becomes a complete lead ──────────────

    def test_creates_lead_with_all_expected_data(self):
        lead = self.Lead.dally_create_from_website(self._payload())

        self.assertTrue(lead.id)
        self.assertRegex(lead.dally_reference, self.REFERENCE_RE)
        self.assertEqual(lead.dally_service_type_id.code, "freight_sea")
        self.assertEqual(lead.dally_service_category, "freight")
        self.assertEqual(lead.contact_name, "Aliou Ndiaye")
        self.assertEqual(lead.partner_name, "Ndiaye Import Export")
        self.assertEqual(lead.email_from, "aliou.ndiaye@example.com")
        self.assertEqual(lead.phone, "+221 77 123 45 67")
        self.assertEqual(lead.dally_whatsapp, "+221 77 123 45 67")
        self.assertEqual(lead.city, "Dakar")
        self.assertEqual(lead.country_id.code, "SN")
        self.assertIn("40ft container", lead.description)
        self.assertEqual(lead.type, "lead")

    def test_records_attribution(self):
        lead = self.Lead.dally_create_from_website(self._payload())
        self.assertEqual(lead.dally_source_url, "https://dallytrading.com/fret-maritime")
        self.assertEqual(lead.dally_utm_source, "google")
        self.assertEqual(lead.dally_utm_medium, "cpc")
        self.assertEqual(lead.dally_utm_campaign, "fret-2026")
        self.assertEqual(lead.source_id.name, "DallyTrading.com")
        self.assertEqual(lead.medium_id.name, "Website Form")

    def test_subject_identifies_the_request(self):
        """The subject is what shows in the pipeline kanban."""
        lead = self.Lead.dally_create_from_website(self._payload())
        self.assertIn("Sea Freight", lead.name)
        self.assertIn("Ndiaye Import Export", lead.name)

    def test_subject_falls_back_to_contact_when_no_company(self):
        lead = self.Lead.dally_create_from_website(
            self._payload(company_name="")
        )
        self.assertIn("Aliou Ndiaye", lead.name)

    def test_intake_is_logged_in_chatter(self):
        lead = self.Lead.dally_create_from_website(self._payload())
        bodies = " ".join(lead.message_ids.mapped("body"))
        self.assertIn(lead.dally_reference, bodies)
        self.assertIn("fret-2026", bodies)

    # ─── §41 : idempotency ────────────────────────────────────────────

    def test_same_request_uuid_returns_the_same_lead(self):
        """A double-click must not produce two leads."""
        payload = self._payload()
        first = self.Lead.dally_create_from_website(payload)
        second = self.Lead.dally_create_from_website(payload)

        self.assertEqual(first, second)
        self.assertEqual(
            self.Lead.search_count([("dally_request_uuid", "=", payload["request_uuid"])]),
            1,
        )

    def test_different_uuids_create_distinct_leads(self):
        first = self.Lead.dally_create_from_website(self._payload())
        second = self.Lead.dally_create_from_website(self._payload())
        self.assertNotEqual(first, second)
        self.assertNotEqual(first.dally_reference, second.dally_reference)

    def test_reference_is_not_consumed_by_a_replay(self):
        """A retry must not burn a reference number."""
        payload = self._payload()
        first = self.Lead.dally_create_from_website(payload)
        reference = first.dally_reference
        self.Lead.dally_create_from_website(payload)
        self.assertEqual(first.dally_reference, reference)

    # ─── §28 : deduplication on intake ────────────────────────────────

    def test_links_to_existing_partner_by_email(self):
        partner = self.Partner.create({
            "name": "Aliou Ndiaye",
            "email": "aliou.ndiaye@example.com",
        })
        lead = self.Lead.dally_create_from_website(self._payload())
        self.assertEqual(lead.partner_id, partner)

    def test_links_to_existing_partner_by_phone(self):
        partner = self.Partner.create({
            "name": "Known Customer",
            "phone": "00221771234567",
        })
        lead = self.Lead.dally_create_from_website(
            self._payload(email="a-new-address@example.com")
        )
        self.assertEqual(lead.partner_id, partner)

    def test_leaves_partner_empty_when_unknown(self):
        """No partner is invented: the salesperson qualifies the lead first."""
        lead = self.Lead.dally_create_from_website(
            self._payload(
                email="brand-new@example.com",
                phone="+221 33 111 00 99",
                whatsapp="",
                company_name="Totally New Company SARL",
            )
        )
        self.assertFalse(lead.partner_id)

    def test_does_not_create_a_partner(self):
        before = self.Partner.search_count([])
        self.Lead.dally_create_from_website(
            self._payload(email="another-new@example.com", phone="+221 33 222 00 88",
                          whatsapp="", company_name="Another New One")
        )
        self.assertEqual(
            self.Partner.search_count([]), before,
            "Intake must not create res.partner records (§28)",
        )

    # ─── Robustness ───────────────────────────────────────────────────

    def test_unknown_service_code_is_rejected(self):
        with self.assertRaises(UserError):
            self.Lead.dally_create_from_website(
                self._payload(service_code="not_a_service")
            )

    def test_unknown_country_code_is_ignored_not_fatal(self):
        """A bad country must not lose the whole request."""
        lead = self.Lead.dally_create_from_website(
            self._payload(country_code="ZZ")
        )
        self.assertFalse(lead.country_id)
        self.assertTrue(lead.id)

    def test_overlong_message_is_truncated(self):
        lead = self.Lead.dally_create_from_website(
            self._payload(message="x" * 50000)
        )
        self.assertLessEqual(len(lead.description), 20000)

    def test_manual_lead_gets_no_reference(self):
        """The reference series is reserved for requests from our channels."""
        lead = self.Lead.create({"name": "Internal prospecting"})
        self.assertFalse(lead.dally_reference)

    def test_manual_lead_can_be_given_a_reference(self):
        lead = self.Lead.create({"name": "Legacy lead"})
        lead.action_dally_assign_reference()
        self.assertRegex(lead.dally_reference, self.REFERENCE_RE)
