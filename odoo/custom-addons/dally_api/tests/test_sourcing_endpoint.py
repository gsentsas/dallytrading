# -*- coding: utf-8 -*-
"""HTTP tests for POST /api/v1/sourcing/requests.

Through the real stack, because that is where an endpoint fails: a model test cannot
catch a wrong status code, a leaked traceback, or an internal field that slipped into a
response.
"""

import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestSourcingEndpoint(HttpCase):

    ENDPOINT = "/api/v1/sourcing/requests"

    def setUp(self):
        super().setUp()
        self.key = self.env["dally.api.key"].create({
            "name": "Sourcing test key",
            "scopes": "sourcing:write",
            "allowed_ips": "",
            "user_id": self.env.ref("dally_sourcing.user_dally_api_sourcing").id,
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
            "service_code": "sourcing",
            "customer": {
                "first_name": "Awa",
                "last_name": "Diallo",
                "company": "Diallo Trading",
                "email": "awa.diallo@example.com",
                "phone": "+221 77 555 44 33",
            },
            "product": {
                "name": "Panneaux solaires 400W",
                "description": "Pour installation résidentielle.",
                "specifications": "Monocristallin, garantie 10 ans.",
            },
            "quantity": 200,
            "uom": "Units",
            "budget": 40000,
            "currency": "EUR",
            "preferred_origin_country": "CN",
            "destination_country": "SN",
            "notes": "Livraison à Dakar.",
            "utm": {"source": "google", "medium": "cpc", "campaign": "sourcing"},
        }
        payload.update(overrides)
        return payload

    # ─── Authentication and scope ────────────────────────────────────

    def test_requires_an_api_key(self):
        response = self._post(self._payload(), api_key=False)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "missing_api_key")

    def test_rejects_an_invalid_key(self):
        self.assertEqual(self._post(self._payload(), api_key="nope").status_code, 401)

    def test_rejects_a_key_without_the_sourcing_scope(self):
        other = self.env["dally.api.key"].create({
            "name": "Leads only", "scopes": "leads:write", "allowed_ips": "",
        })
        response = self._post(self._payload(), api_key=other.key_to_display)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "insufficient_scope")

    def test_tracking_scope_is_not_enough(self):
        other = self.env["dally.api.key"].create({
            "name": "Tracking only", "scopes": "tracking:read", "allowed_ips": "",
        })
        response = self._post(self._payload(), api_key=other.key_to_display)
        self.assertEqual(response.status_code, 403)

    # ─── Body validation ─────────────────────────────────────────────

    def test_rejects_invalid_json(self):
        self.assertEqual(self._post(None, raw_body="{oops").status_code, 400)

    def test_rejects_a_missing_request_uuid(self):
        payload = self._payload()
        del payload["request_uuid"]
        response = self._post(payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "missing_request_uuid")

    def test_rejects_a_non_uuid_request_id(self):
        self.assertEqual(
            self._post(self._payload(request_uuid="nope")).status_code, 422,
        )

    def test_rejects_a_missing_product_name(self):
        response = self._post(self._payload(product={"description": "x"}))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "missing_fields")

    def test_rejects_a_missing_contact_channel(self):
        response = self._post(self._payload(customer={
            "last_name": "Diallo", "email": "", "phone": "",
        }))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "no_contact_channel")

    def test_rejects_a_missing_name(self):
        response = self._post(self._payload(customer={
            "email": "someone@example.com",
        }))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "missing_fields")

    def test_rejects_a_malformed_email(self):
        for bad in ("nope", "a@b", "@example.com", "a b@c.com"):
            with self.subTest(email=bad):
                response = self._post(self._payload(customer={
                    "last_name": "Diallo", "email": bad,
                }))
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "invalid_email")

    def test_rejects_a_non_positive_quantity(self):
        for quantity in (0, -5):
            with self.subTest(quantity=quantity):
                response = self._post(self._payload(quantity=quantity))
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json()["error"]["code"], "invalid_quantity",
                )

    def test_rejects_an_absurd_quantity(self):
        response = self._post(self._payload(quantity=10_000_000_000))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "field_too_large")

    def test_rejects_a_non_numeric_quantity(self):
        response = self._post(self._payload(quantity="beaucoup"))
        self.assertEqual(response.status_code, 422)

    def test_rejects_a_negative_budget(self):
        response = self._post(self._payload(budget=-100))
        self.assertEqual(response.status_code, 422)

    def test_rejects_an_unknown_currency(self):
        response = self._post(self._payload(currency="ZZZ"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unknown_currency")

    def test_rejects_an_unknown_country(self):
        response = self._post(self._payload(preferred_origin_country="ZZ"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unknown_country")

    def test_rejects_an_unknown_service(self):
        response = self._post(self._payload(service_code="no_such_service"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unknown_service")

    def test_rejects_a_malformed_date(self):
        response = self._post(self._payload(requested_deadline="12/06/2026"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_date")

    def test_rejects_an_incoherent_date_range(self):
        response = self._post(self._payload(
            requested_deadline="2026-06-01", required_delivery_date="2026-05-01",
        ))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_date_range")

    def test_rejects_a_non_object_nested_field(self):
        response = self._post(self._payload(product="a string"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_field_type")

    def test_rejects_an_overlong_field(self):
        response = self._post(self._payload(product={
            "name": "x" * 500,
        }))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "field_too_long")

    def test_service_code_defaults_to_sourcing(self):
        payload = self._payload()
        del payload["service_code"]
        response = self._post(payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["service"], "sourcing")

    # ─── Success ─────────────────────────────────────────────────────

    def test_creates_a_request_and_returns_a_reference(self):
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 201)

        body = response.json()
        self.assertRegex(body["data"]["reference"], r"^DT-SRC-\d{4}-\d{6}$")
        self.assertEqual(body["data"]["status"], "received")
        self.assertTrue(body["request_id"])

        request = self.env["dally.sourcing.request"].search(
            [("reference", "=", body["data"]["reference"])]
        )
        self.assertEqual(len(request), 1)
        self.assertEqual(request.product_name, "Panneaux solaires 400W")
        self.assertAlmostEqual(request.quantity, 200.0)
        self.assertAlmostEqual(request.target_total_budget, 40000.0)
        self.assertEqual(request.currency_id.name, "EUR")
        self.assertEqual(request.state, "new")

    def test_response_exposes_nothing_internal(self):
        body = self._post(self._payload()).json()
        serialised = json.dumps(body)
        self.assertNotIn('"id"', serialised)
        self.assertNotIn("_record", serialised)
        self.assertNotIn("internal", serialised.lower())
        self.assertNotIn("customer_id", serialised)
        self.assertNotIn("partner", serialised.lower())
        # Whether an existing contact matched is internal commercial information.
        self.assertNotIn("matched", serialised.lower())

    def test_ignores_unexpected_fields(self):
        response = self._post(self._payload(
            state="completed", responsible_id=1, internal_notes="injected",
            active=False, customer_id=1,
        ))
        self.assertEqual(response.status_code, 201)

        request = self.env["dally.sourcing.request"].search(
            [("reference", "=", response.json()["data"]["reference"])]
        )
        self.assertEqual(request.state, "new")
        self.assertFalse(request.responsible_id)
        self.assertTrue(request.active)

    def test_creates_nothing_downstream(self):
        partners = self.env["res.partner"].search_count([])
        leads = self.env["crm.lead"].search_count([])
        orders = self.env["purchase.order"].search_count([])
        shipments = self.env["dally.shipment"].search_count([])

        self._post(self._payload(customer={
            "last_name": "Brand New",
            "company": "Never Seen Ltd",
            "email": "never-seen-sourcing@example.com",
        }))

        self.assertEqual(self.env["res.partner"].search_count([]), partners)
        self.assertEqual(self.env["crm.lead"].search_count([]), leads)
        self.assertEqual(self.env["purchase.order"].search_count([]), orders)
        self.assertEqual(self.env["dally.shipment"].search_count([]), shipments)

    def test_response_is_not_cacheable(self):
        response = self._post(self._payload())
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    # ─── Idempotency ─────────────────────────────────────────────────

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
            self.env["dally.sourcing.request"].search_count(
                [("request_uuid", "=", payload["request_uuid"])]
            ),
            1,
        )

    def test_distinct_submissions_create_distinct_requests(self):
        first = self._post(self._payload()).json()
        second = self._post(self._payload()).json()
        self.assertNotEqual(
            first["data"]["reference"], second["data"]["reference"],
        )

    def test_a_rejected_submission_can_be_retried(self):
        payload = self._payload(quantity=0)
        self.assertEqual(self._post(payload).status_code, 422)
        payload["quantity"] = 10
        self.assertEqual(self._post(payload).status_code, 201)

    # ─── Logging ─────────────────────────────────────────────────────

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
        self.assertEqual(log.res_model, "dally.sourcing.request")
        self.assertNotIn("should-be-redacted", log.payload or "")
        self.assertNotIn(self.raw_key, log.payload or "")

    def test_get_is_not_allowed(self):
        """There is deliberately no public read endpoint yet (§28)."""
        response = self.url_open(self.ENDPOINT, timeout=30)
        self.assertIn(response.status_code, (404, 405))
