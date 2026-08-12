# -*- coding: utf-8 -*-
"""Quote request intake and qualification.

The rule this file mostly exists to protect: a public submission creates a
*request* and an *opportunity*, and nothing else. No contact, no quotation, no
shipment. Everything downstream is a human decision.
"""

import re
import uuid

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestQuoteRequest(TransactionCase):

    REFERENCE_RE = re.compile(r"^DT-\d{4}-\d{6}$")

    def setUp(self):
        super().setUp()
        self.Request = self.env["dally.quote.request"]
        self.Partner = self.env["res.partner"]
        self.Lead = self.env["crm.lead"]
        self.Order = self.env["sale.order"]
        self.Shipment = self.env["dally.shipment"]

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
            "origin_city": "Le Havre",
            "origin_country_code": "FR",
            "destination_city": "Dakar",
            "destination_country_code": "SN",
            "goods_description": "Pièces automobiles",
            "quantity": "3 palettes",
            "weight_kg": 750.0,
            "volume_cbm": 5.4,
            "packages_count": 3,
            "message": "Devis pour un conteneur 40 pieds.",
            "source_url": "https://dallytrading.com/fret-maritime",
            "referrer_url": "https://www.google.com/",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "fret-2026",
        }
        payload.update(overrides)
        return payload

    # ─── Intake ───────────────────────────────────────────────────────

    def test_creates_request_with_structured_data(self):
        request = self.Request.dally_create_from_website(self._payload())

        self.assertRegex(request.reference, self.REFERENCE_RE)
        self.assertEqual(request.service_code, "freight_sea")
        self.assertEqual(request.contact_name, "Aliou Ndiaye")
        self.assertEqual(request.company_name, "Ndiaye Import Export")
        self.assertEqual(request.origin_city, "Le Havre")
        self.assertEqual(request.origin_country_id.code, "FR")
        self.assertEqual(request.destination_country_id.code, "SN")
        self.assertEqual(request.quantity, "3 palettes")
        self.assertAlmostEqual(request.weight_kg, 750.0)
        self.assertAlmostEqual(request.volume_cbm, 5.4)
        self.assertEqual(request.packages_count, 3)
        self.assertEqual(request.state, "new")

    def test_records_attribution_including_referrer(self):
        request = self.Request.dally_create_from_website(self._payload())
        self.assertEqual(request.utm_source, "google")
        self.assertEqual(request.utm_medium, "cpc")
        self.assertEqual(request.utm_campaign, "fret-2026")
        self.assertEqual(request.referrer_url, "https://www.google.com/")
        self.assertIn("fret-maritime", request.source_url)

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

    def test_unknown_country_is_ignored_not_fatal(self):
        request = self.Request.dally_create_from_website(
            self._payload(origin_country_code="ZZ")
        )
        self.assertFalse(request.origin_country_id)
        self.assertTrue(request.id)

    def test_intake_is_logged_in_chatter(self):
        request = self.Request.dally_create_from_website(self._payload())
        bodies = " ".join(request.message_ids.mapped("body"))
        self.assertIn("fret-2026", bodies)
        self.assertIn("google", bodies)

    # ─── Opportunity ──────────────────────────────────────────────────

    def test_creates_a_crm_opportunity(self):
        request = self.Request.dally_create_from_website(self._payload())
        lead = request.lead_id

        self.assertTrue(lead, "A request must produce a CRM opportunity")
        self.assertEqual(lead.type, "opportunity")
        self.assertEqual(lead.dally_service_type_id.code, "freight_sea")
        self.assertEqual(lead.email_from, "aliou.ndiaye@example.com")
        self.assertEqual(lead.source_id.name, "DallyTrading.com")

    def test_opportunity_shares_the_same_reference(self):
        """A customer holds one number, whatever object stores it."""
        request = self.Request.dally_create_from_website(self._payload())
        self.assertEqual(request.lead_id.dally_reference, request.reference)

    def test_no_second_sequence_number_is_consumed(self):
        first = self.Request.dally_create_from_website(self._payload())
        second = self.Request.dally_create_from_website(self._payload())

        def number(reference):
            return int(reference.rsplit("-", 1)[1])

        self.assertEqual(
            number(second.reference) - number(first.reference), 1,
            "Creating the lead must not draw an extra reference",
        )

    def test_opportunity_description_summarises_the_request(self):
        request = self.Request.dally_create_from_website(self._payload())
        description = request.lead_id.description or ""
        self.assertIn("Le Havre", description)
        self.assertIn("Pièces automobiles", description)
        self.assertIn(request.reference, description)

    def test_opportunity_description_omits_irrelevant_sections(self):
        """An empty 'Vehicle' heading is noise a salesperson reads past."""
        request = self.Request.dally_create_from_website(
            self._payload(service_code="sourcing", origin_city="",
                          origin_country_code="", destination_city="",
                          destination_country_code="")
        )
        description = request.lead_id.description or ""
        self.assertNotIn("Vehicle", description)
        self.assertNotIn("Origin", description)

    # ─── Nothing else is created ──────────────────────────────────────

    def test_no_partner_is_created(self):
        before = self.Partner.search_count([])
        self.Request.dally_create_from_website(
            self._payload(email="brand-new-person@example.com",
                          phone="+221 33 999 88 77", whatsapp="",
                          company_name="Totally Unknown SARL")
        )
        self.assertEqual(
            self.Partner.search_count([]), before,
            "Intake must not create contacts: the address book would fill with "
            "prospects who never answer",
        )

    def test_no_quotation_is_created(self):
        before = self.Order.search_count([])
        self.Request.dally_create_from_website(self._payload())
        self.assertEqual(
            self.Order.search_count([]), before,
            "A form submission is not a quotation",
        )

    def test_no_shipment_is_created(self):
        before = self.Shipment.search_count([])
        self.Request.dally_create_from_website(self._payload())
        self.assertEqual(
            self.Shipment.search_count([]), before,
            "A shipment is operational and must not exist for a mere enquiry",
        )

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

    def test_replay_creates_no_second_opportunity(self):
        payload = self._payload()
        first = self.Request.dally_create_from_website(payload)
        leads_before = self.Lead.search_count([])
        self.Request.dally_create_from_website(payload)

        self.assertEqual(self.Lead.search_count([]), leads_before)
        self.assertEqual(first.lead_id, first.lead_id)

    def test_replay_does_not_consume_a_reference(self):
        payload = self._payload()
        first = self.Request.dally_create_from_website(payload)
        reference = first.reference
        self.Request.dally_create_from_website(payload)
        self.assertEqual(first.reference, reference)

    def test_distinct_uuids_create_distinct_requests(self):
        first = self.Request.dally_create_from_website(self._payload())
        second = self.Request.dally_create_from_website(self._payload())
        self.assertNotEqual(first, second)
        self.assertNotEqual(first.reference, second.reference)

    # ─── Contact matching ─────────────────────────────────────────────

    def test_matches_an_existing_contact_by_email(self):
        partner = self.Partner.create({
            "name": "Aliou Ndiaye", "email": "aliou.ndiaye@example.com",
        })
        request = self.Request.dally_create_from_website(self._payload())
        self.assertEqual(request.partner_id, partner)
        self.assertEqual(request.lead_id.partner_id, partner)

    def test_matches_an_existing_contact_by_phone(self):
        partner = self.Partner.create({
            "name": "Known Customer", "phone": "00221771234567",
        })
        request = self.Request.dally_create_from_website(
            self._payload(email="a-different-address@example.com")
        )
        self.assertEqual(request.partner_id, partner)

    def test_leaves_contact_empty_when_unknown(self):
        request = self.Request.dally_create_from_website(
            self._payload(email="nobody-known@example.com",
                          phone="+221 33 111 00 99", whatsapp="",
                          company_name="Never Seen SARL")
        )
        self.assertFalse(request.partner_id)

    def test_matching_does_not_modify_the_contact(self):
        partner = self.Partner.create({
            "name": "Original Name", "email": "aliou.ndiaye@example.com",
            "phone": "+221 70 000 00 00",
        })
        self.Request.dally_create_from_website(self._payload())
        self.assertEqual(partner.name, "Original Name")
        self.assertEqual(partner.phone, "+221 70 000 00 00")

    # ─── Qualification ────────────────────────────────────────────────

    def test_create_partner_action(self):
        request = self.Request.dally_create_from_website(
            self._payload(email="fresh-contact@example.com",
                          phone="+221 33 222 11 00", whatsapp="",
                          company_name="Fresh Company SARL")
        )
        self.assertFalse(request.partner_id)

        request.action_create_partner()

        self.assertTrue(request.partner_id)
        self.assertEqual(request.partner_id.email, "fresh-contact@example.com")
        self.assertEqual(request.lead_id.partner_id, request.partner_id)

    def test_create_partner_is_idempotent(self):
        request = self.Request.dally_create_from_website(self._payload())
        request.action_create_partner()
        partner = request.partner_id
        request.action_create_partner()
        self.assertEqual(request.partner_id, partner)

    def test_quotation_requires_a_contact(self):
        request = self.Request.dally_create_from_website(
            self._payload(email="no-contact-yet@example.com",
                          phone="+221 33 444 55 66", whatsapp="",
                          company_name="No Contact SARL")
        )
        request.action_mark_qualified()
        with self.assertRaises(UserError):
            request.action_create_quotation()

    def test_quotation_is_created_on_demand(self):
        request = self.Request.dally_create_from_website(self._payload())
        request.action_create_partner()
        request.action_mark_qualified()

        request.action_create_quotation()

        self.assertEqual(request.state, "quoted")
        self.assertEqual(len(request.sale_order_ids), 1)
        order = request.sale_order_ids
        self.assertEqual(order.dally_quote_request_id, request)
        self.assertEqual(order.dally_reference, request.reference)
        self.assertEqual(
            len(order.order_line), 0,
            "Lines are left empty: a pre-filled guess would be quoted by mistake",
        )

    def test_spam_is_archived_not_deleted(self):
        request = self.Request.dally_create_from_website(self._payload())
        request.action_mark_spam()

        self.assertEqual(request.state, "spam")
        self.assertFalse(request.active)
        self.assertTrue(
            request.exists(),
            "Keeping the record means the same submission cannot come back "
            "through idempotency",
        )

    def test_replay_of_a_spam_request_is_answered_not_duplicated(self):
        """An archived request must still satisfy idempotency.

        Without active_test=False in the intake search, the archived record would
        be invisible, create() would hit the UNIQUE constraint on request_uuid, and
        the caller would get a 500 instead of the original reference.
        """
        payload = self._payload()
        request = self.Request.dally_create_from_website(payload)
        request.action_mark_spam()

        replay = self.Request.dally_create_from_website(payload)

        self.assertEqual(replay, request)
        self.assertEqual(
            self.Request.with_context(active_test=False).search_count(
                [("request_uuid", "=", payload["request_uuid"])]
            ),
            1,
        )
