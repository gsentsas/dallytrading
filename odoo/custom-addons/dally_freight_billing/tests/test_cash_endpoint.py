# -*- coding: utf-8 -*-
import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightCashEndpoint(HttpCase):

    def setUp(self):
        super().setUp()
        self.billing_user = self.env.ref(
            "dally_freight_billing.user_dally_freight_billing_integration"
        )
        self.key = self.env["dally.api.key"].create({
            "name": "Freight Cash Test Key",
            "scopes": "freight:cash",
            "allowed_ips": "",
            "user_id": self.billing_user.id,
        })
        self.raw_key = self.key.key_to_display
        self.eur = self.env.ref("base.EUR")
        self.xof = self.env.ref("base.XOF")
        self.eur.active = True
        self.xof.active = True

    def _post(self, endpoint, payload, api_key=None):
        headers = {"Content-Type": "application/json"}
        key = self.raw_key if api_key is None else api_key
        if key:
            headers["X-API-Key"] = key
        return self.url_open(
            endpoint, data=json.dumps(payload), headers=headers, timeout=30,
        )

    def _expense_payload(self, **overrides):
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "external_expense_key": "DEP-%s" % str(uuid.uuid4()),
            "expense_date": "2026-08-21",
            "category": "Transport",
            "description": "Course client",
            "beneficiary": "Prestataire",
            "currency_code": "XOF",
            "total_eur_snapshot": 15.24,
            "total_xof_snapshot": 10000.0,
            "payment_method": "Wave",
            "state": "validated",
            "source": "google_sheets",
            "allocations": [
                {"actor": "Gilles", "amount": 6000.0},
                {"actor": "Alain", "amount": 4000.0},
            ],
        }
        payload.update(overrides)
        return payload

    def _transfer_payload(self, **overrides):
        payload = {
            "request_uuid": str(uuid.uuid4()),
            "external_transfer_key": "TRF-%s" % str(uuid.uuid4()),
            "transfer_date": "2026-08-21",
            "from_actor": "Gilles",
            "to_actor": "Dalanda",
            "amount": 25.0,
            "currency_code": "EUR",
            "total_eur_snapshot": 25.0,
            "total_xof_snapshot": 16400.0,
            "reason": "Remise caisse",
            "payment_method": "Espèces",
            "state": "validated",
            "source": "google_sheets",
        }
        payload.update(overrides)
        return payload

    def test_expense_create_and_business_retry(self):
        endpoint = "/api/v1/freight/expense"
        payload = self._expense_payload()
        first = self._post(endpoint, payload)
        self.assertEqual(first.status_code, 201)
        expense_id = first.json()["data"]["expense_id"]
        payload["request_uuid"] = str(uuid.uuid4())
        second = self._post(endpoint, payload)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["data"]["expense_id"], expense_id)
        self.assertFalse(second.json()["data"]["created"])

    def test_transfer_create_and_business_retry(self):
        endpoint = "/api/v1/freight/cash-transfer"
        payload = self._transfer_payload()
        first = self._post(endpoint, payload)
        self.assertEqual(first.status_code, 201)
        transfer_id = first.json()["data"]["transfer_id"]
        payload["request_uuid"] = str(uuid.uuid4())
        second = self._post(endpoint, payload)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["data"]["transfer_id"], transfer_id)
        self.assertFalse(second.json()["data"]["created"])

    def test_cash_scope_is_required(self):
        limited = self.env["dally.api.key"].create({
            "name": "Payment Only Cash Negative Test",
            "scopes": "freight:payment",
            "allowed_ips": "",
            "user_id": self.billing_user.id,
        })
        response = self._post(
            "/api/v1/freight/expense", self._expense_payload(), limited.key_to_display
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "insufficient_scope")

    def test_cash_scope_does_not_bypass_technical_group(self):
        generic_user = self.env.ref("dally_api.user_dally_api_integration")
        wrong = self.env["dally.api.key"].create({
            "name": "Cash Scope Wrong User",
            "scopes": "freight:cash",
            "allowed_ips": "",
            "user_id": generic_user.id,
        })
        response = self._post(
            "/api/v1/freight/expense", self._expense_payload(), wrong.key_to_display
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")

    def test_expense_requires_positive_allocation(self):
        response = self._post(
            "/api/v1/freight/expense",
            self._expense_payload(allocations=[{"actor": "Gilles", "amount": 0}]),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "missing_allocations")

    def test_transfer_rejects_same_actor(self):
        response = self._post(
            "/api/v1/freight/cash-transfer",
            self._transfer_payload(from_actor="Gilles", to_actor="Gilles"),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "same_actor")
