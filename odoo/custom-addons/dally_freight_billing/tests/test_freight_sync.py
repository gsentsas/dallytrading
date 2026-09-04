# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightSyncService(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Sync = self.env["dally.freight.sync.service"]

    def _force_stale_manual_standard_state(self, line):
        line.flush_recordset(["pricing_type_snapshot", "manual_unit_price_eur", "pricing_reason"])
        self.env.cr.execute(
            """
            UPDATE dally_shipment_package
               SET pricing_type_snapshot = 'standard',
                   manual_unit_price_eur = 5.0,
                   pricing_reason = NULL
             WHERE id = %s
            """,
            [line.id],
        )
        line.invalidate_recordset(["pricing_type_snapshot", "manual_unit_price_eur", "pricing_reason"])

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

    def test_tk_guard_uses_internal_elevated_read_only(self):
        """The sync user must never need direct access to tk_shipment_id."""

        class RestrictedShipment:
            _fields = {"tk_shipment_id": object()}

            def __bool__(self):
                return True

            @property
            def tk_shipment_id(self):
                raise AssertionError(
                    "tk_shipment_id must not be read with the caller permissions"
                )

            def sudo(self):
                class ElevatedShipment:
                    tk_shipment_id = False

                return ElevatedShipment()

        self.assertFalse(
            self.Sync._is_tk_managed(RestrictedShipment())
        )

    def test_tk_guard_blocks_operational_projection(self):
        class RestrictedShipment:
            _fields = {"tk_shipment_id": object()}

            def __bool__(self):
                return True

            @property
            def tk_shipment_id(self):
                raise AssertionError(
                    "tk_shipment_id must not be read with the caller permissions"
                )

            def sudo(self):
                class ElevatedShipment:
                    tk_shipment_id = object()

                return ElevatedShipment()

        self.assertTrue(
            self.Sync._is_tk_managed(RestrictedShipment())
        )

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

    def test_existing_shipment_rejects_draft_state_payload(self):
        _data, shipment = self.Sync.upsert(self._payload())
        self.assertEqual(shipment.state, "request_received")
        payload = self._payload(state="draft")
        with self.assertRaises(ValidationError):
            self.Sync.upsert(payload)

    def test_existing_draft_rejection_happens_before_partner_mutation(self):
        _data, shipment = self.Sync.upsert(self._payload())
        partner = shipment.partner_id
        original_name = partner.name
        payload = self._payload(state="draft")
        payload["client"] = dict(payload["client"], name="Client B invalide")
        with self.assertRaises(ValidationError):
            self.Sync.upsert(payload)
        self.assertEqual(shipment.partner_id, partner)
        self.assertEqual(partner.name, original_name)
        self.assertFalse(self.env["res.partner"].search([("name", "=", "Client B invalide")]))

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

    def test_explicit_standard_clears_previous_manual_tariff(self):
        payload = self._payload(lines=[{
            "external_line_key": "A-SYNC-STANDARD-RESET|A|1",
            "description": "Colis negocie",
            "quantity": 1,
            "exact_weight_kg": 10,
            "billing_method": "real",
            "tariff_family_code": "food",
            "manual_unit_price_eur": 5.0,
            "pricing_type": "special",
            "pricing_reason": "Tarif negocie",
        }])
        _data, shipment = self.Sync.upsert(payload)
        line = shipment.package_ids
        self.assertEqual(line.pricing_type_snapshot, "special")
        self.assertAlmostEqual(line.manual_unit_price_eur, 5.0, places=2)
        self.assertEqual(line.pricing_reason, "Tarif negocie")

        payload["lines"][0].pop("manual_unit_price_eur")
        payload["lines"][0].pop("pricing_reason")
        payload["lines"][0]["pricing_type"] = "standard"
        data, shipment = self.Sync.upsert(payload)

        line = shipment.package_ids
        self.assertEqual(data["lines"][0]["pricing_status"], "automatic")
        self.assertEqual(line.pricing_type_snapshot, "standard")
        self.assertFalse(line.manual_unit_price_eur)
        self.assertFalse(line.pricing_reason)

    def test_explicit_standard_clears_stale_manual_price(self):
        _data, shipment = self.Sync.upsert(self._payload(
            external_reference="A-SYNC-STALE-STANDARD",
            lines=[{
                "external_line_key": "A-SYNC-STALE-STANDARD|A|1",
                "description": "Marchandise non precisee",
                "goods_category": "Non Alimentaires",
                "quantity": 1,
                "exact_weight_kg": 4.15,
                "billing_method": "real",
                "tariff_family_code": "non_food",
            }],
        ))
        line = shipment.package_ids
        self._force_stale_manual_standard_state(line)

        data, shipment = self.Sync.upsert(self._payload(
            external_reference="A-SYNC-STALE-STANDARD",
            lines=[{
                "external_line_key": "A-SYNC-STALE-STANDARD|A|1",
                "description": "Marchandise non precisee",
                "goods_category": "Non Alimentaires",
                "quantity": 1,
                "exact_weight_kg": 4.15,
                "billing_method": "real",
                "tariff_family_code": "non_food",
                "pricing_type": "standard",
            }],
        ))

        line = shipment.package_ids
        self.assertEqual(data["lines"][0]["pricing_status"], "automatic")
        self.assertEqual(line.pricing_type_snapshot, "standard")
        self.assertFalse(line.manual_unit_price_eur)
        self.assertFalse(line.pricing_reason)

    def test_explicit_standard_without_rule_clears_applied_manual_tariff(self):
        payload = self._payload(
            external_reference="M-SYNC-STANDARD-NO-RULE",
            transport_mode="sea",
            lines=[{
                "external_line_key": "M-SYNC-STANDARD-NO-RULE|A|1",
                "description": "Colis negocie maritime",
                "quantity": 1,
                "exact_weight_kg": 4,
                "unit_volume_cbm": 0.5,
                "billing_method": "volumetric",
                "tariff_family_code": "non_food",
                "manual_unit_price_eur": 5.0,
                "pricing_type": "special",
                "pricing_reason": "Tarif negocie",
            }],
        )
        _data, shipment = self.Sync.upsert(payload)
        line = shipment.package_ids
        line.write({"volumetric_ratio_kg_cbm": 10.0})

        self.assertAlmostEqual(line.manual_unit_price_eur, 5.0, places=2)
        self.assertAlmostEqual(line.applied_unit_price_eur, 5.0, places=2)
        self.assertTrue(line.tariff_applied_on)
        self.assertAlmostEqual(line.volumetric_ratio_kg_cbm, 10.0, places=2)
        self.assertAlmostEqual(line.billable_weight_kg, 5.0, places=2)
        self.assertAlmostEqual(line.transport_amount_eur, 25.0, places=2)

        payload["lines"][0].pop("manual_unit_price_eur")
        payload["lines"][0].pop("pricing_reason")
        payload["lines"][0]["pricing_type"] = "standard"
        data, shipment = self.Sync.upsert(payload)

        line = shipment.package_ids
        self.assertEqual(data["lines"][0]["pricing_status"], "manual_required")
        self.assertEqual(line.pricing_type_snapshot, "standard")
        self.assertFalse(line.manual_unit_price_eur)
        self.assertFalse(line.pricing_reason)
        self.assertFalse(line.applied_unit_price_eur)
        self.assertFalse(line.tariff_rule_id)
        self.assertFalse(line.tariff_applied_on)
        self.assertFalse(line.volumetric_ratio_kg_cbm)
        self.assertAlmostEqual(line.billable_weight_kg, 4.0, places=2)
        self.assertAlmostEqual(line.transport_amount_eur, 0.0, places=2)

    def test_special_manual_tariff_still_requires_reason(self):
        payload = self._payload(lines=[{
            "external_line_key": "A-SYNC-SPECIAL-NO-REASON|A|1",
            "description": "Colis sans motif",
            "quantity": 1,
            "exact_weight_kg": 10,
            "billing_method": "real",
            "tariff_family_code": "food",
            "manual_unit_price_eur": 5.0,
            "pricing_type": "special",
            "pricing_reason": None,
        }])
        with self.assertRaisesRegex(ValidationError, "manual freight price requires a reason"):
            self.Sync.upsert(payload)

    def test_valid_special_manual_tariff_is_preserved(self):
        payload = self._payload(lines=[{
            "external_line_key": "A-SYNC-SPECIAL-VALID|A|1",
            "description": "Colis negocie",
            "quantity": 1,
            "exact_weight_kg": 10,
            "billing_method": "real",
            "tariff_family_code": "food",
            "manual_unit_price_eur": 5.0,
            "pricing_type": "special",
            "pricing_reason": "Tarif negocie",
        }])
        data, shipment = self.Sync.upsert(payload)
        line = shipment.package_ids
        self.assertEqual(data["lines"][0]["pricing_status"], "manual")
        self.assertEqual(line.pricing_type_snapshot, "special")
        self.assertAlmostEqual(line.manual_unit_price_eur, 5.0, places=2)
        self.assertEqual(line.pricing_reason, "Tarif negocie")

    def test_standard_sync_is_idempotent_after_manual_reset(self):
        payload = self._payload(
            external_reference="A-SYNC-STANDARD-IDEMPOTENT",
            lines=[{
                "external_line_key": "A-SYNC-STANDARD-IDEMPOTENT|A|1",
                "description": "Colis standard",
                "quantity": 1,
                "exact_weight_kg": 10,
                "billing_method": "real",
                "tariff_family_code": "food",
                "pricing_type": "standard",
            }],
        )
        _data, shipment = self.Sync.upsert(payload)
        line = shipment.package_ids
        self._force_stale_manual_standard_state(line)

        self.Sync.upsert(payload)
        self.Sync.upsert(payload)

        self.assertEqual(line.pricing_type_snapshot, "standard")
        self.assertFalse(line.manual_unit_price_eur)
        self.assertFalse(line.pricing_reason)

    def test_legacy_payload_without_pricing_type_preserves_manual_tariff(self):
        payload = self._payload(lines=[{
            "external_line_key": "A-SYNC-LEGACY-MANUAL|A|1",
            "description": "Colis legacy",
            "quantity": 1,
            "exact_weight_kg": 10,
            "billing_method": "real",
            "tariff_family_code": "food",
            "manual_unit_price_eur": 5.0,
            "pricing_type": "special",
            "pricing_reason": "Tarif legacy",
        }])
        _data, shipment = self.Sync.upsert(payload)
        line = shipment.package_ids

        legacy = self._payload(lines=[{
            "external_line_key": "A-SYNC-LEGACY-MANUAL|A|1",
            "description": "Colis legacy",
            "quantity": 1,
            "exact_weight_kg": 10,
            "billing_method": "real",
            "tariff_family_code": "food",
        }])
        self.Sync.upsert(legacy)

        self.assertEqual(line.pricing_type_snapshot, "special")
        self.assertAlmostEqual(line.manual_unit_price_eur, 5.0, places=2)
        self.assertEqual(line.pricing_reason, "Tarif legacy")

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
