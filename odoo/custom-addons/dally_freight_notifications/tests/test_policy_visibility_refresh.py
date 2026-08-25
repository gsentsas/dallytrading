# -*- coding: utf-8 -*-
"""Régression : le drapeau portail stocké suit le cycle de vie des politiques."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_freight.tests.common import set_shipment_state


@tagged("post_install", "-at_install", "dally")
class TestPolicyVisibilityRefresh(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Policy = self.env["dally.freight.state.policy"]
        self.client = self.env["res.partner"].create({
            "name": "Client visibilité politique",
            "email": "visibility-policy@example.invalid",
        })
        self.service = self.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1
        )

    def _shipment(self, state):
        shipment = self.env["dally.shipment"].create({
            "partner_id": self.client.id,
            "service_type_id": self.service.id,
            "transport_mode": "sea",
        })
        # On teste la politique de visibilité, pas la mécanique de transition ;
        # on utilise donc l'helper de setup qui court-circuite la garde d'état.
        set_shipment_state(shipment, state)
        return shipment

    def test_creating_policy_refreshes_existing_shipment(self):
        """Reproduit l'ordre d'installation : champ d'abord, politique ensuite."""
        policy = self.Policy._dally_policy_for("customs")
        policy.unlink()

        shipment = self._shipment("customs")
        shipment.invalidate_recordset(["dally_portal_visible"])
        self.assertFalse(shipment.dally_portal_visible)

        self.Policy.create({
            "state": "customs",
            "customer_label": "En douane — régression",
            "visible_in_portal": True,
            "visible_in_tracking": True,
            "notify_customer": False,
        })

        shipment.invalidate_recordset(["dally_portal_visible"])
        self.assertTrue(shipment.dally_portal_visible)

    def test_unlinking_policy_hides_existing_shipment(self):
        shipment = self._shipment("in_transit")
        shipment.invalidate_recordset(["dally_portal_visible"])
        self.assertTrue(shipment.dally_portal_visible)

        self.Policy._dally_policy_for("in_transit").unlink()

        shipment.invalidate_recordset(["dally_portal_visible"])
        self.assertFalse(shipment.dally_portal_visible)

    def test_moving_policy_refreshes_old_and_new_states(self):
        """Le déplacement d'une ligne ne doit laisser aucun drapeau périmé."""
        # Libère `preparing` pour pouvoir y déplacer la politique `ready`.
        self.Policy._dally_policy_for("preparing").unlink()

        old_shipment = self._shipment("ready")
        new_shipment = self._shipment("preparing")
        old_shipment.invalidate_recordset(["dally_portal_visible"])
        new_shipment.invalidate_recordset(["dally_portal_visible"])
        self.assertTrue(old_shipment.dally_portal_visible)
        self.assertFalse(new_shipment.dally_portal_visible)

        self.Policy._dally_policy_for("ready").write({"state": "preparing"})

        old_shipment.invalidate_recordset(["dally_portal_visible"])
        new_shipment.invalidate_recordset(["dally_portal_visible"])
        self.assertFalse(old_shipment.dally_portal_visible)
        self.assertTrue(new_shipment.dally_portal_visible)
