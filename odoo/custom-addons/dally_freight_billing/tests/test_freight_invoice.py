# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightNativeInvoice(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({
            "name": "Freight Invoice Customer",
            "email": "invoice.freight@example.com",
        })
        self.food = self.env.ref("dally_freight_billing.tariff_family_food")

    def _ready_shipment(self, reference="INV-SYNC-001"):
        shipment = self.env["dally.shipment"].create({
            "partner_id": self.partner.id,
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
            "customer_segment_snapshot": "individual",
            "goods_received_on": "2026-08-21",
            "dossier_fee_eur": 5.0,
            "other_fees_eur": 2.0,
        })
        line = self.env["dally.shipment.package"].create({
            "shipment_id": shipment.id,
            "external_line_key": "%s|A|1" % reference,
            "package_type": "parcel",
            "description": "Café Touba",
            "quantity": 1,
            "unit_weight_kg": 10.0,
            "billing_method": "real",
            "tariff_family_id": self.food.id,
        })
        line.action_apply_freight_tariff()
        return shipment, line

    def test_creates_confirmed_native_order_and_draft_invoice(self):
        shipment, line = self._ready_shipment()
        invoice = shipment.action_prepare_native_freight_invoice()

        self.assertTrue(shipment.sale_order_id)
        self.assertEqual(shipment.sale_order_id.state, "sale")
        self.assertEqual(shipment.sale_order_id.dally_freight_shipment_id, shipment)
        self.assertTrue(shipment.invoice_id)
        self.assertEqual(invoice, shipment.invoice_id)
        self.assertEqual(invoice.state, "draft")
        self.assertEqual(invoice.move_type, "out_invoice")
        self.assertEqual(invoice.dally_freight_shipment_id, shipment)
        self.assertTrue(shipment.billing_locked)

        freight_sale_line = shipment.sale_order_id.order_line.filtered(
            lambda sale_line: sale_line.dally_freight_package_id == line
        )
        self.assertEqual(len(freight_sale_line), 1)
        self.assertAlmostEqual(freight_sale_line.product_uom_qty, 10.0, places=2)
        self.assertAlmostEqual(freight_sale_line.price_unit, 3.5, places=2)
        self.assertAlmostEqual(shipment.freight_amount_eur, 35.0, places=2)
        self.assertAlmostEqual(shipment.billing_total_eur, 42.0, places=2)
        self.assertAlmostEqual(invoice.amount_untaxed, 42.0, places=2)
        self.assertAlmostEqual(invoice.amount_tax, 0.0, places=2)
        self.assertAlmostEqual(invoice.amount_total, 42.0, places=2)

        if "picking_ids" in shipment.sale_order_id._fields:
            self.assertFalse(
                shipment.sale_order_id.picking_ids,
                "Freight billing products are services and must not create stock pickings",
            )

    def test_business_retry_returns_same_invoice(self):
        shipment, _line = self._ready_shipment("INV-SYNC-RETRY")
        first = shipment.action_prepare_native_freight_invoice()
        second = shipment.action_prepare_native_freight_invoice()
        self.assertEqual(first, second)
        self.assertEqual(
            self.env["sale.order"].search_count([
                ("dally_freight_shipment_id", "=", shipment.id)
            ]),
            1,
        )
        self.assertEqual(
            self.env["account.move"].search_count([
                ("dally_freight_shipment_id", "=", shipment.id)
            ]),
            1,
        )

    def test_incomplete_line_blocks_invoice(self):
        shipment = self.env["dally.shipment"].create({
            "partner_id": self.partner.id,
            "external_reference": "INV-INCOMPLETE",
            "transport_mode": "sea",
            "direction": "export",
        })
        self.env["dally.shipment.package"].create({
            "shipment_id": shipment.id,
            "external_line_key": "INV-INCOMPLETE|A|1",
            "package_type": "parcel",
            "description": "Vaisselle",
            "quantity": 1,
            "unit_weight_kg": 5.0,
            "billing_method": "real",
            "tariff_family_id": self.env.ref(
                "dally_freight_billing.tariff_family_non_food"
            ).id,
        })
        with self.assertRaises(UserError):
            shipment.action_prepare_native_freight_invoice()
        self.assertFalse(shipment.sale_order_id)
        self.assertFalse(shipment.invoice_id)

    def test_billing_lock_blocks_cargo_and_fee_rewrite(self):
        shipment, line = self._ready_shipment("INV-LOCK")
        shipment.action_prepare_native_freight_invoice()
        with self.assertRaises(UserError):
            line.write({"unit_weight_kg": 99.0})
        with self.assertRaises(UserError):
            shipment.write({"dossier_fee_eur": 99.0})

    def test_reset_draft_documents_unlocks_for_correction(self):
        shipment, line = self._ready_shipment("INV-RESET")
        invoice = shipment.action_prepare_native_freight_invoice()
        order = shipment.sale_order_id
        self.assertEqual(invoice.state, "draft")

        shipment.action_reset_draft_freight_billing()
        self.assertFalse(invoice.exists())
        self.assertFalse(order.exists())
        self.assertFalse(shipment.invoice_id)
        self.assertFalse(shipment.sale_order_id)
        self.assertFalse(shipment.billing_locked)

        line.write({"unit_weight_kg": 12.0})
        self.assertAlmostEqual(line.total_weight_kg, 12.0, places=2)
