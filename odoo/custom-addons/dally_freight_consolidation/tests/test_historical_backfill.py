# -*- coding: utf-8 -*-
"""Backfill du premier départ historique.

L'assistant construit un dry-run puis, sur confirmation Manager, matérialise
la consolidation historique sans envoyer de notification client. On teste
donc trois invariants :
- la prévisualisation ne modifie AUCUNE donnée ;
- la confirmation est réservée aux Managers ;
- la matérialisation est idempotente (relancer ne recrée pas de doublons).
"""

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import ConsolidationCommon


@tagged("post_install", "-at_install", "dally_freight")
class TestHistoricalBackfill(ConsolidationCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")

        cls.historical = cls.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-2026-HIST",
            "transport_mode": "air",
            "direction": "export",
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_city": "Paris",
            "destination_location": "CDG",
            "carrier_name": "Air France",
            "mawb_number": "057-98765432",
            "state": "collecting",
        })
        cls.past_a = cls._shipment(reference="HIST-A")
        cls.past_a.write({"goods_received_on": "2026-08-01"})
        cls.past_b = cls._shipment(reference="HIST-B")
        cls.past_b.write({"goods_received_on": "2026-08-05"})

    def _wizard(self):
        return self.env["dally.consolidation.backfill.wizard"].create({
            "consolidation_id": self.historical.id,
            "cutoff_date": "2026-08-25",
        })

    def test_previsualisation_ne_modifie_aucune_donnee(self):
        packages_before = self.past_a.package_ids.consolidation_line_ids
        wizard = self._wizard()
        wizard.action_preview()

        self.assertTrue(wizard.candidate_line_ids)
        self.assertEqual(self.historical.state, "collecting")
        self.assertFalse(self.historical.line_ids)
        self.assertEqual(self.past_a.package_ids.consolidation_line_ids, packages_before)

    def test_confirmation_reservee_au_manager(self):
        wizard = self._wizard()
        wizard.action_preview()
        wizard.candidate_line_ids.write({"include": True})

        # On enlève temporairement le groupe manager de l'utilisateur.
        self.env.user.group_ids -= self.env.ref("dally_core.group_dally_manager")
        with self.assertRaises(AccessError):
            wizard.action_confirm()

    def test_backfill_marque_les_dossiers_departed_sans_notification(self):
        wizard = self._wizard()
        wizard.action_preview()
        wizard.candidate_line_ids.write({"include": True})

        notifications_before = self.env["dally.shipment.notification"].search_count([
            ("shipment_id", "in", (self.past_a + self.past_b).ids),
        ])

        wizard.action_confirm()

        self.assertEqual(self.historical.state, "departed")
        self.assertEqual(self.past_a.state, "departed")
        self.assertEqual(self.past_b.state, "departed")

        notifications_after = self.env["dally.shipment.notification"].search_count([
            ("shipment_id", "in", (self.past_a + self.past_b).ids),
        ])
        self.assertEqual(notifications_after, notifications_before,
                         "Un backfill historique ne doit générer aucun courriel client.")

    def test_confirmation_est_idempotente(self):
        wizard = self._wizard()
        wizard.action_preview()
        wizard.candidate_line_ids.write({"include": True})
        wizard.action_confirm()

        first = self.historical.line_ids.mapped("id")

        # Deuxième passe : la consolidation est en `departed`, la prévisualisation
        # marque les dossiers comme déjà rattachés donc `include=False` par
        # défaut. Rien de nouveau ne doit être créé.
        second_wizard = self._wizard()
        second_wizard.action_preview()
        for candidate in second_wizard.candidate_line_ids:
            self.assertFalse(candidate.include,
                             "Un dossier déjà consolidé ne doit pas être resélectionné automatiquement.")

        # Même si on force include, la ligne existe déjà : `Line.search` la
        # trouve et `continue`, aucun doublon n'est écrit.
        second_wizard.candidate_line_ids.write({"include": True})
        second_wizard.action_confirm()
        self.assertEqual(sorted(self.historical.line_ids.ids), sorted(first))

    def test_context_historique_forgeable_ne_supprime_pas_les_effets(self):
        shipment = self._shipment(reference="HIST-CTX")
        before = self.env["dally.shipment.event"].search_count([("shipment_id", "=", shipment.id)])
        forged = fields.Datetime.to_datetime("2026-08-18 10:00:00")
        shipment.with_context(historical_backfill=True, historical_event_date=forged).write({"state": "request_received"})
        self.assertGreater(self.env["dally.shipment.event"].search_count([("shipment_id", "=", shipment.id)]), before)
        self.assertNotEqual(shipment.state_changed_on, forged)
