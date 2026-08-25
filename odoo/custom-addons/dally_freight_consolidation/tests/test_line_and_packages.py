# -*- coding: utf-8 -*-
"""Lignes de consolidation et contraintes sur les colis clients."""

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import ConsolidationCommon


@tagged("post_install", "-at_install", "dally_freight")
class TestConsolidationLines(ConsolidationCommon):

    def test_creation_ligne_hors_collecte_est_refusee(self):
        consolidation = self._consolidation()
        consolidation.action_close_collection()
        shipment = self._shipment(reference="OUTSIDE-1")

        with self.assertRaises(UserError):
            self.env["dally.freight.consolidation.line"].create({
                "consolidation_id": consolidation.id,
                "package_id": shipment.package_ids.id,
                "quantity_loaded": 1,
            })

    def test_quantite_chargee_ne_depasse_pas_la_quantite_du_colis(self):
        """Le colis a une quantité `n`, on ne peut pas en charger `n+1`."""
        consolidation = self._consolidation()
        shipment = self._shipment(reference="LIMIT-1")
        package = shipment.package_ids  # quantity = 2

        with self.assertRaises(ValidationError):
            self.env["dally.freight.consolidation.line"].create({
                "consolidation_id": consolidation.id,
                "package_id": package.id,
                "quantity_loaded": 3,
            })

    def test_deux_consolidations_ne_peuvent_pas_prendre_plus_que_le_stock(self):
        """La contrainte est globale : la somme sur toutes les consolidations
        actives ne peut pas dépasser la quantité disponible."""
        cons_a = self._consolidation(name="AIR-DSS-CDG-2026-A")
        cons_b = self._consolidation(name="AIR-DSS-CDG-2026-B")
        shipment = self._shipment(reference="SHARE-1")
        package = shipment.package_ids  # quantity = 2

        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": cons_a.id,
            "package_id": package.id,
            "quantity_loaded": 2,
        })
        with self.assertRaises(ValidationError):
            self.env["dally.freight.consolidation.line"].create({
                "consolidation_id": cons_b.id,
                "package_id": package.id,
                "quantity_loaded": 1,
            })

    def test_ligne_partie_ne_peut_pas_etre_modifiee_ou_supprimee(self):
        consolidation = self._consolidation()
        shipment = self._shipment(reference="FROZEN-1")
        line = self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": shipment.package_ids.id,
            "quantity_loaded": 1,
        })
        # On force l'état sans transiter par les gates de départ ni les
        # préconditions dossier : le point testé est l'immutabilité, pas la
        # gate de départ (couverte par test_departure_gate).
        consolidation.write({"state": "collection_closed"})
        consolidation.write({"state": "ready"})
        consolidation.with_context(_dally_consolidation_bypass_test=True)
        consolidation.write({"actual_departure": "2026-08-25 06:00:00"})
        # bypass via un write direct — on est en dev, la contrainte de write
        # sur `state` autorise ready → departed.
        consolidation.write({"state": "departed"})

        with self.assertRaises(UserError):
            line.write({"quantity_loaded": 2})
        with self.assertRaises(UserError):
            line.unlink()

    def test_quantite_disponible_est_recalculee_apres_chargement(self):
        consolidation = self._consolidation()
        shipment = self._shipment(reference="QTY-1")
        package = shipment.package_ids  # quantity = 2

        self.assertEqual(package.available_quantity, 2)
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": package.id,
            "quantity_loaded": 1,
        })
        package.invalidate_recordset(["loaded_quantity", "available_quantity"])
        self.assertEqual(package.loaded_quantity, 1)
        self.assertEqual(package.available_quantity, 1)
