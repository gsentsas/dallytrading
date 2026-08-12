# -*- coding: utf-8 -*-
"""HTTP tests for POST /api/v1/quotes.

Through the real stack, because that is where an endpoint fails: a model test
cannot catch a wrong status code, a leaked traceback, or a field that slipped into
a response.
"""

import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestQuotesEndpoint(HttpCase):

    ENDPOINT = "/api/v1/quotes"

    def setUp(self):
        super().setUp()
        self.key = self.env["dally.api.key"].create({
            "name": "Quotes test key",
            "scopes": "quotes:write",
            "allowed_ips": "",
        })
        self.raw_key = self.key.key_to_display

    def _post(self, payload, api_key=None, raw_body=None):
        headers = {"Content-Type": "application/json"}
        key = self.raw_key if api_key is None else api_key
        if key:
            headers["X-API-Key"] = key
        body = raw_body if raw_body is not None else json.dumps(payload)
        return self.url_open(self.ENDPOINT, data=body, headers=headers, timeout=30)

    def _payload(self, **overrides):
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "service_code": "freight_sea",
            "first_name": "Awa",
            "last_name": "Diallo",
            "company_name": "Diallo Trading",
            "email": "awa.diallo@example.com",
            "phone": "+221 77 555 44 33",
            "origin_city": "Le Havre",
            "origin_country_code": "FR",
            "destination_city": "Dakar",
            "destination_country_code": "SN",
            "goods_description": "Textile",
            "quantity": "10 cartons",
            "weight_kg": 480,
            "volume_cbm": 2.5,
            "packages_count": 10,
            "message": "Devis groupage.",
            "source_url": "https://dallytrading.com/devis",
            "utm_source": "newsletter",
        }
        payload.update(overrides)
        return payload

    # ─── Permission and scope ─────────────────────────────────────────

    def test_requires_an_api_key(self):
        self.assertEqual(self._post(self._payload(), api_key=False).status_code, 401)

    def test_rejects_an_invalid_key(self):
        self.assertEqual(self._post(self._payload(), api_key="nope").status_code, 401)

    def test_rejects_a_key_without_the_quotes_scope(self):
        other = self.env["dally.api.key"].create({
            "name": "Tracking only", "scopes": "tracking:read", "allowed_ips": "",
        })
        response = self._post(self._payload(), api_key=other.key_to_display)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "insufficient_scope")

    # ─── Validation ───────────────────────────────────────────────────

    def test_rejects_invalid_json(self):
        self.assertEqual(self._post(None, raw_body="{oops").status_code, 400)

    def test_rejects_a_missing_request_uuid(self):
        payload = self._payload()
        del payload["request_uuid"]
        response = self._post(payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "missing_request_uuid")

    def test_rejects_a_non_uuid_request_id(self):
        response = self._post(self._payload(request_uuid="not-a-uuid"))
        self.assertEqual(response.status_code, 422)

    def test_rejects_missing_required_fields(self):
        response = self._post(self._payload(last_name="", service_code=""))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "missing_fields")

    def test_requires_email_or_phone(self):
        response = self._post(self._payload(email="", phone=""))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "no_contact_channel")

    def test_rejects_a_malformed_email(self):
        for bad in ("nope", "a@b", "@example.com", "a b@c.com"):
            with self.subTest(email=bad):
                response = self._post(self._payload(email=bad))
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "invalid_email")

    def test_rejects_an_unknown_service_code(self):
        response = self._post(self._payload(service_code="no_such_service"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unknown_service")

    def test_rejects_an_unpublished_service(self):
        self.env["dally.service.type"].create({
            "name": "Hidden", "code": "hidden_service",
            "category": "other", "published": False,
        })
        response = self._post(self._payload(service_code="hidden_service"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")

    def test_rejects_negative_and_absurd_numbers(self):
        self.assertEqual(self._post(self._payload(weight_kg=-1)).status_code, 422)
        self.assertEqual(
            self._post(self._payload(weight_kg=99_999_999_999)).status_code, 422
        )
        self.assertEqual(
            self._post(self._payload(weight_kg="beaucoup")).status_code, 422
        )

    def test_rejects_an_overlong_field(self):
        response = self._post(self._payload(first_name="x" * 500))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "field_too_long")

    # ─── Service-driven requirements ──────────────────────────────────

    def test_service_requiring_a_route_rejects_a_submission_without_one(self):
        """The form adapts, but the form is not the authority: curl reaches here."""
        response = self._post(self._payload(
            origin_city="", origin_country_code="",
            destination_city="", destination_country_code="",
        ))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "missing_route")

    def test_a_country_code_alone_satisfies_the_route(self):
        response = self._post(self._payload(
            origin_city="", destination_city="",
        ))
        self.assertEqual(response.status_code, 201)

    def test_service_without_a_route_accepts_a_submission_without_one(self):
        response = self._post(self._payload(
            service_code="sourcing",
            origin_city="", origin_country_code="",
            destination_city="", destination_country_code="",
            budget="2000 EUR / tonne",
        ))
        self.assertEqual(response.status_code, 201)

    def test_weight_is_not_required_even_when_the_service_asks_for_it(self):
        # Often unknown at enquiry time; refusing would turn away real business.
        payload = self._payload()
        for key in ("weight_kg", "volume_cbm", "packages_count"):
            payload.pop(key, None)
        self.assertEqual(self._post(payload).status_code, 201)

    # ─── Success ──────────────────────────────────────────────────────

    def test_creates_a_request_and_returns_a_reference(self):
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 201)

        body = response.json()
        self.assertRegex(body["data"]["reference"], r"^DT-\d{4}-\d{6}$")
        self.assertEqual(body["data"]["service"], "freight_sea")
        self.assertEqual(body["data"]["status"], "received")
        self.assertTrue(body["request_id"])

        request = self.env["dally.quote.request"].search(
            [("reference", "=", body["data"]["reference"])]
        )
        self.assertEqual(len(request), 1)
        self.assertEqual(request.origin_city, "Le Havre")
        self.assertAlmostEqual(request.weight_kg, 480.0)
        self.assertTrue(request.lead_id)

    def test_response_exposes_no_internal_field(self):
        body = self._post(self._payload()).json()
        serialised = json.dumps(body)
        self.assertNotIn('"id"', serialised)
        self.assertNotIn("_record", serialised)
        self.assertNotIn("partner_id", serialised)
        self.assertNotIn("internal_notes", serialised)
        self.assertNotIn("lead_id", serialised)
        # Whether an existing contact matched is internal commercial information.
        self.assertNotIn("matched", serialised.lower())

    def test_ignores_unexpected_fields(self):
        response = self._post(self._payload(
            state="won", user_id=1, internal_notes="injected", active=False,
        ))
        self.assertEqual(response.status_code, 201)

        request = self.env["dally.quote.request"].search(
            [("reference", "=", response.json()["data"]["reference"])]
        )
        self.assertEqual(request.state, "new")
        self.assertFalse(request.user_id)
        self.assertTrue(request.active)

    def test_response_is_not_cacheable(self):
        response = self._post(self._payload())
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    # ─── Idempotency: double submission ───────────────────────────────

    def test_double_submission_returns_the_same_reference(self):
        payload = self._payload()

        first = self._post(payload)
        second = self._post(payload)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200, "A replay is not a creation")
        self.assertEqual(
            first.json()["data"]["reference"],
            second.json()["data"]["reference"],
        )
        self.assertEqual(
            self.env["dally.quote.request"].search_count(
                [("request_uuid", "=", payload["request_uuid"])]
            ),
            1,
        )

    def test_double_submission_creates_one_opportunity(self):
        payload = self._payload()
        before = self.env["crm.lead"].search_count([])
        self._post(payload)
        after_first = self.env["crm.lead"].search_count([])
        self._post(payload)
        after_second = self.env["crm.lead"].search_count([])

        self.assertEqual(after_first, before + 1)
        self.assertEqual(after_second, after_first)

    def test_distinct_submissions_create_distinct_requests(self):
        first = self._post(self._payload()).json()
        second = self._post(self._payload()).json()
        self.assertNotEqual(
            first["data"]["reference"], second["data"]["reference"]
        )

    def test_a_rejected_submission_can_be_retried(self):
        payload = self._payload(last_name="")
        self.assertEqual(self._post(payload).status_code, 422)

        payload["last_name"] = "Diallo"
        self.assertEqual(self._post(payload).status_code, 201)

    # ─── Contact handling ─────────────────────────────────────────────

    def test_matches_an_existing_contact(self):
        partner = self.env["res.partner"].create({
            "name": "Awa Diallo", "email": "awa.diallo@example.com",
        })
        response = self._post(self._payload())
        request = self.env["dally.quote.request"].search(
            [("reference", "=", response.json()["data"]["reference"])]
        )
        self.assertEqual(request.partner_id, partner)

    def test_creates_no_contact_for_a_new_person(self):
        before = self.env["res.partner"].search_count([])
        self._post(self._payload(
            email="never-seen@example.com", phone="+221 33 000 11 22",
            company_name="Never Seen Ltd",
        ))
        self.assertEqual(self.env["res.partner"].search_count([]), before)

    def test_creates_no_quotation_and_no_shipment(self):
        orders = self.env["sale.order"].search_count([])
        shipments = self.env["dally.shipment"].search_count([])
        self._post(self._payload())
        self.assertEqual(self.env["sale.order"].search_count([]), orders)
        self.assertEqual(self.env["dally.shipment"].search_count([]), shipments)

    # ─── Logging ──────────────────────────────────────────────────────

    def test_request_is_logged_without_the_api_key(self):
        payload = self._payload()
        payload["api_key"] = "should-be-redacted"
        self._post(payload)

        log = self.env["dally.api.request"].search([
            ("request_uuid", "=", payload["request_uuid"]),
            ("endpoint", "=", self.ENDPOINT),
        ])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.status_code, 201)
        self.assertEqual(log.res_model, "dally.quote.request")
        self.assertNotIn("should-be-redacted", log.payload or "")
        self.assertNotIn(self.raw_key, log.payload or "")

    def test_get_is_not_allowed(self):
        response = self.url_open(self.ENDPOINT, timeout=30)
        self.assertIn(response.status_code, (404, 405))
