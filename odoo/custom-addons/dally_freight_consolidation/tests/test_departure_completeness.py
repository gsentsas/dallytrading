# -*- coding: utf-8 -*-
"""La complétude d'un départ : ce qui est *attendu*, pas seulement ce qui est là.

## Le trou que ces tests ferment

Avant, la porte de sortie ne regardait que `line_ids` — les colis effectivement
chargés. Un départ dont aucun dossier n'avait été chargé n'avait donc aucun
dossier à contrôler, et passait la porte : la vérification portait sur un
ensemble vide et concluait que tout allait bien. Un départ pouvait partir en
oubliant tout le monde.

L'autorité devient `planned_consolidation_id`, le départ **prévu**. Il dit ce
qu'on attend ; `line_ids` dit ce qu'on a. Le contrôle porte enfin sur l'écart
entre les deux.

## Pourquoi l'union avec les dossiers déjà chargés

Un dossier chargé ici sans départ prévu — un import historique, une reprise —
reste attendu : il est là. L'union garantit qu'aucun dossier présent ne sort du
contrôle, et c'est ce qui rend le durcissement rétro-compatible.
"""

from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.dally_freight_consolidation.models.consolidation import (
    DallyFreightConsolidationLine,
)
from odoo.addons.dally_freight_consolidation.models.shipment import (
    _INTAKE_IDENTITY_TOKEN,
)

from .common import ConsolidationCommon


@tagged("post_install", "-at_install", "dally")
class TestDepartureCompleteness(ConsolidationCommon):

    def setUp(self):
        super().setUp()
        self.depart = self._consolidation("AIR-DSS-CDG-COMPLET-1")
        self.ailleurs = self._consolidation("AIR-DSS-CDG-COMPLET-2")

    # ─── Outils ──────────────────────────────────────────────────────

    def _charger(self, shipment, depart=None, quantite=None):
        package = shipment.package_ids[0]
        return self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": (depart or self.depart).id,
            "package_id": package.id,
            "quantity_loaded": quantite or package.quantity,
        })

    def _blocages(self, depart=None):
        return (depart or self.depart)._departure_blockers()

    def _partiels(self, depart=None):
        return (depart or self.depart)._shipment_partial_departure_blockers()

    # ─── Le trou refermé ─────────────────────────────────────────────

    def test_un_depart_sans_aucun_dossier_attendu_est_bloque(self):
        blocages = self._blocages()
        self.assertIn("Aucun dossier n'est rattaché.", blocages)

    def test_un_dossier_prevu_mais_rien_de_charge_bloque_le_depart(self):
        """Le cas exact qui passait avant : un dossier attendu, zéro ligne."""
        shipment = self._shipment(reference="TST-COMPLET-A")
        shipment.planned_consolidation_id = self.depart

        blocages = self._blocages()
        self.assertNotIn("Aucun dossier n'est rattaché.", blocages)
        self.assertIn("Aucun colis n'est chargé.", blocages)
        # Et le dossier lui-même est nommé : il n'est pas prêt.
        self.assertTrue(any("TST-COMPLET-A" in motif for motif in blocages))

    def test_un_dossier_prevu_non_charge_est_nomme_colis_par_colis(self):
        shipment = self._shipment(reference="TST-COMPLET-B")
        shipment.planned_consolidation_id = self.depart

        partiels = self._partiels()
        self.assertTrue(partiels)
        self.assertTrue(any("TST-COMPLET-B" in motif and "n'est pas chargé" in motif
                            for motif in partiels))

    def test_un_dossier_prevu_sans_aucun_colis_est_signale(self):
        shipment = self.env["dally.shipment"].create({
            "partner_id": self.business.id,
            "external_reference": "TST-COMPLET-VIDE",
            "transport_mode": "air", "direction": "export",
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_city": "Paris", "destination_location": "CDG",
        })
        shipment.planned_consolidation_id = self.depart

        partiels = self._partiels()
        self.assertTrue(any("TST-COMPLET-VIDE" in motif
                            and "aucun colis n'est enregistré" in motif
                            for motif in partiels))

    def test_un_dossier_partiellement_charge_bloque_encore(self):
        shipment = self._shipment(reference="TST-COMPLET-C")
        shipment.planned_consolidation_id = self.depart
        self._charger(shipment, quantite=1)  # le colis en compte 2

        partiels = self._partiels()
        self.assertTrue(any("TST-COMPLET-C" in motif for motif in partiels))

    def test_un_dossier_entierement_charge_ne_bloque_plus_au_titre_des_colis(self):
        shipment = self._shipment(reference="TST-COMPLET-D")
        shipment.planned_consolidation_id = self.depart
        self._charger(shipment)

        self.assertEqual(self._partiels(), [])
        self.assertNotIn("Aucun colis n'est chargé.", self._blocages())
        self.assertNotIn("Aucun dossier n'est rattaché.", self._blocages())

    # ─── Chargé ici, prévu ailleurs ──────────────────────────────────

    def test_un_dossier_charge_ici_mais_prevu_ailleurs_bloque(self):
        shipment = self._shipment(reference="TST-COMPLET-E")
        shipment.planned_consolidation_id = self.ailleurs
        self._charger(shipment)

        motifs = [motif for motif in self._blocages()
                  if "TST-COMPLET-E" in motif and "prévu sur" in motif]
        self.assertEqual(len(motifs), 1)
        self.assertIn(self.ailleurs.display_name, motifs[0])

    def test_un_dossier_charge_sans_depart_prevu_ne_bloque_pas_a_ce_titre(self):
        """La rétro-compatibilité tient à cette nuance.

        Un dossier sans départ prévu ne pointe nulle part : il ne contredit
        rien. Le blocage ne vise que la contradiction — chargé ici, attendu
        ailleurs — et non l'absence d'information.
        """
        shipment = self._shipment(reference="TST-COMPLET-F")
        self.assertFalse(shipment.planned_consolidation_id)
        self._charger(shipment)

        self.assertFalse([motif for motif in self._blocages()
                          if "prévu sur" in motif])

    # ─── Ce qui définit « attendu » ──────────────────────────────────

    def test_l_attendu_vient_du_depart_prevu_et_non_de_la_reception(self):
        """La distinction que ce durcissement repose entièrement dessus.

        `intake_consolidation_id` dit *où le colis est entré* ; il est figé à
        la création. `planned_consolidation_id` dit *sur quel départ il est
        attendu*, et lui peut être replanifié. Confondre les deux ferait
        attendre un dossier sur le départ qui l'a reçu, pour toujours.
        """
        shipment = self.env["dally.shipment"].with_context(
            _dally_intake_identity_token=_INTAKE_IDENTITY_TOKEN,
        ).create({
            "partner_id": self.business.id,
            "external_reference": "TST-COMPLET-G",
            "transport_mode": "air", "direction": "export",
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_city": "Paris", "destination_location": "CDG",
            "intake_consolidation_id": self.ailleurs.id,
        })
        shipment.planned_consolidation_id = self.depart

        self.assertEqual(shipment.intake_consolidation_id, self.ailleurs)
        self.assertIn(shipment, self.depart._expected_shipments())
        self.assertNotIn(shipment, self.ailleurs._expected_shipments())

    def test_un_dossier_charge_reste_attendu_meme_sans_depart_prevu(self):
        shipment = self._shipment(reference="TST-COMPLET-H")
        self._charger(shipment)
        self.assertIn(shipment, self.depart._expected_shipments())

    def test_l_attendu_ne_compte_jamais_deux_fois_le_meme_dossier(self):
        shipment = self._shipment(reference="TST-COMPLET-I")
        shipment.planned_consolidation_id = self.depart
        self._charger(shipment)
        self.assertEqual(len(self.depart._expected_shipments()), 1)

    def test_une_societe_etrangere_ne_peut_pas_devenir_un_depart_prevu(self):
        """Le cœur refuse le rattachement, avant même le filtre de lecture.

        Un dossier d'une autre société sans départ prévu ni ligne serait exclu
        de toute façon : l'affirmer ne prouverait rien. Ce qui se prouve, c'est
        que le rattachement lui-même est refusé.
        """
        autre_societe = self.env["res.company"].create({"name": "Complet Autre"})
        etranger = self.env["dally.shipment"].create({
            "partner_id": self.business.id,
            "company_id": autre_societe.id,
            "external_reference": "TST-COMPLET-ETR",
            "transport_mode": "air", "direction": "export",
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_city": "Paris", "destination_location": "CDG",
        })
        with self.assertRaises(ValidationError):
            etranger.planned_consolidation_id = self.depart

    def test_le_filtre_par_societe_borne_bien_l_attendu(self):
        """Le filtre lui-même, isolé.

        On construit un départ jumeau dans une autre société et un dossier qui
        y est réellement prévu : il est attendu là-bas, et nulle part ici. Sans
        le filtre `company_id`, la recherche par `planned_consolidation_id`
        seule ne les distinguerait pas si deux départs partageaient un
        identifiant — c'est cette garantie que le test tient.
        """
        autre_societe = self.env["res.company"].create({"name": "Complet Ailleurs"})
        depart_etranger = self.env["dally.freight.consolidation"].with_company(
            autre_societe).create({
                "name": "AIR-DSS-CDG-COMPLET-ETR", "company_id": autre_societe.id,
                "transport_mode": "air", "direction": "export",
                "origin_city": "Dakar", "origin_location": "DSS",
                "destination_city": "Paris", "destination_location": "CDG",
                "carrier_name": "Air Sénégal", "mawb_number": "297-99999999",
                "state": "collecting",
            })
        etranger = self.env["dally.shipment"].with_company(autre_societe).create({
            "partner_id": self.business.id,
            "company_id": autre_societe.id,
            "external_reference": "TST-COMPLET-ETR2",
            "transport_mode": "air", "direction": "export",
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_city": "Paris", "destination_location": "CDG",
        })
        etranger.with_company(autre_societe).planned_consolidation_id = depart_etranger

        self.assertIn(etranger, depart_etranger._expected_shipments())
        self.assertNotIn(etranger, self.depart._expected_shipments())

    # ─── Le verrou manquant au retrait ───────────────────────────────

    def test_retirer_une_ligne_verrouille_son_colis(self):
        """Créer et corriger prenaient le verrou ; supprimer ne le prenait pas.

        Le plafond de quantité se recalcule à partir des lignes existantes :
        une suppression qui ne se sérialise pas laisse une transaction voisine
        lire un total périmé et accepter une charge en trop.
        """
        premier = self._shipment(reference="TST-COMPLET-J")
        second = self._shipment(reference="TST-COMPLET-K")
        lignes = self._charger(premier) | self._charger(second)
        attendus = sorted(lignes.mapped("package_id.id"))

        appels = []
        original = DallyFreightConsolidationLine._lock_package

        def espion(cr, package_id):
            appels.append(package_id)
            return original(cr, package_id)

        with patch.object(DallyFreightConsolidationLine, "_lock_package",
                          staticmethod(espion)):
            lignes.unlink()

        self.assertEqual(sorted(set(appels)), attendus)

    def test_retirer_verrouille_chaque_colis_une_seule_fois(self):
        shipment = self._shipment(reference="TST-COMPLET-L")
        ligne = self._charger(shipment)
        package_id = ligne.package_id.id

        appels = []
        original = DallyFreightConsolidationLine._lock_package

        def espion(cr, package_id_appele):
            appels.append(package_id_appele)
            return original(cr, package_id_appele)

        with patch.object(DallyFreightConsolidationLine, "_lock_package",
                          staticmethod(espion)):
            ligne.unlink()

        self.assertEqual(appels, [package_id])
