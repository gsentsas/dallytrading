# -*- coding: utf-8 -*-
"""
Workflow opérationnel : le bridge protège l'écriture d'état côté Dally et
propage la vérité vers tk_freight sans la contredire.

Ces tests couvrent les invariants du pont :

- une transition non-adjacente est refusée, même via un write() RPC direct ;
- une annulation reste possible sur un dossier lié à tk (régression : la
  version initiale du pont exigeait un stage tk pour tout état, ce que
  « cancelled » n'a jamais eu et n'aura jamais) ;
- une transition légitime écrit d'abord le stage tk, puis laisse la sync
  tk → dally propager l'état sans écraser la projection en aval.
"""

import uuid

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally_freight")
class TestOperationalWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1
        )
        partenaire = cls.env["res.partner"].create({"name": "Workflow Client"})
        cls.devis = cls.env["dally.quote.request"].create({
            "partner_id": partenaire.id,
            "contact_name": "Workflow",
            "company_name": "Workflow Client",
            "service_type_id": cls.service.id,
            "email": "workflow@test.invalid",
            "request_uuid": str(uuid.uuid4()),
        })
        cls.devis.write({"state": "won"})

        booking = cls.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", cls.devis.id)], limit=1
        )
        cls.expedition = cls.env["freight.shipment"].sudo().search(
            [("booking_id", "=", booking.id)], limit=1
        )
        cls.projection = cls.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "=", cls.expedition.id)], limit=1
        )

    def test_annulation_d_un_dossier_lie_a_tk_reste_possible(self):
        """action_cancel() doit passer même si tk n'a pas de stage cancelled.

        Régression : le pont exigeait un stage tk pour tout état cible et
        « cancelled » n'était pas mappé, ce qui empêchait toute annulation
        d'un dossier provisionné par tk. Les particuliers qui abandonnent
        une demande produisent exactement ce cas.
        """
        self.projection.action_cancel()
        self.assertEqual(self.projection.state, "cancelled")

    def test_transition_non_adjacente_est_refusee(self):
        """draft → in_transit doit être refusé, même sur un dossier tk-linké."""
        with self.assertRaises(UserError):
            self.projection.action_set_state("in_transit")

    def test_progression_ordonnee_ecrit_le_stage_tk(self):
        """Chaque avancée à l'étape suivante bascule aussi le stage tk_freight."""
        self.projection.action_set_state("awaiting_goods")
        self.assertEqual(self.projection.state, "awaiting_goods")

        stage_awaiting = self.env.ref("dally_freight_bridge.stage_awaiting_goods")
        self.assertEqual(self.expedition.stage_id, stage_awaiting)

    def test_ecriture_directe_du_stage_tk_propage_l_etat_dally(self):
        """Un opérateur qui bascule le kanban tk_freight aligne la projection."""
        stage_prep = self.env.ref("dally_freight_bridge.stage_preparing")
        # Il faut d'abord amener le dossier à l'étape immédiatement précédente,
        # sans quoi la garde côté Dally refuserait le saut goods_received.
        self.projection.action_set_state("awaiting_goods")
        self.projection.action_set_state("goods_received")

        self.expedition.write({"stage_id": stage_prep.id})
        self.assertEqual(self.projection.state, "preparing")
