# -*- coding: utf-8 -*-
"""Regression coverage for consolidation-scoped intake identities."""

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase


class TestIntakeSequence(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env["res.partner"].create({
            "name": "Intake Sequence Client",
            "company_type": "company",
            "email": "intake-sequence@test.invalid",
        })
        cls.service = cls.env["dally.freight.sync.service"]

    def _consolidation(self, name):
        return self.env["dally.freight.consolidation"].create({
            "name": name,
            "company_id": self.company.id,
            "transport_mode": "air",
            "direction": "export",
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_city": "Paris",
            "destination_location": "CDG",
            "state": "collecting",
        })

    def _payload(self, key, planned, external=None, state="request_received"):
        values = {
            "sync_source_key": key,
            "planned_consolidation_ref": planned.name,
            "transport_mode": "air",
            "direction": "export",
            "state": state,
            "client": {"name": self.partner.name, "email": self.partner.email},
        }
        if external:
            values["external_reference"] = external
        return values

    def test_allocations_restart_per_consolidation_and_retry_is_idempotent(self):
        second = self._consolidation("AIR-DSS-CDG-2099-002")
        third = self._consolidation("AIR-DSS-CDG-2099-003")

        result_a, shipment_a = self.service.upsert(
            self._payload("sheet:002:a", second)
        )
        result_b, shipment_b = self.service.upsert(
            self._payload("sheet:002:b", second)
        )
        result_c, shipment_c = self.service.upsert(
            self._payload("sheet:003:a", third)
        )

        self.assertEqual(result_a["collection_local_ref"], "A001")
        self.assertEqual(result_b["collection_local_ref"], "A002")
        self.assertEqual(result_c["collection_local_ref"], "A001")
        self.assertEqual(result_a["external_reference"], "AIR-DSS-CDG-2099-002-A001")
        self.assertEqual(result_c["external_reference"], "AIR-DSS-CDG-2099-003-A001")
        self.assertNotEqual(shipment_a.external_reference, shipment_c.external_reference)

        retry, retry_shipment = self.service.upsert(
            self._payload("sheet:002:a", second)
        )
        self.assertEqual(retry_shipment, shipment_a)
        self.assertEqual(retry["collection_local_ref"], "A001")
        self.assertEqual(
            self.env["dally.shipment"].search_count([
                ("sync_source_key", "=", "sheet:002:a"),
            ]),
            1,
        )

    def test_retry_preserves_global_identity_and_forged_external_is_rejected(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-RETRY")
        payload = self._payload("sheet:retry", consolidation)
        first, shipment = self.service.upsert(payload)
        second, retry = self.service.upsert(payload)
        self.assertEqual(shipment, retry)
        self.assertEqual(first["external_reference"], second["external_reference"])
        self.assertEqual(first["collection_local_ref"], "A001")
        with self.assertRaises(ValidationError):
            self.service.upsert(dict(payload, external_reference="A999"))

    def test_new_intake_requires_collecting_and_closed_existing_reports_replan(self):
        closed = self._consolidation("AIR-DSS-CDG-2099-CLOSED")
        closed.action_close_collection()
        with self.assertRaises(ValidationError):
            self.service.upsert(self._payload("sheet:closed:new", closed))
        collecting = self._consolidation("AIR-DSS-CDG-2099-REPLAN")
        payload = self._payload("sheet:replan", collecting)
        first, shipment = self.service.upsert(payload)
        collecting.action_close_collection()
        retry, same = self.service.upsert(payload)
        self.assertEqual(first["external_reference"], retry["external_reference"])
        self.assertTrue(retry["requires_replan"])
        self.assertEqual(same.planned_consolidation_id, collecting)

    def test_intake_identity_cannot_be_forged_by_create_or_write(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-GUARD")
        _, shipment = self.service.upsert(self._payload("sheet:guard", consolidation))
        with self.assertRaises(AccessError):
            self.env["dally.shipment"].create({
                "partner_id": self.partner.id, "external_reference": "FORGED",
                "intake_consolidation_id": consolidation.id,
                "collection_sequence": 1, "collection_local_ref": "A001",
                "sync_source_key": "forged",
            })
        for values in ({"collection_sequence": 999}, {"collection_local_ref": "A999"},
                       {"sync_source_key": "forged"}, {"external_reference": "FORGED"}):
            with self.assertRaises(AccessError):
                shipment.write(values)

    def test_legacy_external_reference_remains_supported(self):
        result, shipment = self.service.upsert({
            "external_reference": "A001",
            "transport_mode": "air",
            "direction": "export",
            "client": {"name": self.partner.name, "email": self.partner.email},
        })
        self.assertEqual(shipment.external_reference, "A001")
        self.assertEqual(result["external_reference"], "A001")

    def test_manual_local_reference_is_normalized_and_duplicate_rejected(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-004")
        _, shipment = self.service.upsert(
            self._payload("sheet:004:a", consolidation, state="request_received") | {
                "collection_local_ref": "A001",
            }
        )
        self.assertEqual(shipment.collection_sequence, 1)
        self.assertEqual(shipment.collection_local_ref, "A001")
        with self.assertRaises(ValidationError):
            self.service.upsert(
                self._payload("sheet:004:b", consolidation) | {
                    "collection_local_ref": "A001",
                }
            )

    def test_request_received_stores_plan_without_physical_lines(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-006")
        _, shipment = self.service.upsert(self._payload("sheet:006:a", consolidation))
        self.assertEqual(shipment.planned_consolidation_id, consolidation)
        self.assertFalse(shipment.consolidation_line_ids)

    def test_route_mismatch_is_rejected(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-ROUTE")
        with self.assertRaises(ValidationError):
            self.service.upsert({
                "sync_source_key": "sheet:route:a",
                "planned_consolidation_ref": consolidation.name,
                "transport_mode": "air",
                "direction": "export",
                "origin": {"city": "Paris"},
                "destination": {"city": "Dakar"},
                "client": {"name": self.partner.name},
            })

    def test_incompatible_mode_is_rejected(self):
        consolidation = self._consolidation("SEA-DKR-PAR-2099-001")
        with self.assertRaises(ValidationError):
            self.service.upsert({
                "sync_source_key": "sheet:sea:a",
                "planned_consolidation_ref": consolidation.name,
                "transport_mode": "sea",
                "direction": "export",
                "client": {"name": self.partner.name},
            })
