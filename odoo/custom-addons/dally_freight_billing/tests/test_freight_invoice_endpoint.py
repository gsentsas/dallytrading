# -*- coding: utf-8 -*-
import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightInvoiceEndpoint(HttpCase):

    ENDPOINT = "/api/v1/freight/invoice"

    def setUp(self):
        super().setUp()
        self.billing_user = self.env.ref(
            "dally_freight_billing.user_dally_freight_billing_integration"
        )
        self.key = self.env["dally.api.key"].create({
            "name": "Freight Invoice Test Key",
            "scopes": "freight:invoice",
            "allowed_ips": "",
            "user_id": self.billing_user.id,
        })
        self.raw_key = self.key.key_to_display

    def _post(self, payload, api_key=None):
        headers = {"Content-Type": "application/json"}
        key = self.raw_key if api_key is None else api_key
        if key:
            headers["X-API-Key"] = key
        return self.url_open(
            self.ENDPOINT,
            data=json.dumps(payload),
            headers=headers,
            timeout=30,
        )

    def _shipment(self, reference):
        partner = self.env["res.partner"].create({
            "name": "Invoice API Customer %s" % reference,
        })
        shipment = self.env["dally.shipment"].create({
            "partner_id": partner.id,
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
            "customer_segment_snapshot": "individual",
        })
        line = self.env["dally.shipment.package"].create({
            "shipment_id": shipment.id,
            "external_line_key": "%s|A|1" % reference,
            "package_type": "parcel",
            "description": "Café Touba",
            "quantity": 1,
            "unit_weight_kg": 10.0,
            "billing_method": "real",
            "tariff_family_id": self.env.ref(
                "dally_freight_billing.tariff_family_food"
            ).id,
        })
        line.action_apply_freight_tariff()
        return shipment

    def _payload(self, reference, **overrides):
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "external_reference": reference,
        }
        payload.update(overrides)
        return payload

    def test_uses_dedicated_billing_user(self):
        self.assertEqual(self.key.user_id, self.billing_user)
        self.assertTrue(self.billing_user.has_group("account.group_account_invoice"))
        self.assertTrue(self.billing_user.has_group("sales_team.group_sale_salesman"))

    def test_requires_invoice_scope(self):
        shipment = self._shipment("HTTP-INV-SCOPE")
        limited = self.env["dally.api.key"].create({
            "name": "Sync Only",
            "scopes": "freight:write",
            "allowed_ips": "",
            "user_id": self.billing_user.id,
        })
        response = self._post(
            self._payload(shipment.external_reference),
            api_key=limited.key_to_display,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "insufficient_scope")

    def test_scope_does_not_grant_native_accounting_rights(self):
        shipment = self._shipment("HTTP-INV-ACL")
        generic_user = self.env.ref("dally_api.user_dally_api_integration")
        wrong_user_key = self.env["dally.api.key"].create({
            "name": "Invoice Scope Generic User",
            "scopes": "freight:invoice",
            "allowed_ips": "",
            "user_id": generic_user.id,
        })
        response = self._post(
            self._payload(shipment.external_reference),
            api_key=wrong_user_key.key_to_display,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")

    def test_creates_draft_invoice(self):
        shipment = self._shipment("HTTP-INV-CREATE")
        response = self._post(self._payload(shipment.external_reference))
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertTrue(data["created"])
        self.assertEqual(data["invoice_state"], "draft")
        self.assertTrue(data["billing_locked"])
        self.assertEqual(data["shipment_id"], shipment.id)
        self.assertAlmostEqual(data["amount_total"], 35.0, places=2)

    def test_new_request_uuid_is_business_idempotent(self):
        shipment = self._shipment("HTTP-INV-RETRY")
        first = self._post(self._payload(shipment.external_reference))
        second = self._post(self._payload(shipment.external_reference))
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            first.json()["data"]["invoice_id"],
            second.json()["data"]["invoice_id"],
        )
        self.assertFalse(second.json()["data"]["created"])

    def test_unknown_shipment_returns_404(self):
        response = self._post(self._payload("DOES-NOT-EXIST"))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "shipment_not_found")

    def test_unknown_field_is_rejected(self):
        shipment = self._shipment("HTTP-INV-FIELD")
        response = self._post(
            self._payload(shipment.external_reference, post_invoice=True)
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unknown_fields")

    def test_invoice_request_is_logged_against_account_move(self):
        shipment = self._shipment("HTTP-INV-LOG")
        payload = self._payload(shipment.external_reference)
        response = self._post(payload)
        self.assertEqual(response.status_code, 201)
        log = self.env["dally.api.request"].search([
            ("request_uuid", "=", payload["request_uuid"]),
            ("endpoint", "=", self.ENDPOINT),
        ])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.res_model, "account.move")
        self.assertEqual(log.res_id, response.json()["data"]["invoice_id"])
