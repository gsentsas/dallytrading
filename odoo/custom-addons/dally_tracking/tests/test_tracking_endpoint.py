# -*- coding: utf-8 -*-
"""HTTP tests for GET /api/v1/tracking/<reference> (§90).

Through the real stack: routing, authentication, scope checking, error mapping and
serialisation. A model-level test cannot catch a wrong status code, and it cannot
prove that the response body which actually leaves the server is clean.
"""

import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestTrackingEndpoint(HttpCase):

    SECRET_NOTE = "HTTP-LEAK-CANARY-internal-note"

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({
            "name": "HTTP Tracking Customer",
            "email": "http-private@example.com",
        })
        self.shipment = self.env["dally.shipment"].create({
            "partner_id": self.partner.id,
            "transport_mode": "sea",
            "direction": "import",
            "origin_city": "Le Havre",
            "destination_city": "Dakar",
            "goods_description": "Automotive spare parts",
            "estimated_arrival": "2026-10-01",
            "supplier_cost": 777888.99,
            "internal_notes": self.SECRET_NOTE,
        })
        self.env["dally.shipment.event"].create({
            "shipment_id": self.shipment.id,
            "status": "departed",
            "description": "Goods loaded and vessel departed",
            "location": "Le Havre",
            "internal_note": "HTTP-EVENT-CANARY chase the agent",
            "visible_to_customer": True,
        })
        self.env["dally.shipment.event"].create({
            "shipment_id": self.shipment.id,
            "status": "preparing",
            "description": "HTTP-INTERNAL-CANARY not for the customer",
            "visible_to_customer": False,
        })

        # A key acting as the dedicated tracking user, which is how production is
        # configured. allowed_ips is emptied because the test client's address
        # varies between runners.
        self.key = self.env["dally.api.key"].create({
            "name": "Tracking test key",
            "scopes": "tracking:read",
            "allowed_ips": "",
            "user_id": self.env.ref("dally_tracking.user_dally_api_tracking").id,
        })
        self.raw_key = self.key.key_to_display

    def _get(self, reference, api_key=None):
        headers = {}
        key = self.raw_key if api_key is None else api_key
        if key:
            headers["X-API-Key"] = key
        return self.url_open(
            "/api/v1/tracking/%s" % reference, headers=headers, timeout=30
        )

    # ─── Authentication ──────────────────────────────────────────────

    def test_requires_an_api_key(self):
        response = self._get(self.shipment.reference, api_key=False)
        self.assertEqual(response.status_code, 401)

    def test_rejects_an_invalid_key(self):
        response = self._get(self.shipment.reference, api_key="wrong-key")
        self.assertEqual(response.status_code, 401)

    def test_rejects_a_key_without_the_tracking_scope(self):
        leads_only = self.env["dally.api.key"].create({
            "name": "Leads only", "scopes": "leads:write", "allowed_ips": "",
        })
        response = self._get(
            self.shipment.reference, api_key=leads_only.key_to_display
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "insufficient_scope")

    # ─── Lookup ──────────────────────────────────────────────────────

    def test_returns_the_shipment(self):
        response = self._get(self.shipment.reference)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["reference"], self.shipment.reference)
        self.assertEqual(data["goodsDescription"], "Automotive spare parts")
        self.assertEqual(data["estimatedArrival"], "2026-10-01")

    def test_lookup_is_case_insensitive(self):
        response = self._get(self.shipment.reference.lower())
        self.assertEqual(response.status_code, 200)

    def test_unknown_reference_returns_404(self):
        response = self._get("DT-SHP-2026-999999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_malformed_reference_is_indistinguishable_from_unknown(self):
        """Same status and same body, so the endpoint cannot be probed."""
        unknown = self._get("DT-SHP-2026-999999")
        malformed = self._get("not-a-reference")
        self.assertEqual(malformed.status_code, 404)
        self.assertEqual(unknown.json()["error"], malformed.json()["error"])

    def test_sql_injection_attempt_is_just_a_404(self):
        for payload in ("DT-SHP-2026-000001' OR '1'='1", "%27", "../../etc/passwd"):
            with self.subTest(payload=payload):
                response = self._get(payload)
                self.assertEqual(response.status_code, 404)

    def test_no_listing_endpoint(self):
        response = self.url_open(
            "/api/v1/tracking",
            headers={"X-API-Key": self.raw_key},
            timeout=30,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "reference_required")

    # ─── Confidentiality of the wire response (§44) ──────────────────

    def test_response_contains_no_confidential_value(self):
        body = self._get(self.shipment.reference).text

        self.assertNotIn(self.SECRET_NOTE, body)
        self.assertNotIn("HTTP-EVENT-CANARY", body)
        self.assertNotIn("HTTP-INTERNAL-CANARY", body)
        self.assertNotIn("777888", body)
        self.assertNotIn("HTTP Tracking Customer", body)
        self.assertNotIn("http-private@example.com", body)

    def test_response_contains_no_database_id(self):
        body = self._get(self.shipment.reference).text
        self.assertNotIn('"id"', body)
        self.assertNotIn(str(self.shipment.id), json.dumps(
            self._get(self.shipment.reference).json()["data"]["timeline"]
        ))

    def test_timeline_holds_only_the_visible_event(self):
        timeline = self._get(self.shipment.reference).json()["data"]["timeline"]
        self.assertEqual(len(timeline), 1)
        self.assertIn("vessel departed", timeline[0]["description"])
        self.assertNotIn("internalNote", timeline[0])
        self.assertNotIn("attachments", timeline[0])

    def test_response_is_not_cacheable(self):
        response = self._get(self.shipment.reference)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_shipment_of_another_company_is_not_reachable(self):
        other_company = self.env["res.company"].create({"name": "Foreign Co"})
        foreign = self.env["dally.shipment"].create({
            "partner_id": self.partner.id,
            "transport_mode": "air",
            "direction": "export",
            "company_id": other_company.id,
        })
        response = self._get(foreign.reference)
        self.assertEqual(
            response.status_code, 404,
            "The multi-company rule must apply to the public endpoint too",
        )
