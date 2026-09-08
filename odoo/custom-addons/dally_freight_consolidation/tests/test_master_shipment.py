# -*- coding: utf-8 -*-
"""L'expédition maître d'une consolidation.

Ce qui se joue ici n'est pas « le champ est-il rempli » mais « peut-on router
une consolidation au mauvais endroit sans que personne ne le voie ». Les cas de
refus comptent donc autant que le cas heureux, et davantage : un maître absent
se remarque, un maître mal routé se découvre à l'arrivée.
"""

import logging
import os

import psycopg2
from psycopg2 import errors
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.dally_freight_consolidation.models.consolidation import (
    _CONSOLIDATION_BYPASS_TOKEN,
    _CONSOLIDATION_STATE_WRITE_TOKEN,
)

from .common import ConsolidationCommon

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestMasterShipment(ConsolidationCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.senegal = cls.env.ref("base.sn")
        cls.france = cls.env.ref("base.fr")
        Port = cls.env["freight.port"]
        # Deux ports aériens sur la route de référence, plus un port maritime
        # homonyme : c'est lui qui prouve que le drapeau de mode compte.
        cls.port_dss = Port.create({
            "name": "Dakar Blaise Diagne", "code": "DSS",
            "city": "Dakar", "country_id": cls.senegal.id, "air": True,
        })
        cls.port_cdg = Port.create({
            "name": "Paris Charles de Gaulle", "code": "CDG",
            "city": "Paris", "country_id": cls.france.id, "air": True,
        })
        cls.port_dkr_mer = Port.create({
            "name": "Port autonome de Dakar", "code": "DKR",
            "city": "Dakar", "country_id": cls.senegal.id, "ocean": True,
        })
        cls.port_lehavre = Port.create({
            "name": "Le Havre", "code": "LEH",
            "city": "Le Havre", "country_id": cls.france.id, "ocean": True,
        })

    # ------------------------------------------------------------------
    # Le cas heureux, mode par mode
    # ------------------------------------------------------------------

    def test_aerien_reporte_mode_route_dates_et_document(self):
        consolidation = self._consolidation()
        consolidation.write({
            "flight_number": "HC302",
            "scheduled_departure": "2026-09-20 08:00:00",
            "estimated_arrival": "2026-09-20 15:30:00",
            "master_piece_count": 12,
            "master_gross_weight_kg": 480.5,
        })
        consolidation.action_create_master_shipment()

        maitre = consolidation.tk_master_shipment_id
        self.assertTrue(maitre, "le maître doit être rattaché")
        self.assertEqual(maitre.operation, "master")
        self.assertEqual(maitre.transport, "air")
        self.assertEqual(maitre.direction, "export")
        self.assertEqual(maitre.source_location_id, self.port_dss)
        self.assertEqual(maitre.destination_location_id, self.port_cdg)
        # Sans `port_ids`, le domaine du fournisseur rejetterait à l'écran les
        # ports qu'on vient d'y écrire.
        self.assertIn(self.port_dss, maitre.port_ids)
        self.assertIn(self.port_cdg, maitre.port_ids)
        self.assertEqual(maitre.mawb_no, "297-12345678")
        self.assertEqual(maitre.flight_no, "HC302")
        self.assertFalse(maitre.bl_number, "le connaissement n'a pas de sens en aérien")
        self.assertEqual(str(maitre.pickup_datetime), "2026-09-20 08:00:00")
        self.assertEqual(str(maitre.arrival_datetime), "2026-09-20 15:30:00")

    def test_aerien_declare_pieces_et_poids_en_une_ligne(self):
        consolidation = self._consolidation()
        consolidation.write({"master_piece_count": 12, "master_gross_weight_kg": 480.5})
        consolidation.action_create_master_shipment()

        lignes = consolidation.tk_master_shipment_id.freight_packages
        self.assertEqual(len(lignes), 1, "une seule ligne agrégée, pas un colis par pièce")
        self.assertEqual(lignes.qty, 12)
        self.assertAlmostEqual(lignes.gross_weight, 480.5, places=3)
        self.assertEqual(lignes.name, consolidation.name)

    def test_sans_declaration_aucune_ligne_colis(self):
        # Une ligne à zéro pièce serait un renseignement faux.
        consolidation = self._consolidation()
        consolidation.write({"master_piece_count": 0, "master_gross_weight_kg": 0.0})
        consolidation.action_create_master_shipment()
        self.assertFalse(consolidation.tk_master_shipment_id.freight_packages)

    def test_maritime_reporte_connaissement_et_voyage(self):
        consolidation = self.env["dally.freight.consolidation"].create({
            "name": "SEA-DKR-LEH-2026-TEST", "transport_mode": "sea",
            "direction": "export", "origin_location": "DKR",
            "destination_location": "LEH", "mawb_number": "MBL-99001",
            "flight_number": "V-114", "state": "collecting",
        })
        consolidation.action_create_master_shipment()

        maitre = consolidation.tk_master_shipment_id
        self.assertEqual(maitre.transport, "ocean", "« sea » chez nous, « ocean » chez eux")
        self.assertEqual(maitre.source_location_id, self.port_dkr_mer)
        self.assertEqual(maitre.destination_location_id, self.port_lehavre)
        self.assertEqual(maitre.bl_number, "MBL-99001")
        self.assertEqual(maitre.voyage_no, "V-114")
        self.assertFalse(maitre.mawb_no, "la LTA n'a pas de sens en maritime")

    def test_routier_reporte_la_lettre_de_voiture(self):
        Port = self.env["freight.port"]
        Port.create({"name": "Dakar Route", "code": "DKR-R", "city": "Dakar",
                     "country_id": self.senegal.id, "land": True})
        Port.create({"name": "Bamako Route", "code": "BKO-R", "city": "Bamako",
                     "country_id": self.env.ref("base.ml").id, "land": True})
        consolidation = self.env["dally.freight.consolidation"].create({
            "name": "ROAD-DKR-BKO-2026-TEST", "transport_mode": "road",
            "direction": "export", "origin_location": "DKR-R",
            "destination_location": "BKO-R", "mawb_number": "CMR-771",
            "state": "collecting",
        })
        consolidation.action_create_master_shipment()

        maitre = consolidation.tk_master_shipment_id
        self.assertEqual(maitre.transport, "land")
        self.assertEqual(maitre.truck_ref, "CMR-771")
        self.assertFalse(maitre.mawb_no)
        self.assertFalse(maitre.bl_number)

    # ------------------------------------------------------------------
    # L'extraction déterministe d'un code
    # ------------------------------------------------------------------

    def test_un_code_noye_dans_le_libelle_est_extrait(self):
        # Les libellés de terrain mêlent le nom et le code. L'extraction ne
        # retient que les jetons de exactement trois lettres : « AIBD » en fait
        # quatre, « Roissy » six.
        for champ, libelle, port in (
            ("origin_location", "AIBD-DSS", self.port_dss),
            ("origin_location", "DSS", self.port_dss),
            ("origin_location", "Aéroport AIBD / DSS", self.port_dss),
            ("destination_location", "Roissy CDG", self.port_cdg),
            ("destination_location", "CDG", self.port_cdg),
        ):
            with self.subTest(libelle=libelle):
                consolidation = self._consolidation(
                    name="AIR-EXTRACT-%s" % abs(hash(champ + libelle)))
                consolidation.write({champ: libelle})
                consolidation.action_create_master_shipment()
                cible = ("source_location_id" if champ == "origin_location"
                         else "destination_location_id")
                self.assertEqual(consolidation.tk_master_shipment_id[cible], port)

    def test_deux_codes_dans_le_meme_libelle_ne_donnent_rien(self):
        # « DSS CDG » : on ne choisit pas lequel est l'origine. Le fail-closed
        # s'applique à l'extraction elle-même.
        consolidation = self._consolidation()
        consolidation.write({"origin_location": "DSS CDG", "origin_city": False})
        with self.assertRaises(UserError) as refus:
            consolidation.action_create_master_shipment()
        self.assertIn("Aucun port", str(refus.exception))

    def test_l_extraction_reste_exacte_et_sans_joker(self):
        # « DAKAR » fait cinq lettres : rien n'est extrait, et aucun port n'est
        # trouvé par sous-chaîne. Un `ilike` avec jokers aurait matché « DSS »
        # dans un nom quelconque.
        self.assertIsNone(
            self.env["dally.freight.consolidation"]._dally_code_iata("DAKAR"))
        self.assertEqual(
            self.env["dally.freight.consolidation"]._dally_code_iata("AIBD-DSS"), "DSS")
        self.assertEqual(
            self.env["dally.freight.consolidation"]._dally_code_iata("Roissy CDG"), "CDG")
        self.assertIsNone(
            self.env["dally.freight.consolidation"]._dally_code_iata("LEH BKO"))
        self.assertIsNone(
            self.env["dally.freight.consolidation"]._dally_code_iata(""))

    def test_un_joker_dans_le_libelle_ne_elargit_pas_la_recherche(self):
        """`=ilike` ne pose pas de joker, mais il en honore.

        Sans échappement, un libellé « D_S » trouverait « DSS » — et « % »
        trouverait n'importe quel port. La promesse d'exactitude tomberait sur
        une valeur que l'exploitation saisit librement.
        """
        Consolidation = self.env["dally.freight.consolidation"]
        self.assertEqual(Consolidation._dally_echapper_like("D_S"), "D\\_S")
        self.assertEqual(Consolidation._dally_echapper_like("100%"), "100\\%")

        for joker in ("D_S", "%", "DS%", "_SS"):
            with self.subTest(joker=joker):
                consolidation = self._consolidation(
                    name="AIR-JOKER-%s" % abs(hash(joker)))
                consolidation.write({"origin_location": joker, "origin_city": False})
                with self.assertRaises(UserError) as refus:
                    consolidation.action_create_master_shipment()
                self.assertIn("Aucun port", str(refus.exception))

    # ------------------------------------------------------------------
    # Le poids sans les pièces
    # ------------------------------------------------------------------

    def test_un_poids_sans_pieces_est_refuse(self):
        # Compléter par « 1 pièce » déclarerait un colis que personne n'a
        # compté, et lui attacherait tout le poids.
        consolidation = self._consolidation()
        consolidation.write({"master_piece_count": 0, "master_gross_weight_kg": 480.5})
        with self.assertRaises(UserError) as refus:
            consolidation.action_create_master_shipment()
        self.assertIn("sans nombre de pièces", str(refus.exception))
        self.assertFalse(consolidation.tk_master_shipment_id,
                         "aucun maître ne doit rester derrière un refus")

    def test_aucun_maitre_orphelin_apres_un_refus_de_ligne_colis(self):
        # Le refus tombe après le verrou : il ne doit laisser ni expédition ni
        # lien. La transaction de test le vérifie à l'état visible.
        consolidation = self._consolidation()
        consolidation.write({"master_piece_count": 0, "master_gross_weight_kg": 12.0})
        avant = self.env["freight.shipment"].search_count([])
        with self.assertRaises(UserError):
            consolidation.action_create_master_shipment()
        self.assertEqual(self.env["freight.shipment"].search_count([]), avant)

    # ------------------------------------------------------------------
    # L'idempotence
    # ------------------------------------------------------------------

    def test_deuxieme_clic_ouvre_le_meme_maitre_sans_en_creer_un_second(self):
        consolidation = self._consolidation()
        consolidation.action_create_master_shipment()
        premier = consolidation.tk_master_shipment_id
        avant = self.env["freight.shipment"].search_count([])

        action = consolidation.action_create_master_shipment()

        self.assertEqual(consolidation.tk_master_shipment_id, premier)
        self.assertEqual(self.env["freight.shipment"].search_count([]), avant,
                         "aucune expédition supplémentaire")
        self.assertEqual(action["res_id"], premier.id)

    def test_rejeu_apres_rechargement_ne_duplique_pas(self):
        consolidation = self._consolidation()
        consolidation.action_create_master_shipment()
        maitre = consolidation.tk_master_shipment_id
        consolidation.invalidate_recordset()
        consolidation.action_create_master_shipment()
        self.assertEqual(consolidation.tk_master_shipment_id, maitre)

    @mute_logger("odoo.sql_db")
    def test_deux_consolidations_ne_partagent_pas_un_maitre(self):
        # Le garde Python ne protège que d'un appel séquentiel. Deux
        # transactions concurrentes lisent toutes les deux « pas de maître » ;
        # seule la contrainte en base les sépare.
        premiere = self._consolidation()
        premiere.action_create_master_shipment()
        seconde = self._consolidation(name="AIR-DSS-CDG-2026-TEST-2")
        with self.assertRaises(errors.UniqueViolation):
            with self.cr.savepoint():
                seconde.write({"tk_master_shipment_id": premiere.tk_master_shipment_id.id})
                self.env.flush_all()

    # ------------------------------------------------------------------
    # Les refus
    # ------------------------------------------------------------------

    def test_domestique_est_refuse(self):
        consolidation = self._consolidation()
        consolidation.write({"direction": "domestic"})
        with self.assertRaises(UserError) as refus:
            consolidation.action_create_master_shipment()
        self.assertIn("domestique", str(refus.exception).lower())
        self.assertFalse(consolidation.tk_master_shipment_id,
                         "aucun rattachement silencieux")

    def test_port_introuvable_est_refuse(self):
        consolidation = self._consolidation()
        consolidation.write({"origin_location": "ZZZ", "origin_city": "Nulle Part"})
        with self.assertRaises(UserError) as refus:
            consolidation.action_create_master_shipment()
        self.assertIn("Aucun port", str(refus.exception))
        self.assertFalse(consolidation.tk_master_shipment_id)

    def test_port_ambigu_est_refuse(self):
        # Deux ports aériens nommés « Dakar » : on ne choisit pas pour l'humain.
        self.env["freight.port"].create({
            "name": "Dakar Blaise Diagne", "code": "DSS-2", "city": "Dakar",
            "country_id": self.senegal.id, "air": True,
        })
        consolidation = self._consolidation()
        consolidation.write({"origin_location": "Dakar Blaise Diagne"})
        with self.assertRaises(UserError) as refus:
            consolidation.action_create_master_shipment()
        self.assertIn("Plusieurs ports", str(refus.exception))
        self.assertFalse(consolidation.tk_master_shipment_id)

    def test_port_du_mauvais_mode_est_refuse(self):
        # DKR est un port maritime : une consolidation aérienne ne doit pas s'y
        # router, même si le nom de ville correspond.
        consolidation = self._consolidation()
        consolidation.write({"origin_location": "DKR", "origin_city": False})
        with self.assertRaises(UserError) as refus:
            consolidation.action_create_master_shipment()
        self.assertIn("Aucun port", str(refus.exception))

    def test_origine_et_destination_identiques_sont_refusees(self):
        consolidation = self._consolidation()
        consolidation.write({"destination_location": "DSS", "destination_city": "Dakar",
                             "destination_country_id": self.senegal.id})
        with self.assertRaises(UserError) as refus:
            consolidation.action_create_master_shipment()
        self.assertIn("même port", str(refus.exception))

    def test_creation_refusee_apres_le_depart(self):
        consolidation = self._consolidation()
        consolidation.with_context(
            _dally_consolidation_state_write=_CONSOLIDATION_STATE_WRITE_TOKEN,
            _dally_consolidation_bypass=_CONSOLIDATION_BYPASS_TOKEN,
        ).write({"state": "departed"})
        with self.assertRaises(UserError) as refus:
            consolidation.action_create_master_shipment()
        self.assertIn("avant le départ", str(refus.exception))

    def test_rattachement_gele_apres_le_depart(self):
        consolidation = self._consolidation()
        consolidation.action_create_master_shipment()
        autre = self.env["freight.shipment"].create({"transport": "air"})
        consolidation.with_context(
            _dally_consolidation_state_write=_CONSOLIDATION_STATE_WRITE_TOKEN,
            _dally_consolidation_bypass=_CONSOLIDATION_BYPASS_TOKEN,
        ).write({"state": "departed"})
        with self.assertRaises(UserError) as refus:
            consolidation.write({"tk_master_shipment_id": autre.id})
        self.assertIn("figés après le départ", str(refus.exception))

    def test_ouvrir_sans_maitre_est_refuse(self):
        consolidation = self._consolidation()
        with self.assertRaises(UserError):
            consolidation.action_open_master_shipment()

    # ------------------------------------------------------------------
    # Le transporteur : commodité, pas règle de routage
    # ------------------------------------------------------------------

    def test_compagnie_aerienne_resolue_quand_elle_est_unique(self):
        proprietaire = self.env["res.partner"].create({"name": "Air Sénégal SA"})
        compagnie = self.env["freight.airline"].create({
            "name": "Air Sénégal", "owner_id": proprietaire.id,
        })
        consolidation = self._consolidation()
        consolidation.action_create_master_shipment()
        maitre = consolidation.tk_master_shipment_id
        self.assertEqual(maitre.airline_id, compagnie)
        self.assertEqual(maitre.airline_owner_id, proprietaire,
                         "le propriétaire garde le domaine du fournisseur cohérent")

    def test_transporteur_inconnu_laisse_le_champ_vide_sans_bloquer(self):
        # Contrairement à la route, un transporteur absent ne fait rien partir
        # au mauvais endroit : il ne bloque pas la création.
        consolidation = self._consolidation()
        consolidation.write({"carrier_name": "Compagnie Qui N’Existe Pas"})
        consolidation.action_create_master_shipment()
        self.assertTrue(consolidation.tk_master_shipment_id)
        self.assertFalse(consolidation.tk_master_shipment_id.airline_id)

    # ------------------------------------------------------------------
    # Ce qui est relu APRÈS le verrou
    # ------------------------------------------------------------------
    #
    # Le verrou ne protège que ce qui est lu après lui. Ces deux tests écrivent
    # en SQL direct — donc sans passer par le cache de l'ORM, exactement comme
    # le ferait une autre transaction validée entre-temps — et vérifient que
    # l'action s'en aperçoit.

    def test_un_depart_survenu_entre_temps_est_vu(self):
        consolidation = self._consolidation()
        self.assertEqual(consolidation.state, "collecting")
        self.env.cr.execute(
            "UPDATE dally_freight_consolidation SET state = 'departed' WHERE id = %s",
            [consolidation.id])
        # Le cache de la transaction porte encore « collecting ».
        self.assertEqual(consolidation.state, "collecting")
        with self.assertRaises(UserError) as refus:
            consolidation.action_create_master_shipment()
        self.assertIn("avant le départ", str(refus.exception))
        self.assertFalse(consolidation.tk_master_shipment_id)

    def test_une_route_changee_entre_temps_est_revalidee(self):
        consolidation = self._consolidation()
        self.env.cr.execute(
            "UPDATE dally_freight_consolidation SET origin_location = 'ZZZ', "
            "origin_city = NULL WHERE id = %s", [consolidation.id])
        self.assertEqual(consolidation.origin_location, "DSS")
        with self.assertRaises(UserError) as refus:
            consolidation.action_create_master_shipment()
        self.assertIn("Aucun port", str(refus.exception))

    def test_un_maitre_cree_entre_temps_est_repris_sans_doublon(self):
        consolidation = self._consolidation()
        autre = self.env["freight.shipment"].create(
            {"transport": "air", "operation": "master"})
        self.env.cr.execute(
            "UPDATE dally_freight_consolidation SET tk_master_shipment_id = %s "
            "WHERE id = %s", [autre.id, consolidation.id])
        avant = self.env["freight.shipment"].search_count([])
        action = consolidation.action_create_master_shipment()
        self.assertEqual(action["res_id"], autre.id)
        self.assertEqual(self.env["freight.shipment"].search_count([]), avant)

    # ------------------------------------------------------------------
    # Ce qu'un rattachement a le droit d'être
    # ------------------------------------------------------------------

    def test_un_rattachement_vers_une_expedition_maison_est_refuse(self):
        maison = self.env["freight.shipment"].create(
            {"transport": "air", "operation": "house"})
        consolidation = self._consolidation()
        with self.assertRaises(ValidationError) as refus:
            consolidation.write({"tk_master_shipment_id": maison.id})
            consolidation.flush_recordset()
        self.assertIn("maître", str(refus.exception))

    def test_un_rattachement_vers_une_autre_societe_est_refuse(self):
        autre_societe = self.env["res.company"].create({"name": "Autre Société"})
        etranger = self.env["freight.shipment"].create({
            "transport": "air", "operation": "master",
            "company_id": autre_societe.id})
        consolidation = self._consolidation()
        with self.assertRaises(ValidationError) as refus:
            consolidation.write({"tk_master_shipment_id": etranger.id})
            consolidation.flush_recordset()
        self.assertIn("appartient", str(refus.exception))

    def test_le_maitre_cree_par_l_action_satisfait_la_contrainte(self):
        consolidation = self._consolidation()
        consolidation.action_create_master_shipment()
        maitre = consolidation.tk_master_shipment_id
        self.assertEqual(maitre.operation, "master")
        self.assertEqual(maitre.company_id, consolidation.company_id)

    # ------------------------------------------------------------------
    # Le chemin de retour, les droits, la non-régression
    # ------------------------------------------------------------------

    def test_depuis_l_expedition_on_retrouve_la_consolidation(self):
        consolidation = self._consolidation()
        consolidation.action_create_master_shipment()
        maitre = consolidation.tk_master_shipment_id
        self.assertEqual(maitre.dally_consolidation_id, consolidation)
        action = maitre.action_open_dally_consolidation()
        self.assertEqual(action["res_model"], "dally.freight.consolidation")
        self.assertEqual(action["res_id"], consolidation.id)

    def test_le_lien_reste_hors_du_portail(self):
        # Même confinement que `dally.shipment.tk_shipment_id` : un compte
        # portail n'a pas `group_dally_readonly`, donc ne lit pas le champ.
        champ = self.env["dally.freight.consolidation"]._fields["tk_master_shipment_id"]
        self.assertEqual(champ.groups, "dally_core.group_dally_readonly")

    def test_aucune_expedition_cliente_n_est_reparentee(self):
        # Ce cycle crée le maître et rien d'autre. Le rattachement house/master
        # des expéditions clientes est un autre chantier : si ce test tombe,
        # c'est que quelqu'un l'a commencé ici.
        shipment = self._shipment(reference="TST-MASTER-1")
        consolidation = self._consolidation()
        consolidation.action_create_master_shipment()
        maitre = consolidation.tk_master_shipment_id
        self.assertFalse(maitre.parent_id)
        self.assertFalse(maitre.shipments_ids)
        if "tk_shipment_id" in shipment._fields:
            self.assertFalse(shipment.sudo().tk_shipment_id,
                             "le dossier client garde son propre lien, intact")

    def test_le_workflow_de_consolidation_reste_intact(self):
        # Non-régression : la création du maître ne doit rien changer au cycle
        # de vie de la consolidation ni piloter l'étape du fournisseur.
        consolidation = self._consolidation()
        consolidation.action_create_master_shipment()
        etape_initiale = consolidation.tk_master_shipment_id.stage_id
        consolidation.action_close_collection()
        self.assertEqual(consolidation.state, "collection_closed")
        self.assertEqual(consolidation.tk_master_shipment_id.stage_id, etape_initiale,
                         "l'état de la consolidation ne pilote pas l'étape tk")


@tagged("post_install", "-at_install")
class TestMasterShipmentConcurrence(TransactionCase):
    """Deux créations concurrentes sur la MÊME consolidation.

    Le test d'unicité prouvait qu'une expédition ne peut pas servir deux
    consolidations. Il ne prouvait pas le cas qui compte : deux appels
    concurrents sur la même consolidation. Chacun crée son expédition, les deux
    clés étrangères sont distinctes, aucune contrainte ne s'oppose — et il reste
    un maître orphelin que personne ne regarde.

    ## Pourquoi un entrelacement décidé, et non une course

    Une première version lançait deux fils qui appelaient l'action ensemble.
    Dans le lanceur de tests Odoo, les deux se figeaient : le registre et le
    curseur de test ne se prêtent pas à des connexions concurrentes créées à la
    main, et le test échouait sur un délai plutôt que sur ce qu'il voulait dire.

    Un test qui dépend de l'ordonnanceur ne prouve d'ailleurs qu'un
    entrelacement parmi d'autres — celui du jour où il a tourné. On décide donc
    l'entrelacement, et on vérifie les deux moitiés séparément :

    1. le verrou est réellement pris : un curseur qui détient déjà la ligne fait
       expirer le second ;
    2. la relecture après verrou fonctionne : un curseur qui trouve la
       consolidation déjà liée rend l'existant sans rien créer.

    Ensemble, elles interdisent l'orphelin.
    """

    def setUp(self):
        super().setUp()
        self.senegal = self.env.ref("base.sn")
        self.france = self.env.ref("base.fr")
        Port = self.env["freight.port"]
        self.origine = Port.create({
            "name": "Concurrence Origine", "code": "CO1",
            "country_id": self.senegal.id, "air": True,
        })
        self.destination = Port.create({
            "name": "Concurrence Destination", "code": "CD1",
            "country_id": self.france.id, "air": True,
        })
        self.consolidation = self.env["dally.freight.consolidation"].create({
            "name": "CONCURRENCE-TEST", "transport_mode": "air",
            "direction": "export", "origin_location": "CO1",
            "destination_location": "CD1", "state": "collecting",
        })

    def test_deux_curseurs_reels_ne_laissent_aucun_maitre_orphelin(self):
        """Deux connexions distinctes, sur des données validées.

        Une première version créait la consolidation dans la transaction de
        test : l'autre connexion ne voyait aucune ligne, son `FOR UPDATE` ne
        trouvait rien à verrouiller et passait sans attendre. Le test réussissait
        pour la mauvaise raison. Une seconde lançait deux fils, qui se figeaient
        dans le lanceur Odoo.

        On travaille donc sur des enregistrements validés, avec deux connexions
        réelles et un entrelacement décidé — plus sûr qu'une course, dont on ne
        prouve jamais que l'ordre du jour.
        """
        import uuid

        from odoo import SUPERUSER_ID, api
        from odoo.sql_db import db_connect

        base = self.env.cr.dbname
        cree = {}
        # Ces enregistrements sont validés : ils survivent au rollback de la
        # transaction de test. Un suffixe unique évite qu'un nettoyage manqué
        # bloque l'exécution suivante sur `_name_company_unique`.
        jeton = uuid.uuid4().hex[:8].upper()
        code_origine = "V%s" % jeton[:3]
        code_destination = "W%s" % jeton[:3]

        preparation = db_connect(base).cursor()
        try:
            env = api.Environment(preparation, SUPERUSER_ID, {})
            origine = env["freight.port"].create({
                "name": "Verrou Origine %s" % jeton, "code": code_origine,
                "country_id": env.ref("base.sn").id, "air": True})
            destination = env["freight.port"].create({
                "name": "Verrou Destination %s" % jeton, "code": code_destination,
                "country_id": env.ref("base.fr").id, "air": True})
            consolidation = env["dally.freight.consolidation"].create({
                "name": "VERROU-CONCURRENCE-%s" % jeton, "transport_mode": "air",
                "direction": "export", "origin_location": code_origine,
                "destination_location": code_destination, "state": "collecting"})
            cree = {"consolidation": consolidation.id,
                    "ports": [origine.id, destination.id]}
            preparation.commit()
        finally:
            preparation.close()

        premier = db_connect(base).cursor()
        second = db_connect(base).cursor()
        try:
            # --- le premier prend le verrou et le garde ---
            env_premier = api.Environment(premier, SUPERUSER_ID, {})
            consolidation_1 = env_premier["dally.freight.consolidation"].browse(
                cree["consolidation"])
            consolidation_1.action_create_master_shipment()

            # --- le second se heurte au verrou, il ne double pas la création ---
            second.execute("SET LOCAL lock_timeout = '2s'")
            with self.assertRaises(psycopg2.errors.LockNotAvailable):
                second.execute(
                    "SELECT tk_master_shipment_id FROM dally_freight_consolidation "
                    "WHERE id = %s FOR UPDATE", [cree["consolidation"]])
            second.rollback()

            # --- le premier valide ; le second relit et trouve le maître ---
            premier.commit()
            env_second = api.Environment(second, SUPERUSER_ID, {})
            consolidation_2 = env_second["dally.freight.consolidation"].browse(
                cree["consolidation"])
            avant = env_second["freight.shipment"].search_count([])
            action = consolidation_2.action_create_master_shipment()
            second.commit()

            self.assertEqual(
                env_second["freight.shipment"].search_count([]), avant,
                "le second appel ne doit créer aucune expédition")

            maitres = env_second["freight.shipment"].search([
                ("operation", "=", "master"),
                ("source_location_id", "=", cree["ports"][0])])
            self.assertEqual(len(maitres), 1, "un seul maître, aucun orphelin")
            self.assertEqual(maitres, consolidation_2.tk_master_shipment_id)
            self.assertEqual(action["res_id"], maitres.id)
            self.assertTrue(maitres.dally_consolidation_id,
                            "le maître restant est bien rattaché")
        finally:
            for curseur in (premier, second):
                try:
                    curseur.close()
                except Exception:                      # noqa: BLE001
                    pass
            menage = db_connect(base).cursor()
            try:
                env = api.Environment(menage, SUPERUSER_ID, {})
                consolidation = env["dally.freight.consolidation"].browse(
                    cree["consolidation"])
                if consolidation.exists():
                    maitre = consolidation.tk_master_shipment_id
                    consolidation.write({"tk_master_shipment_id": False})
                    if maitre.exists():
                        maitre.freight_packages.unlink()
                        maitre.unlink()
                    consolidation.with_context(
                        _dally_consolidation_state_write=_CONSOLIDATION_STATE_WRITE_TOKEN,
                        _dally_consolidation_bypass=_CONSOLIDATION_BYPASS_TOKEN,
                    ).write({"state": "cancelled"})
                    consolidation.unlink()
                env["freight.port"].browse(cree.get("ports", [])).exists().unlink()
                menage.commit()
            except Exception:                          # noqa: BLE001
                # Un nettoyage muet laisserait des enregistrements validés
                # derrière lui. On le dit, et le test échoue : mieux vaut une
                # suite rouge qu'une base qui dérive sans que personne ne sache.
                menage.rollback()
                _logger.exception(
                    "Nettoyage des enregistrements validés du test de "
                    "concurrence impossible : %s / ports %s",
                    cree.get("consolidation"), cree.get("ports"))
                raise
            finally:
                menage.close()

    def test_le_perdant_rend_le_maitre_du_gagnant_sans_en_creer_un_second(self):
        """L'autre moitié : celui qui obtient le verrou après coup relit, trouve
        la consolidation déjà liée, et ne crée rien.

        C'est exactement l'état dans lequel se réveille le second appel d'une
        course réelle, une fois le premier validé.
        """
        # Le gagnant.
        self.consolidation.action_create_master_shipment()
        gagnant = self.consolidation.tk_master_shipment_id
        self.assertTrue(gagnant)

        # Le perdant : il repart d'un cache vide, comme une autre transaction.
        avant = self.env["freight.shipment"].search_count([])
        self.consolidation.invalidate_recordset()
        action = self.consolidation.action_create_master_shipment()

        self.assertEqual(self.consolidation.tk_master_shipment_id, gagnant)
        self.assertEqual(action["res_id"], gagnant.id)
        self.assertEqual(
            self.env["freight.shipment"].search_count([]), avant,
            "le perdant ne crée aucune expédition")

    def test_aucun_maitre_orphelin_sur_ces_ports(self):
        """L'invariante, dite telle qu'on la vérifierait en exploitation : sur
        cette route, il n'existe pas d'expédition maître sans consolidation."""
        self.consolidation.action_create_master_shipment()
        self.consolidation.invalidate_recordset()
        self.consolidation.action_create_master_shipment()

        maitres = self.env["freight.shipment"].search([
            ("operation", "=", "master"),
            ("source_location_id", "=", self.origine.id),
        ])
        self.assertEqual(len(maitres), 1)
        orphelins = maitres.filtered(lambda m: not m.dally_consolidation_id)
        self.assertFalse(orphelins, "aucune expédition maître sans consolidation")
