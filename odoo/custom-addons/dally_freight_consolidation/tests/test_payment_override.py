# -*- coding: utf-8 -*-
"""Dérogation Manager au contrôle de paiement.

Trois garde-fous à couvrir :
- seul un Manager peut accorder la dérogation ;
- elle est interdite pour un particulier ;
- la trace est immuable (aucune écriture d'un client applicatif, sudo-only).
"""

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install", "dally_freight")
class TestPaymentOverride(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Le test doit pouvoir instancier des shipments et poster des factures.
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

    def _shipment(self, segment):
        partner = self.env["res.partner"].create({
            "name": "Override %s" % segment,
            "company_type": "company" if segment == "business" else "person",
        })
        shipment = self.env["dally.shipment"].create({
            "partner_id": partner.id,
            "external_reference": "OVR-%s" % segment,
            "transport_mode": "air",
            "direction": "export",
            "customer_segment_snapshot": segment,
        })
        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "invoice_line_ids": [(0, 0, {
                "name": "Fret", "quantity": 1, "price_unit": 250.0,
            })],
        })
        invoice.action_post()
        shipment.invoice_id = invoice.id
        return shipment

    def test_derogation_reservee_au_manager(self):
        shipment = self._shipment("business")
        # Retire le rôle manager pour ce test.
        self.env.user.group_ids -= self.env.ref("dally_core.group_dally_manager")
        with self.assertRaises(AccessError):
            shipment._record_payment_override("Test")

    def test_non_manager_peut_evaluer_le_depart_blocker(self):
        shipment = self._shipment("business")
        self.env.user.group_ids -= self.env.ref("dally_core.group_dally_manager")
        self.assertTrue(shipment._departure_blocker())

    def test_derogation_interdite_pour_un_particulier(self):
        shipment = self._shipment("individual")
        with self.assertRaises(UserError):
            shipment._record_payment_override("Cadeau")

    def test_raison_obligatoire(self):
        shipment = self._shipment("business")
        with self.assertRaises(UserError):
            shipment._record_payment_override("   ")

    def test_trace_est_immuable_pour_un_appelant_normal(self):
        shipment = self._shipment("business")
        shipment._record_payment_override("Client VIP")
        with self.assertRaises(AccessError):
            shipment.write({"departure_payment_override_reason": "hacked"})

    def test_override_est_invalidee_si_la_facture_change(self):
        shipment = self._shipment("business")
        invoice_a = shipment.invoice_id
        shipment._record_payment_override("Crédit validé")
        self.assertEqual(shipment.departure_payment_override_invoice_id, invoice_a)
        invoice_b = self.env["account.move"].create({
            "move_type": "out_invoice", "partner_id": shipment.partner_id.id,
            "invoice_line_ids": [(0, 0, {"name": "Fret B", "quantity": 1, "price_unit": 300.0})],
        })
        invoice_b.action_post()
        shipment.write({"invoice_id": invoice_b.id})
        self.assertFalse(shipment.departure_payment_override_invoice_id)
        self.assertTrue(shipment._departure_blocker())
    def test_champs_override_proteges_avec_invoice_id_meme(self):
        shipment = self._shipment("business")
        invoice_a = shipment.invoice_id
        shipment._record_payment_override("Origine")
        with self.assertRaises(AccessError):
            shipment.write({"invoice_id": invoice_a.id, "departure_payment_override_reason": "forged"})
        self.assertEqual(shipment.departure_payment_override_reason, "Origine")
        self.assertEqual(shipment.invoice_id, invoice_a)

    def test_champs_override_proteges_avant_changement_invoice(self):
        shipment = self._shipment("business")
        invoice_b = self.env["account.move"].create({
            "move_type": "out_invoice", "partner_id": shipment.partner_id.id,
            "invoice_line_ids": [(0, 0, {"name": "Fret B", "quantity": 1, "price_unit": 300.0})],
        })
        invoice_b.action_post()
        shipment._record_payment_override("Origine")
        with self.assertRaises(AccessError):
            shipment.write({"invoice_id": invoice_b.id, "departure_payment_override_reason": "forged"})
        self.assertEqual(shipment.invoice_id, shipment.departure_payment_override_invoice_id)
        self.assertEqual(shipment.departure_payment_override_reason, "Origine")

    def test_override_conservee_si_la_meme_facture_est_recrite(self):
        shipment = self._shipment("business")
        invoice = shipment.invoice_id
        shipment._record_payment_override("Crédit validé")
        shipment.write({"invoice_id": invoice.id})
        self.assertEqual(shipment.departure_payment_override_invoice_id, invoice)
        self.assertEqual(shipment.departure_payment_override_reason, "Crédit validé")

    def test_override_invalidee_si_la_facture_est_effacee(self):
        shipment = self._shipment("business")
        shipment._record_payment_override("Crédit validé")
        shipment.write({"invoice_id": False})
        self.assertFalse(shipment.departure_payment_override_invoice_id)
        self.assertFalse(shipment.departure_payment_override_reason)
