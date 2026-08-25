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
