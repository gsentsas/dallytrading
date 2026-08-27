# -*- coding: utf-8 -*-
import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestSheetBindingsEndpoint(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sync_user = cls.env.ref("dally_freight_billing.user_dally_freight_sync_integration")
        cls.partner = cls.env["res.partner"].create({"name": "Sheet bindings test partner"})
        cls.planned = cls.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-2099-BIND",
            "transport_mode": "air", "direction": "export", "state": "collecting",
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_city": "Paris", "destination_location": "CDG",
        })
        cls.shipment = cls.env["dally.shipment"].create({
            "partner_id": cls.partner.id,
            "external_reference": "SHEET-BINDINGS-1",
            "transport_mode": "air", "direction": "export",
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_city": "Paris", "destination_location": "CDG",
            "planned_consolidation_id": cls.planned.id,
        })
        cls.unplanned = cls.env["dally.shipment"].create({
            "partner_id": cls.partner.id, "external_reference": "SHEET-BINDINGS-2",
            "transport_mode": "air", "direction": "export",
        })
        cls.closed = cls.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-2099-CLOSED-BIND",
            "transport_mode": "air", "direction": "export", "state": "collecting",
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_city": "Paris", "destination_location": "CDG",
        })
        cls.closed_shipment = cls.env["dally.shipment"].create({
            "partner_id": cls.partner.id, "external_reference": "SHEET-BINDINGS-3",
            "transport_mode": "air", "direction": "export",
            "planned_consolidation_id": cls.closed.id,
        })
        cls.closed.action_close_collection()
        cls.other_company = cls.env["res.company"].create({"name": "Sheet Bindings Other Company"})
        cls.other_company_shipment = cls.env["dally.shipment"].with_company(cls.other_company).create({
            "partner_id": cls.partner.id, "external_reference": "SHEET-BINDINGS-OTHER",
            "transport_mode": "air", "direction": "export",
        })

    def setUp(self):
        super().setUp()
        self.key = self.env["dally.api.key"].create({
            "name": "Sheet bindings test key",
            "scopes": "freight:write",
            "allowed_ips": "",
            "user_id": self.env.ref("dally_freight_billing.user_dally_freight_sync_integration").id,
        })
        self.raw_key = self.key.key_to_display

    def _get(self, query=""):
        return self.url_open(
            "/api/v1/freight/sheet-bindings" + query,
            headers={"X-API-Key": self.raw_key}, timeout=30,
        )

    def test_missing_key_is_unauthorized(self):
        response = self.url_open("/api/v1/freight/sheet-bindings?shipment_ids=1", timeout=30)
        self.assertEqual(response.status_code, 401)

    def test_malformed_and_oversized_ids_are_rejected(self):
        self.assertEqual(self._get("?shipment_ids=1,nope").status_code, 422)
        self.assertEqual(self._get("?shipment_ids=" + ",".join(str(i) for i in range(1, 202))).status_code, 422)

    def test_wrong_group_is_forbidden(self):
        key = self.env["dally.api.key"].create({
            "name": "Non Freight group key", "scopes": "freight:write",
            "allowed_ips": "", "user_id": self.env.ref("base.user_admin").id,
        })
        response = self.url_open(
            "/api/v1/freight/sheet-bindings?shipment_ids=1",
            headers={"X-API-Key": key.key_to_display}, timeout=30,
        )
        self.assertEqual(response.status_code, 403)

    def test_own_company_binding_is_minimal(self):
        response = self._get("?shipment_ids=%s" % self.shipment.id)
        self.assertEqual(response.status_code, 200)
        row = response.json()["data"]["bindings"][0]
        self.assertEqual(row["shipment_id"], self.shipment.id)
        self.assertEqual(row["planned_consolidation_ref"], self.planned.name)
        self.assertFalse(set(row) & {"partner_id", "tk_shipment_id", "freight_shipment_id", "invoice_id"})

    def test_unknown_or_other_company_ids_are_not_returned(self):
        response = self._get("?shipment_ids=%s,%s,999999999" % (self.shipment.id, self.other_company_shipment.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["shipment_id"] for row in response.json()["data"]["bindings"]], [self.shipment.id])

    def test_unplanned_and_closed_assignments_are_reported(self):
        response = self._get("?shipment_ids=%s,%s" % (self.unplanned.id, self.closed_shipment.id))
        self.assertEqual(response.status_code, 200)
        rows = {row["shipment_id"]: row for row in response.json()["data"]["bindings"]}
        self.assertFalse(rows[self.unplanned.id]["planned_consolidation_ref"])
        self.assertEqual(rows[self.closed_shipment.id]["planned_consolidation_ref"], self.closed.name)
