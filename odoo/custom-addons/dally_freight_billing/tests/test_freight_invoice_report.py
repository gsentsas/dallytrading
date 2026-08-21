# -*- coding: utf-8 -*-

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightInvoiceReport(TransactionCase):

    def setUp(self):
        super().setUp()

        self.partner = self.env["res.partner"].create({
            "name": "Client Facture Fret",
            "email": "facture@example.com",
        })

        family = self.env.ref(
            "dally_freight_billing.tariff_family_non_food"
        )

        self.shipment = self.env["dally.shipment"].create({
            "partner_id": self.partner.id,
            "external_reference": "REPORT-001",
            "transport_mode": "air",
            "direction": "export",
            "customer_segment_snapshot": "individual",
            "goods_received_on": "2026-08-21",
        })

        self.package = self.env[
            "dally.shipment.package"
        ].create({
            "shipment_id": self.shipment.id,
            "external_line_key": "REPORT-001|A|1",
            "package_type": "parcel",
            "description": "Habits",
            "quantity": 1,
            "unit_weight_kg": 4.6,
            "billing_method": "real",
            "tariff_family_id": family.id,
        })

        self.package.action_apply_freight_tariff()

        self.invoice = (
            self.shipment
            .action_prepare_native_freight_invoice()
        )

        self.env["dally.freight.collection"].create({
            "external_payment_key": "REPORT-001|P|1",
            "shipment_id": self.shipment.id,
            "amount": 10.0,
            "currency_id": self.invoice.currency_id.id,
            "payment_date": "2026-08-21",
            "source_method": "wave",
            "source": "backoffice",
            "state": "pending",
        })

    def test_report_context_is_french_and_freight_specific(self):
        context = self.invoice.dally_freight_report_context()

        self.assertEqual(
            context["document_title"],
            "FACTURE - BROUILLON",
        )

        self.assertEqual(
            context["dossier_reference"],
            "REPORT-001",
        )

        self.assertEqual(
            context["mode_label"],
            "Fret aérien",
        )

        self.assertEqual(
            len(context["freight_lines"]),
            1,
        )

        self.assertEqual(
            context["freight_lines"][0]["designation"],
            "Fret aérien - Habits",
        )

        self.assertAlmostEqual(
            context["freight_lines"][0]["quantity"],
            4.6,
            places=2,
        )

        self.assertAlmostEqual(
            context["freight_lines"][0]["unit_price"],
            5.0,
            places=2,
        )

        self.assertEqual(
            context["collections"][0]["method_label"],
            "Wave",
        )

        self.assertEqual(
            context["collections"][0]["state_label"],
            "Enregistré",
        )

        self.assertEqual(
            context["payment_summary_label"],
            "Acompte enregistré",
        )

        self.assertEqual(
            context["balance_label"],
            "Reste à payer (indicatif)",
        )

        self.assertAlmostEqual(
            context["received_equivalent"],
            10.0,
            places=2,
        )

        self.assertAlmostEqual(
            context["balance_due"],
            13.0,
            places=2,
        )

        xof = self.env["res.currency"].search([
            ("name", "=", "XOF"),
        ], limit=1)

        self.assertTrue(xof)

        self.assertEqual(
            self.invoice.dally_freight_format_amount(
                15088,
                xof,
            ),
            "15 088 FCFA",
        )

    def test_report_action_is_available_for_account_moves(self):
        report = self.env.ref(
            "dally_freight_billing."
            "action_report_dally_freight_invoice"
        )

        self.assertEqual(
            report.model,
            "account.move",
        )

        self.assertEqual(
            report.report_type,
            "qweb-pdf",
        )

        self.assertEqual(
            report.report_name,
            "dally_freight_billing."
            "report_freight_invoice",
        )


    def test_report_context_without_payment_is_unpaid(self):
        self.env["dally.freight.collection"].search([
            ("shipment_id", "=", self.shipment.id),
        ]).unlink()

        context = self.invoice.dally_freight_report_context()

        self.assertFalse(context["collections"])

        self.assertEqual(
            context["payment_summary_label"],
            "Non réglée",
        )

        self.assertAlmostEqual(
            context["balance_due"],
            self.invoice.amount_total,
            places=2,
        )
