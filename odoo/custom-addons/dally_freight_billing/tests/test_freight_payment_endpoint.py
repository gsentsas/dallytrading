# -*- coding: utf-8 -*-
import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightPaymentEndpoint(HttpCase):

    ENDPOINT = "/api/v1/freight/payment"

    def setUp(self):
        super().setUp()
        self.billing_user = self.env.ref(
            "dally_freight_billing.user_dally_freight_billing_integration"
        )
        self.key = self.env["dally.api.key"].create({
            "name": "Freight Payment Test Key",
            "scopes": "freight:payment",
            "allowed_ips": "",
            "user_id": self.billing_user.id,
        })
        self.raw_key = self.key.key_to_display
        self.eur = self.env.ref("base.EUR")
        self.eur.active = True

    def _shipment(self, reference):
        partner = self.env["res.partner"].create({
            "name": "Payment API Customer %s" % reference,
        })
        return self.env["dally.shipment"].create({
            "partner_id": partner.id,
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
        })

    def _payload(self, reference, **overrides):
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "external_payment_key": "BF-%s" % str(uuid.uuid4()),
            "external_reference": reference,
            "amount": 25.0,
            "currency_code": "EUR",
            "payment_date": "2026-08-21",
            "payment_method": "wave",
            "collected_by": "Gilles",
            "source": "google_sheets",
        }
        payload.update(overrides)
        return payload

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

    def test_uses_dedicated_billing_user(self):
        self.assertEqual(self.key.user_id, self.billing_user)
        self.assertTrue(self.key.has_scope("freight:payment"))

    def test_requires_payment_scope(self):
        shipment = self._shipment("HTTP-PAY-SCOPE")
        limited = self.env["dally.api.key"].create({
            "name": "Invoice Only",
            "scopes": "freight:invoice",
            "allowed_ips": "",
            "user_id": self.billing_user.id,
        })
        response = self._post(
            self._payload(shipment.external_reference),
            api_key=limited.key_to_display,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "insufficient_scope")

    def test_scope_does_not_bypass_collection_acl(self):
        shipment = self._shipment("HTTP-PAY-ACL")
        generic_user = self.env.ref("dally_api.user_dally_api_integration")
        wrong_user_key = self.env["dally.api.key"].create({
            "name": "Payment Scope Generic User",
            "scopes": "freight:payment",
            "allowed_ips": "",
            "user_id": generic_user.id,
        })
        response = self._post(
            self._payload(shipment.external_reference),
            api_key=wrong_user_key.key_to_display,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")

    def test_creates_pending_collection_before_invoice(self):
        shipment = self._shipment("HTTP-PAY-CREATE")
        payload = self._payload(shipment.external_reference)
        response = self._post(payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertTrue(data["created"])
        self.assertEqual(data["external_payment_key"], payload["external_payment_key"])
        self.assertEqual(data["shipment_id"], shipment.id)
        self.assertEqual(data["currency"], "EUR")
        self.assertEqual(data["collection_state"], "pending")
        self.assertFalse(data["account_payment_id"])

    def test_same_request_uuid_replays_without_duplicate(self):
        shipment = self._shipment("HTTP-PAY-REPLAY")
        payload = self._payload(shipment.external_reference)
        first = self._post(payload)
        second = self._post(payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            first.json()["data"]["collection_id"],
            second.json()["data"]["collection_id"],
        )
        self.assertEqual(
            self.env["dally.freight.collection"].search_count([
                ("external_payment_key", "=", payload["external_payment_key"])
            ]),
            1,
        )

    def test_new_http_uuid_same_payment_key_is_business_idempotent(self):
        shipment = self._shipment("HTTP-PAY-BUSINESS")
        payload = self._payload(shipment.external_reference)
        first = self._post(payload)
        self.assertEqual(first.status_code, 201)
        payload["request_uuid"] = str(uuid.uuid4())
        second = self._post(payload)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["data"]["created"])
        self.assertEqual(
            first.json()["data"]["collection_id"],
            second.json()["data"]["collection_id"],
        )

    def test_unknown_currency_is_rejected(self):
        shipment = self._shipment("HTTP-PAY-CURRENCY")
        response = self._post(
            self._payload(shipment.external_reference, currency_code="ZZZ")
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unknown_currency")

    def test_non_positive_amount_is_rejected(self):
        shipment = self._shipment("HTTP-PAY-AMOUNT")
        response = self._post(
            self._payload(shipment.external_reference, amount=0)
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_amount")

    def test_unknown_field_is_rejected(self):
        shipment = self._shipment("HTTP-PAY-FIELD")
        response = self._post(
            self._payload(shipment.external_reference, journal_id=1)
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unknown_fields")

    def test_success_is_logged_against_collection(self):
        shipment = self._shipment("HTTP-PAY-LOG")
        payload = self._payload(shipment.external_reference)
        response = self._post(payload)
        self.assertEqual(response.status_code, 201)
        log = self.env["dally.api.request"].search([
            ("request_uuid", "=", payload["request_uuid"]),
            ("endpoint", "=", self.ENDPOINT),
        ])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.res_model, "dally.freight.collection")
        self.assertEqual(log.res_id, response.json()["data"]["collection_id"])
