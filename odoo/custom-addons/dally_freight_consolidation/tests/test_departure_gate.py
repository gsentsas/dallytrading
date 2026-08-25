# -*- coding: utf-8 -*-
"""Contrôle paiement avant le départ.

Ces tests exercent le gate de départ au niveau du dossier :
- pas de facture, pas de départ ;
- facture non réglée, pas de départ pour un particulier ;
- facture soldée, départ possible ;
- une consolidation refuse de partir tant qu'un seul dossier bloque.

On garde ``AccountTestInvoicingCommon`` pour bâtir une facture réelle : les
mock-ups sur le résiduel donneraient un test qui passerait localement mais
manquerait la vraie mécanique du gate.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install", "dally_freight")
class TestDepartureGate(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        # AccountTestInvoicingCommon fixe déjà la société courante et les
        # journaux : on part de son `partner_a` pour éviter de recréer une
        # comptabilité complète.
        cls.customer_business = cls.partner_a
        cls.customer_business.company_type = "company"

    def _prepared_shipment(self, reference, segment="business"):
        shipment = self.env["dally.shipment"].create({
            "partner_id": self.customer_business.id,
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
            "customer_segment_snapshot": segment,
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_city": "Paris",
            "destination_location": "CDG",
            "goods_description": "Café",
        })
        self.env["dally.shipment.package"].create({
            "shipment_id": shipment.id,
            "external_line_key": "%s|A|1" % reference,
            "package_type": "parcel",
            "description": "Café 5kg",
            "quantity": 1,
            "unit_weight_kg": 5.0,
            "billing_method": "real",
            "applied_unit_price_eur": 5.0,
        })
        return shipment

    def _consolidation_with(self, shipment):
        consolidation = self.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-GATE-%s" % shipment.external_reference,
            "transport_mode": "air",
            "direction": "export",
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_city": "Paris",
            "destination_location": "CDG",
            "carrier_name": "Air Sénégal",
            "mawb_number": "297-77777777",
            "state": "collecting",
        })
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": shipment.package_ids.id,
            "quantity_loaded": 1,
        })
        return consolidation

    def _basic_invoice(self, shipment, price=100.0):
        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": shipment.partner_id.id,
            "invoice_line_ids": [(0, 0, {
                "name": "Fret DSS→CDG",
                "quantity": 1,
                "price_unit": price,
            })],
        })
        shipment.invoice_id = invoice.id
        return invoice

    def _register_full_payment(self, invoice):
        # Post + register a full payment via the standard wizard.
        wizard = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids,
        ).create({})
        wizard.action_create_payments()

    def test_dossier_sans_facture_bloque_le_depart(self):
        shipment = self._prepared_shipment("NOFACT-1")
        blocker = shipment._departure_blocker()
        self.assertTrue(blocker)
        self.assertIn("facture", blocker.lower())

    def test_facture_non_reglee_bloque_le_depart_pour_particulier(self):
        shipment = self._prepared_shipment("PART-UNPAID-1", segment="individual")
        invoice = self._basic_invoice(shipment)
        invoice.action_post()

        blocker = shipment._departure_blocker()
        self.assertTrue(blocker)
        self.assertIn("réglée", blocker.lower())

    def test_facture_reglee_permet_le_depart(self):
        shipment = self._prepared_shipment("PAID-1")
        invoice = self._basic_invoice(shipment)
        invoice.action_post()
        self._register_full_payment(invoice)
        invoice.invalidate_recordset(["payment_state", "amount_residual"])

        self.assertFalse(shipment._departure_blocker())

    def test_consolidation_refuse_de_partir_si_un_dossier_bloque(self):
        shipment = self._prepared_shipment("BLK-1")
        consolidation = self._consolidation_with(shipment)
        consolidation.action_close_collection()
        # Mettre le dossier à ready (contrôle préparation seulement).
        shipment.write({"state": "request_received"})
        shipment.write({"state": "awaiting_goods"})
        shipment.write({"state": "goods_received"})
        shipment.write({"state": "preparing"})
        shipment.write({"state": "ready"})
        consolidation.action_mark_ready()

        with self.assertRaises(UserError):
            consolidation.action_record_departure()

    def test_derogation_business_permet_le_depart(self):
        shipment = self._prepared_shipment("BIZ-OVR-1", segment="business")
        invoice = self._basic_invoice(shipment)
        invoice.action_post()

        # Sans dérogation, le blocker existe.
        self.assertTrue(shipment._departure_blocker())

        shipment._record_payment_override("Client historique, virement en cours")
        shipment.invalidate_recordset([
            "departure_payment_override_reason",
            "departure_payment_override_user_id",
            "departure_payment_override_on",
            "departure_payment_override_residual",
        ])
        self.assertFalse(shipment._departure_blocker())
