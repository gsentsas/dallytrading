# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightLockedSync(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Sync = self.env["dally.freight.sync.service"]

    def _payload(self):
        return {
            "external_reference": "LOCKED-SYNC-001",
            "transport_mode": "air",
            "direction": "export",
            "source": "google_sheets",
            "goods_received_on": "2026-08-21",
            "customer_segment": "individual",
            "client": {
                "name": "Locked Sync Customer",
                "email": "locked.sync@example.com",
                "phone": "+221 77 123 00 00",
            },
            "lines": [{
                "external_line_key": "LOCKED-SYNC-001|A|1",
                "description": "Café Touba",
                "quantity": 1,
                "exact_weight_kg": 10.0,
                "billing_method": "real",
                "tariff_family_code": "food",
            }],
        }

    def test_identical_retry_after_draft_invoice_is_allowed_without_repricing(self):
        payload = self._payload()
        _data, shipment = self.Sync.upsert(payload)
        line = shipment.package_ids
        self.assertAlmostEqual(line.applied_unit_price_eur, 3.5, places=2)
        original_rule = line.tariff_rule_id
        invoice = shipment.action_prepare_native_freight_invoice()
        self.assertEqual(invoice.state, "draft")
        self.assertTrue(shipment.billing_locked)

        # Change the live grid after the invoice snapshot. A harmless replay must
        # not look up this new price and must not fail because history is locked.
        original_rule.active = False
        self.env["dally.freight.tariff.rule"].create({
            "name": "Future replacement test tariff",
            "transport_mode": "air",
            "family_id": line.tariff_family_id.id,
            "customer_segment": "all",
            "price_per_kg_eur": 99.0,
            "volumetric_ratio_kg_cbm": 167.0,
            "date_from": "2026-08-21",
            "currency_id": self.env.ref("base.EUR").id,
        })

        replay, same_shipment = self.Sync.upsert(payload)
        self.assertEqual(same_shipment, shipment)
        self.assertEqual(replay["lines"][0]["pricing_status"], "locked")
        self.assertAlmostEqual(line.applied_unit_price_eur, 3.5, places=2)
        self.assertEqual(line.tariff_rule_id, original_rule)
        self.assertEqual(shipment.invoice_id, invoice)
        self.assertEqual(
            self.env["account.move"].search_count([
                ("dally_freight_shipment_id", "=", shipment.id)
            ]),
            1,
        )

    def test_real_change_after_draft_invoice_is_rejected(self):
        payload = self._payload()
        _data, shipment = self.Sync.upsert(payload)
        shipment.action_prepare_native_freight_invoice()

        changed = self._payload()
        changed["lines"][0]["exact_weight_kg"] = 12.0
        with self.assertRaises(UserError):
            self.Sync.upsert(changed)

        self.assertAlmostEqual(shipment.package_ids.total_weight_kg, 10.0, places=2)
        self.assertAlmostEqual(shipment.package_ids.applied_unit_price_eur, 3.5, places=2)
