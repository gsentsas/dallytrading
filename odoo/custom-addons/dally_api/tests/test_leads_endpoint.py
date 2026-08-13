# -*- coding: utf-8 -*-
"""End-to-end HTTP tests for POST /api/v1/leads.

These go through the real HTTP stack — routing, authentication, JSON handling
and error mapping — because that is where an endpoint actually fails. Model-level
tests cannot catch a wrong status code or a leaked traceback.
"""

import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestLeadsEndpoint(HttpCase):

    ENDPOINT = "/api/v1/leads"

    def setUp(self):
        super().setUp()
        self.key = self.env["dally.api.key"].create({
            "name": "Test Suite Key",
            "scopes": "leads:write",
            "allowed_ips": "",  # the test client's address varies
        })
        self.raw_key = self.key.key_to_display

    # ─── Helpers ─────────────────────────────────────────────────────

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
            "service_code": "freight_air",
            "first_name": "Awa",
            "last_name": "Diallo",
            "company_name": "Diallo Trading",
            "email": "awa.diallo@example.com",
            "phone": "+221 77 555 44 33",
            "city": "Dakar",
            "country_code": "SN",
            "message": "Quote request for 200 kg of spare parts.",
            "source_url": "https://dallytrading.com/fret-aerien",
            "utm_source": "newsletter",
        }
        payload.update(overrides)
        return payload

    # ─── Authentication ──────────────────────────────────────────────

    def test_rejects_missing_api_key(self):
        response = self._post(self._payload(), api_key=False)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "missing_api_key")

    def test_rejects_invalid_api_key(self):
        response = self._post(self._payload(), api_key="totally-wrong-key")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_api_key")

    def test_error_does_not_reveal_why_key_failed(self):
        """Unknown, revoked and expired keys must be indistinguishable."""
        revoked = self.env["dally.api.key"].create({
            "name": "Revoked", "scopes": "leads:write", "allowed_ips": "",
        })
        raw = revoked.key_to_display
        revoked.active = False

        unknown = self._post(self._payload(), api_key="unknown-key-value").json()
        revoked_response = self._post(self._payload(), api_key=raw).json()
        self.assertEqual(unknown["error"], revoked_response["error"])

    def test_rejects_insufficient_scope(self):
        limited = self.env["dally.api.key"].create({
            "name": "Read Only", "scopes": "tracking:read", "allowed_ips": "",
        })
        response = self._post(self._payload(), api_key=limited.key_to_display)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "insufficient_scope")

    # ─── Body validation ─────────────────────────────────────────────

    def test_rejects_invalid_json(self):
        response = self._post(None, raw_body="{not valid json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_json")

    def test_rejects_empty_body(self):
        response = self._post(None, raw_body=" ")
        self.assertEqual(response.status_code, 400)

    def test_rejects_json_array(self):
        response = self._post(None, raw_body="[1, 2, 3]")
        self.assertEqual(response.status_code, 400)

    def test_rejects_missing_request_uuid(self):
        payload = self._payload()
        del payload["request_uuid"]
        response = self._post(payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "missing_request_uuid")

    def test_rejects_non_uuid_request_id(self):
        """Arbitrary strings would let a client pin one value and block itself."""
        response = self._post(self._payload(request_uuid="not-a-uuid"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request_uuid")

    def test_rejects_missing_required_fields(self):
        response = self._post(self._payload(last_name="", service_code=""))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "missing_fields")

    def test_rejects_whitespace_only_name(self):
        response = self._post(self._payload(last_name="   "))
        self.assertEqual(response.status_code, 422)

    def test_requires_email_or_phone(self):
        response = self._post(self._payload(email="", phone=""))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "no_contact_channel")

    def test_accepts_phone_without_email(self):
        response = self._post(self._payload(email=""))
        self.assertEqual(response.status_code, 201)

    def test_rejects_malformed_email(self):
        for bad in ("not-an-email", "a@b", "@example.com", "a@@b.com", "a b@c.com"):
            with self.subTest(email=bad):
                response = self._post(self._payload(email=bad))
                self.assertEqual(response.status_code, 422, bad)
                self.assertEqual(response.json()["error"]["code"], "invalid_email")

    def test_rejects_unknown_service_code(self):
        response = self._post(self._payload(service_code="no_such_service"))
        self.assertEqual(response.status_code, 422)

    def test_rejects_overlong_field(self):
        response = self._post(self._payload(first_name="x" * 500))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "field_too_long")

    def test_ignores_unexpected_fields(self):
        """An allowlist means a caller cannot set arbitrary lead fields."""
        response = self._post(self._payload(
            user_id=1, stage_id=1, expected_revenue=999999, probability=100,
        ))
        self.assertEqual(response.status_code, 201)
        reference = response.json()["data"]["reference"]
        lead = self.env["crm.lead"].search([("dally_reference", "=", reference)])
        self.assertEqual(lead.expected_revenue, 0)

    # ─── Success ─────────────────────────────────────────────────────

    def test_creates_lead_and_returns_reference(self):
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 201)

        body = response.json()
        self.assertTrue(body["success"])
        self.assertRegex(body["data"]["reference"], r"^DT-\d{4}-\d{6}$")
        self.assertEqual(body["data"]["service"], "freight_air")
        self.assertEqual(body["data"]["status"], "received")
        self.assertTrue(body["request_id"], "A correlation id must be returned")

        lead = self.env["crm.lead"].search(
            [("dally_reference", "=", body["data"]["reference"])]
        )
        self.assertEqual(len(lead), 1)
        self.assertEqual(lead.contact_name, "Awa Diallo")

    def test_response_never_exposes_database_id(self):
        """A sequential id must not become an authorisation handle (§42)."""
        body = self._post(self._payload()).json()
        serialised = json.dumps(body)
        self.assertNotIn('"id"', serialised)
        self.assertNotIn("_record", serialised)

    def test_response_is_not_cacheable(self):
        response = self._post(self._payload())
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_request_is_logged(self):
        payload = self._payload()
        self._post(payload)
        log = self.env["dally.api.request"].search([
            ("request_uuid", "=", payload["request_uuid"]),
            ("endpoint", "=", self.ENDPOINT),
        ])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.status_code, 201)
        self.assertEqual(log.res_model, "crm.lead")
        self.assertTrue(log.res_id)

    def test_log_never_contains_the_api_key(self):
        payload = self._payload()
        payload["api_key"] = "should-be-redacted"
        self._post(payload)
        log = self.env["dally.api.request"].search([
            ("request_uuid", "=", payload["request_uuid"])
        ])
        self.assertNotIn("should-be-redacted", log.payload or "")
        self.assertNotIn(self.raw_key, log.payload or "")

    # ─── Idempotency (§41) ───────────────────────────────────────────

    def test_replay_returns_same_reference_without_creating_a_second_lead(self):
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
            self.env["crm.lead"].search_count(
                [("dally_request_uuid", "=", payload["request_uuid"])]
            ),
            1,
            "A retry must never create a second lead",
        )

    def test_distinct_submissions_create_distinct_leads(self):
        first = self._post(self._payload()).json()
        second = self._post(self._payload()).json()
        self.assertNotEqual(
            first["data"]["reference"], second["data"]["reference"]
        )

    def test_failed_request_can_be_retried(self):
        """A transient failure must not be cached forever."""
        payload = self._payload(last_name="")
        self.assertEqual(self._post(payload).status_code, 422)

        payload["last_name"] = "Diallo"
        retried = self._post(payload)
        self.assertEqual(retried.status_code, 201)

    # ─── Method handling ─────────────────────────────────────────────

    def test_get_is_not_allowed(self):
        response = self.url_open(self.ENDPOINT, timeout=30)
        self.assertIn(response.status_code, (404, 405))


@tagged("post_install", "-at_install", "dally")
class TestHealthEndpoint(HttpCase):

    def test_health_requires_authentication(self):
        """An open health endpoint is free reconnaissance."""
        response = self.url_open("/api/v1/health", timeout=30)
        self.assertEqual(response.status_code, 401)

    def test_health_returns_ok_with_valid_key(self):
        key = self.env["dally.api.key"].create({
            "name": "Monitoring", "scopes": "customers:read", "allowed_ips": "",
        })
        response = self.url_open(
            "/api/v1/health",
            headers={"X-API-Key": key.key_to_display},
            timeout=30,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "ok")
