# -*- coding: utf-8 -*-
import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightPaymentReconcileEndpoint(HttpCase):

    PAYMENT_ENDPOINT = "/api/v1/freight/payment"
    RECONCILE_ENDPOINT = "/api/v1/freight/payment/reconcile"

    def setUp(self):
        super().setUp()
        self.billing_user = self.env.ref(
            "dally_freight_billing.user_dally_freight_billing_integration"
        )
        self.key = self.env["dally.api.key"].create({
            "name": "Freight Payment Reconcile Test Key",
            "scopes": "freight:payment",
            "allowed_ips": "",
            "user_id": self.billing_user.id,
        })
        self.raw_key = self.key.key_to_display
        self.eur = self.env.ref("base.EUR")
        self.eur.active = True

    def _shipment(self, reference):
        partner = self.env["res.partner"].create({
            "name": "Payment Reconcile Customer %s" % reference,
        })
        return self.env["dally.shipment"].create({
            "partner_id": partner.id,
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
        })

    def _post(self, endpoint, payload):
        return self.url_open(
            endpoint,
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self.raw_key,
            },
            timeout=30,
        )

    def _payment_payload(self, shipment, key, source="google_sheets"):
        return {
            "request_uuid": str(uuid.uuid4()),
            "external_payment_key": key,
            "external_reference": shipment.external_reference,
            "shipment_id": shipment.id,
            "amount": 25.0,
            "currency_code": "EUR",
            "payment_date": "2026-08-22",
            "payment_method": "wave",
            "collected_by": "Gilles",
            "source": source,
        }

    def _reconcile_payload(self, shipment, active_keys, source="google_sheets"):
        return {
            "request_uuid": str(uuid.uuid4()),
            "external_reference": shipment.external_reference,
            "shipment_id": shipment.id,
            "active_payment_keys": active_keys,
            "source": source,
        }

    def test_missing_pending_collection_is_cancelled(self):
        shipment = self._shipment("HTTP-PAY-RECONCILE-CANCEL")
        payment_key = "HTTP-PAY-RECONCILE-CANCEL|P|1"
        created = self._post(
            self.PAYMENT_ENDPOINT,
            self._payment_payload(shipment, payment_key, source="legacy_xlsx"),
        )
        self.assertEqual(created.status_code, 201)

        response = self._post(
            self.RECONCILE_ENDPOINT,
            self._reconcile_payload(shipment, [], source="google_sheets"),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn(payment_key, data["cancelled_payment_keys"])
        self.assertFalse(data["blocked_registered_payment_keys"])

        collection = self.env["dally.freight.collection"].search([
            ("external_payment_key", "=", payment_key),
        ])
        self.assertEqual(collection.state, "cancelled")
        self.assertFalse(collection.payment_id)

    def test_active_collection_is_preserved(self):
        shipment = self._shipment("HTTP-PAY-RECONCILE-ACTIVE")
        payment_key = "HTTP-PAY-RECONCILE-ACTIVE|P|1"
        self._post(
            self.PAYMENT_ENDPOINT,
            self._payment_payload(shipment, payment_key),
        )

        response = self._post(
            self.RECONCILE_ENDPOINT,
            self._reconcile_payload(shipment, [payment_key]),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertFalse(data["cancelled_payment_keys"])

        collection = self.env["dally.freight.collection"].search([
            ("external_payment_key", "=", payment_key),
        ])
        self.assertEqual(collection.state, "pending")

    def test_cancelled_collection_reactivates_with_same_business_key(self):
        shipment = self._shipment("HTTP-PAY-RECONCILE-REACTIVATE")
        payment_key = "HTTP-PAY-RECONCILE-REACTIVATE|P|1"
        self._post(
            self.PAYMENT_ENDPOINT,
            self._payment_payload(shipment, payment_key),
        )
        self._post(
            self.RECONCILE_ENDPOINT,
            self._reconcile_payload(shipment, []),
        )

        response = self._post(
            self.PAYMENT_ENDPOINT,
            self._payment_payload(shipment, payment_key),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertFalse(data["created"])
        self.assertEqual(data["collection_state"], "pending")

        collection = self.env["dally.freight.collection"].search([
            ("external_payment_key", "=", payment_key),
        ])
        self.assertEqual(collection.state, "pending")
