# -*- coding: utf-8 -*-
"""End-to-end HTTP tests for POST /api/v1/freight/sync."""

import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightSyncEndpoint(HttpCase):

    ENDPOINT = "/api/v1/freight/sync"

    def setUp(self):
        super().setUp()
        self.sync_user = self.env.ref(
            "dally_freight_billing.user_dally_freight_sync_integration"
        )
        self.key = self.env["dally.api.key"].create({
            "name": "Freight Sheet Test Key",
            "scopes": "freight:write",
            "allowed_ips": "",
            "user_id": self.sync_user.id,
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
        suffix = str(uuid.uuid4())[:8]
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "external_reference": "GS-%s" % suffix,
            "transport_mode": "air",
            "direction": "export",
            "source": "google_sheets",
            "goods_received_on": "2026-08-21",
            "customer_segment": "individual",
            "client": {
                "name": "Fatou Test %s" % suffix,
                "email": "fatou.%s@example.com" % suffix,
                "phone": "+221 77 555 00 11",
                "address": "Dakar",
            },
            "origin": {"country_code": "SN", "city": "Dakar"},
            "destination": {"country_code": "FR", "city": "Paris"},
            "lines": [{
                "external_line_key": "GS-%s|A|1" % suffix,
                "description": "Café Touba",
                "goods_category": "Alimentaires",
                "quantity": 1,
                "announced_weight_kg": 8.0,
                "exact_weight_kg": 7.5,
                "billing_method": "real",
                "tariff_family_code": "food",
                "customs_value_xof": 15000,
            }],
        }
        payload.update(overrides)
        return payload

    def test_freight_write_scope_is_valid_for_api_key(self):
        self.assertIn("freight:write", self.key._scope_list())
        self.assertTrue(self.key.has_scope("freight:write"))
        self.assertEqual(self.key.user_id, self.sync_user)

    def test_rejects_missing_api_key(self):
        response = self._post(self._payload(), api_key=False)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "missing_api_key")

    def test_rejects_insufficient_scope(self):
        limited = self.env["dally.api.key"].create({
            "name": "Freight Wrong Scope",
            "scopes": "tracking:read",
            "allowed_ips": "",
            "user_id": self.sync_user.id,
        })
        response = self._post(self._payload(), api_key=limited.key_to_display)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "insufficient_scope")

    def test_scope_does_not_bypass_acting_user_acl(self):
        generic_user = self.env.ref("dally_api.user_dally_api_integration")
        wrong_user_key = self.env["dally.api.key"].create({
            "name": "Freight Scope With Generic User",
            "scopes": "freight:write",
            "allowed_ips": "",
            "user_id": generic_user.id,
        })
        response = self._post(self._payload(), api_key=wrong_user_key.key_to_display)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")

    def test_creates_shipment_and_returns_sync_ids(self):
        payload = self._payload()
        response = self._post(payload)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["success"])
        data = body["data"]
        self.assertTrue(data["partner_id"])
        self.assertTrue(data["shipment_id"])
        self.assertTrue(data["shipment_created"])
        self.assertEqual(data["external_reference"], payload["external_reference"])
        self.assertEqual(data["lines"][0]["pricing_status"], "automatic")
        self.assertAlmostEqual(data["lines"][0]["applied_unit_price_eur"], 3.5, places=2)

        shipment = self.env["dally.shipment"].browse(data["shipment_id"]).exists()
        self.assertTrue(shipment)
        self.assertEqual(shipment.external_reference, payload["external_reference"])
        self.assertEqual(len(shipment.package_ids), 1)

    def test_same_request_uuid_replays_without_duplicate(self):
        payload = self._payload()
        first = self._post(payload)
        second = self._post(payload)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            first.json()["data"]["shipment_id"],
            second.json()["data"]["shipment_id"],
        )
        self.assertEqual(
            self.env["dally.shipment"].search_count([
                ("external_reference", "=", payload["external_reference"])
            ]),
            1,
        )

    def test_new_http_uuid_same_business_keys_updates_without_duplicate(self):
        payload = self._payload()
        first = self._post(payload)
        self.assertEqual(first.status_code, 201)

        payload["request_uuid"] = str(uuid.uuid4())
        payload["lines"][0]["exact_weight_kg"] = 10.0
        second = self._post(payload)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["data"]["shipment_created"])
        self.assertEqual(
            first.json()["data"]["shipment_id"],
            second.json()["data"]["shipment_id"],
        )

        line_id = second.json()["data"]["lines"][0]["line_id"]
        line = self.env["dally.shipment.package"].browse(line_id)
        self.assertAlmostEqual(line.total_weight_kg, 10.0, places=3)
        self.assertAlmostEqual(line.transport_amount_eur, 35.0, places=2)

    def test_invoiced_shipment_resync_does_not_require_accounting_acl(self):
        payload = self._payload()
        first = self._post(payload)
        self.assertEqual(first.status_code, 201)

        shipment = self.env["dally.shipment"].browse(
            first.json()["data"]["shipment_id"]
        )
        invoice = shipment.action_prepare_native_freight_invoice()
        self.assertEqual(invoice.state, "draft")
        self.assertTrue(shipment.invoice_id)

        payload["request_uuid"] = str(uuid.uuid4())
        second = self._post(payload)
        self.assertEqual(second.status_code, 200)
        data = second.json()["data"]
        self.assertEqual(data["shipment_id"], shipment.id)
        self.assertEqual(data["lines"][0]["pricing_status"], "locked")
        self.assertNotIn("sale_order_id", data)
        self.assertNotIn("invoice_id", data)
        self.assertNotIn("invoice_number", data)
        self.assertNotIn("invoice_state", data)

    def test_unknown_top_level_field_is_rejected(self):
        payload = self._payload()
        payload["user_id"] = 1
        response = self._post(payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unknown_fields")

    def test_unknown_line_field_is_rejected(self):
        payload = self._payload()
        payload["lines"][0]["supplier_cost"] = 1
        response = self._post(payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unknown_line_fields")

    def test_sea_non_food_returns_manual_required_not_http_failure(self):
        payload = self._payload(transport_mode="sea")
        payload["lines"][0]["tariff_family_code"] = "non_food"
        response = self._post(payload)
        self.assertEqual(response.status_code, 201)
        line = response.json()["data"]["lines"][0]
        self.assertEqual(line["pricing_status"], "manual_required")
        self.assertFalse(line["applied_unit_price_eur"])

    def test_success_request_is_logged_against_shipment(self):
        payload = self._payload()
        response = self._post(payload)
        self.assertEqual(response.status_code, 201)

        log = self.env["dally.api.request"].search([
            ("request_uuid", "=", payload["request_uuid"]),
            ("endpoint", "=", self.ENDPOINT),
        ])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.status_code, 201)
        self.assertEqual(log.res_model, "dally.shipment")
        self.assertEqual(log.res_id, response.json()["data"]["shipment_id"])

    def test_log_never_contains_raw_api_key(self):
        payload = self._payload()
        self._post(payload)
        log = self.env["dally.api.request"].search([
            ("request_uuid", "=", payload["request_uuid"]),
        ])
        self.assertNotIn(self.raw_key, log.payload or "")
        self.assertNotIn(self.raw_key, log.response or "")

    def test_invalid_json_is_rejected(self):
        response = self._post(None, raw_body="{invalid")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_json")

    def test_get_is_not_allowed(self):
        response = self.url_open(self.ENDPOINT, timeout=30)
        self.assertIn(response.status_code, (404, 405))
