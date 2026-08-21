# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightSyncService(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Sync = self.env["dally.freight.sync.service"]

    def _payload(self, **overrides):
        payload = {
            "external_reference": "A-SYNC-001",
            "transport_mode": "air",
            "direction": "export",
            "source": "google_sheets",
            "goods_received_on": "2026-08-21",
            "customer_segment": "individual",
            "client": {
                "name": "Awa Ndiaye",
                "email": "awa.sync@example.com",
                "phone": "+221 77 123 45 67",
                "address": "Dakar",
            },
            "origin": {"country_code": "SN", "city": "Dakar"},
            "destination": {"country_code": "FR", "city": "Paris"},
            "lines": [
                {
                    "external_line_key": "A-SYNC-001|A|1",
                    "description": "Pâte d'arachide",
                    "goods_category": "Alimentaires",
                    "quantity": 1,
                    "announced_weight_kg": 10.0,
                    "exact_weight_kg": 9.9,
                    "billing_method": "real",
                    "tariff_family_code": "food",
                    "customs_value_xof": 25000,
                }
            ],
        }
        payload.update(overrides)
        return payload

    def test_creates_customer_shipment_and_priced_line(self):
        data, shipment = self.Sync.upsert(self._payload())

        self.assertTrue(data["partner_created"])
        self.assertTrue(data["shipment_created"])
        self.assertEqual(shipment.external_reference, "A-SYNC-001")
        self.assertEqual(shipment.transport_mode, "air")
        self.assertEqual(shipment.direction, "export")
        self.assertEqual(shipment.partner_id.email, "awa.sync@example.com")
        self.assertEqual(shipment.origin_city, "Dakar")
        self.assertEqual(shipment.destination_city, "Paris")
        self.assertEqual(shipment.state, "request_received")

        line = shipment.package_ids
        self.assertEqual(len(line), 1)
        self.assertAlmostEqual(line.total_weight_kg, 9.9, places=3)
        self.assertAlmostEqual(line.applied_unit_price_eur, 3.5, places=2)
        self.assertAlmostEqual(line.transport_amount_eur, 34.65, places=2)
        self.assertEqual(data["lines"][0]["pricing_status"], "automatic")

    def test_same_business_keys_are_idempotent_with_new_http_request(self):
        first, first_shipment = self.Sync.upsert(self._payload())
        second_payload = self._payload()
        second_payload["lines"][0]["exact_weight_kg"] = 12.0
        second, second_shipment = self.Sync.upsert(second_payload)

        self.assertEqual(first_shipment, second_shipment)
        self.assertFalse(second["shipment_created"])
        self.assertEqual(
            self.env["dally.shipment"].search_count([
                ("external_reference", "=", "A-SYNC-001")
            ]),
            1,
        )
        self.assertEqual(
            self.env["dally.shipment.package"].search_count([
                ("external_line_key", "=", "A-SYNC-001|A|1")
            ]),
            1,
        )
        self.assertAlmostEqual(second_shipment.package_ids.total_weight_kg, 12.0, places=3)
        self.assertAlmostEqual(second_shipment.package_ids.transport_amount_eur, 42.0, places=2)

    def test_total_excel_weight_is_divided_by_quantity(self):
        payload = self._payload()
        payload["lines"][0].update({
            "external_line_key": "A-SYNC-001|A|QTY",
            "quantity": 4,
            "exact_weight_kg": 79.9,
        })
        _data, shipment = self.Sync.upsert(payload)
        line = shipment.package_ids.filtered(
            lambda item: item.external_line_key == "A-SYNC-001|A|QTY"
        )
        self.assertAlmostEqual(line.unit_weight_kg, 19.975, places=3)
        self.assertAlmostEqual(line.total_weight_kg, 79.9, places=3)

    def test_formatted_phone_reuses_existing_partner(self):
        existing = self.env["res.partner"].create({
            "name": "Existing Customer",
            "phone": "06 12 34 56 78",
        })
        payload = self._payload(
            external_reference="A-SYNC-PHONE",
            client={
                "name": "Corrected Customer Name",
                "phone": "+33 6 12 34 56 78",
            },
            lines=[],
        )
        data, shipment = self.Sync.upsert(payload)
        self.assertFalse(data["partner_created"])
        self.assertEqual(shipment.partner_id, existing)
        self.assertEqual(existing.name, "Corrected Customer Name")

    def test_sea_non_food_syncs_but_requires_manual_tariff(self):
        payload = self._payload(
            external_reference="M-SYNC-001",
            transport_mode="sea",
            lines=[{
                "external_line_key": "M-SYNC-001|A|1",
                "description": "Vaisselle",
                "quantity": 1,
                "exact_weight_kg": 6.05,
                "billing_method": "real",
                "tariff_family_code": "non_food",
            }],
        )
        data, shipment = self.Sync.upsert(payload)
        self.assertEqual(data["lines"][0]["pricing_status"], "manual_required")
        self.assertFalse(shipment.package_ids.applied_unit_price_eur)
        self.assertAlmostEqual(shipment.package_ids.total_weight_kg, 6.05, places=2)

    def test_historical_manual_tariff_is_snapshotted(self):
        payload = self._payload(
            external_reference="M-SYNC-HIST",
            transport_mode="sea",
            source="legacy_xlsx",
            lines=[{
                "external_line_key": "M-SYNC-HIST|A|1",
                "description": "Ancien dossier",
                "quantity": 1,
                "exact_weight_kg": 10,
                "billing_method": "real",
                "tariff_family_code": "food",
                "manual_unit_price_eur": 2.0,
                "pricing_type": "special",
                "pricing_reason": "Tarif historique conservé lors de la fusion.",
            }],
        )
        data, shipment = self.Sync.upsert(payload)
        line = shipment.package_ids
        self.assertEqual(data["lines"][0]["pricing_status"], "manual")
        self.assertAlmostEqual(line.applied_unit_price_eur, 2.0, places=2)
        self.assertAlmostEqual(line.transport_amount_eur, 20.0, places=2)
        self.assertFalse(line.tariff_rule_id)

    def test_partial_dossier_can_sync_before_weight_exists(self):
        payload = self._payload(
            external_reference="A-SYNC-PARTIAL",
            lines=[{
                "external_line_key": "A-SYNC-PARTIAL|A|1",
                "description": "Colis annoncé",
                "quantity": 1,
                "tariff_family_code": "food",
            }],
        )
        data, shipment = self.Sync.upsert(payload)
        self.assertEqual(data["lines"][0]["pricing_status"], "pending_weight")
        self.assertEqual(shipment.package_ids.total_weight_kg, 0.0)
        self.assertFalse(shipment.package_ids.applied_unit_price_eur)

    def test_customer_without_email_or_phone_is_not_matched_by_name(self):
        self.env["res.partner"].create({"name": "Homonyme"})
        payload = self._payload(
            external_reference="A-SYNC-NO-CONTACT",
            client={"name": "Homonyme", "address": "Dakar"},
            lines=[],
        )
        data, shipment = self.Sync.upsert(payload)
        self.assertTrue(data["partner_created"])
        self.assertEqual(shipment.partner_id.name, "Homonyme")
        self.assertEqual(
            self.env["res.partner"].search_count([("name", "=", "Homonyme")]),
            2,
            "Safe duplication is preferable to linking two homonyms",
        )
