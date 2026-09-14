# -*- coding: utf-8 -*-
"""Le smart button Factures doit montrer toutes les pieces du depart."""

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install", "dally_freight")
class TestConsolidationInvoiceButton(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_logistics")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")
        cls.setup_other_currency("EUR")
        cls.Sync = cls.env["dally.freight.sync.service"]
        cls.consolidation = cls.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-2099-BTN",
            "transport_mode": "air",
            "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris",
            "destination_location": "CDG",
            "state": "collecting",
        })

    def _line(self, reference, index, weight):
        return {
            "external_line_key": "%s|A|%s" % (reference, index),
            "description": "Article %s" % index,
            "goods_category": "Alimentaires",
            "quantity": 1,
            "exact_weight_kg": weight,
            "billing_method": "real",
            "tariff_family_code": "food",
        }

    def _payload(self, reference, customer_index, line):
        return {
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
            "source": "google_sheets",
            "goods_received_on": "2026-09-14",
            "customer_segment": "individual",
            "client": {
                "name": "Client bouton %s" % customer_index,
                "email": "invoice-button-%s@example.invalid" % customer_index,
            },
            "origin": {"country_code": "SN", "city": "Dakar", "location": "DSS"},
            "destination": {"country_code": "FR", "city": "Paris", "location": "CDG"},
            "lines": [line],
        }

    def _load(self, package):
        return self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": self.consolidation.id,
            "package_id": package.id,
            "quantity_loaded": package.quantity,
        })

    def test_button_shows_four_primary_invoices_and_the_supplement(self):
        shipments = []
        primary_invoices = self.env["account.move"]
        for index in range(1, 5):
            reference = "BTN-INV-%03d" % index
            _data, shipment = self.Sync.upsert(self._payload(
                reference, index, self._line(reference, 1, 10.0 + index)
            ))
            shipment.write({
                "origin_city": "Dakar",
                "origin_location": "DSS",
                "destination_city": "Paris",
                "destination_location": "CDG",
            })
            self._load(shipment.package_ids)
            invoice = shipment.action_prepare_native_freight_invoice()
            invoice.action_post()
            shipments.append(shipment)
            primary_invoices |= invoice

        # Charge le cache AVANT le complément : la création de celui-ci doit
        # invalider le compteur et la liste sans invalidate_recordset() manuel.
        self.assertEqual(self.consolidation.invoice_count, 4)
        self.assertEqual(set(self.consolidation.invoice_ids.ids), set(primary_invoices.ids))

        target = shipments[2]
        reference = "BTN-INV-003"
        _data, same = self.Sync.upsert(self._payload(
            reference, 3, self._line(reference, 2, 6.0)
        ))
        self.assertEqual(same, target)
        late_package = same.package_ids.filtered(
            lambda package: package.external_line_key == "%s|A|2" % reference
        )
        self.assertEqual(len(late_package), 1)
        self._load(late_package)

        supplement, created, kind = same._prepare_freight_invoice()
        self.assertTrue(created)
        self.assertEqual(kind, "supplement")
        supplement.action_post()

        expected = set(primary_invoices.ids + supplement.ids)
        self.assertEqual(self.consolidation.invoice_count, 5)
        self.assertEqual(set(self.consolidation.invoice_ids.ids), expected)

        action = self.consolidation.action_view_invoices()
        self.assertEqual(action["res_model"], "account.move")
        self.assertEqual(action["domain"][0][:2], ("id", "in"))
        self.assertEqual(set(action["domain"][0][2]), expected)
