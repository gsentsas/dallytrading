# -*- coding: utf-8 -*-
"""L'expédition maître d'une consolidation.

Ce qui se joue ici n'est pas « le champ est-il rempli » mais « peut-on router
une consolidation au mauvais endroit sans que personne ne le voie ». Les cas de
refus comptent donc autant que le cas heureux, et davantage : un maître absent
se remarque, un maître mal routé se découvre à l'arrivée.
"""

from psycopg2 import errors
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.dally_freight_consolidation.models.consolidation import (
    _CONSOLIDATION_BYPASS_TOKEN,
    _CONSOLIDATION_STATE_WRITE_TOKEN,
)

from .common import ConsolidationCommon


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
