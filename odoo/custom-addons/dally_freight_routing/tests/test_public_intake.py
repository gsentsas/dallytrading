# -*- coding: utf-8 -*-
"""Ce que le formulaire public a le droit d'envoyer, et de recevoir.

Deux sens, deux familles d'assertions.

**Ce qui sort** — les projections publiques. Chaque test vérifie non seulement
que les champs attendus sont là, mais qu'il n'y en a **aucun autre** : c'est la
seule formulation qui résiste à l'ajout d'un champ par une mise à jour du
fournisseur.

**Ce qui entre** — le payload. Le navigateur envoie des codes, jamais des
identifiants, et chaque code est résolu puis confronté au mode déduit du
service. Un port maritime déclaré sur une demande aérienne doit donc être
écarté, et pas seulement ignoré à l'affichage : c'est ce que ces tests
mesurent, sur des demandes réellement créées.
"""

import uuid

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestPublicIntake(TransactionCase):

    #: Rien de ce qui relève de la qualification commerciale ne doit sortir.
    INTERDITS = (
        "carrier", "vessel", "airline", "shipping", "route", "cost", "margin",
        "price", "partner", "owner", "id", "internal", "note",
    )

    def setUp(self):
        super().setUp()
        self.Devis = self.env["dally.quote.request"]

    def _soumettre(self, **payload):
        base = {
            "service_code": "freight_sea",
            "last_name": "Client public",
            "email": "public@example.invalid",
            "request_uuid": str(uuid.uuid4()),
        }
        base.update(payload)
        return self.Devis.dally_create_from_website(base)

    # ─── Ce qui sort ─────────────────────────────────────────────────

    def test_les_pays_ne_portent_que_code_et_nom(self):
        pays = self.env["res.country"]._dally_public_countries()
        self.assertGreater(len(pays), 200)
        for entree in pays[:20]:
            self.assertEqual(set(entree), {"code", "name"})

    def test_les_subdivisions_exigent_un_pays(self):
        self.assertEqual(self.env["res.country.state"]._dally_public_states(""), [])
        self.assertEqual(self.env["res.country.state"]._dally_public_states(None), [])

        senegal = self.env["res.country.state"]._dally_public_states("SN")
        self.assertGreaterEqual(len(senegal), 14)
        self.assertIn("Dakar", [e["name"] for e in senegal])
        for entree in senegal:
            self.assertEqual(set(entree), {"code", "name"})

    def test_les_lieux_sont_filtres_par_mode(self):
        Lieu = self.env["freight.port"]
        maritimes = {e["code"] for e in Lieu._dally_public_locations("sea")}
        aeriens = {e["code"] for e in Lieu._dally_public_locations("air")}

        self.assertIn("SNDKR", maritimes)
        self.assertNotIn("SNDKR", aeriens)
        self.assertIn("DSS", aeriens)
        self.assertNotIn("DSS", maritimes)
        self.assertFalse(maritimes & aeriens)

    def test_un_mode_inconnu_ne_donne_rien(self):
        """Un paramètre incompris ne doit jamais élargir une réponse."""
        self.assertEqual(
            self.env["freight.port"]._dally_public_locations("ocean"), [])
        self.assertEqual(
            self.env["freight.port"]._dally_public_locations("../etc"), [])

    def test_aucune_projection_ne_laisse_fuir_de_champ_interne(self):
        jeux = [
            self.env["res.country"]._dally_public_countries(),
            self.env["res.country.state"]._dally_public_states("SN"),
            self.env["account.incoterms"]._dally_public_incoterms(),
            self.env["freight.port"]._dally_public_locations(),
        ]
        for donnees in jeux:
            cles = set().union(*[set(e) for e in donnees]) if donnees else set()
            for cle in cles:
                if cle in ("code", "country_code", "state_code"):
                    continue
                for interdit in self.INTERDITS:
                    self.assertNotIn(interdit, cle, "%s dans %s" % (interdit, cles))

    def test_les_lieux_publient_les_drapeaux_en_vocabulaire_client(self):
        """Le navigateur n'a pas à connaître le mot « ocean »."""
        dakar = next(
            e for e in self.env["freight.port"]._dally_public_locations()
            if e["code"] == "SNDKR")
        self.assertEqual(
            set(dakar),
            {"code", "name", "city", "country_code", "state_code", "sea", "air", "road"})
        self.assertTrue(dakar["sea"])
        self.assertFalse(dakar["air"])

    # ─── Ce qui entre ────────────────────────────────────────────────

    def test_maritime_france_vers_senegal(self):
        devis = self._soumettre(
            origin_country_code="FR", origin_city="Le Havre", origin_port_code="FRLEH",
            destination_country_code="SN", destination_city="Dakar",
            destination_state_code="DK", destination_port_code="SNDKR",
            incoterm_code="FOB",
        )
        self.assertEqual(devis.origin_port_id.code, "FRLEH")
        self.assertEqual(devis.destination_port_id.code, "SNDKR")
        self.assertEqual(devis.destination_state_id.code, "DK")
        self.assertEqual(devis.incoterm_id.code, "FOB")
        # Les champs texte historiques restent renseignés tels quels.
        self.assertEqual(devis.origin_city, "Le Havre")
        self.assertEqual(devis.destination_city, "Dakar")

    def test_aerien_cdg_vers_dss(self):
        devis = self._soumettre(
            service_code="freight_air",
            origin_port_code="CDG", destination_port_code="DSS")
        self.assertEqual(devis.origin_port_id.code, "CDG")
        self.assertEqual(devis.destination_port_id.code, "DSS")

    def test_groupage_maritime_et_aerien(self):
        mer = self._soumettre(
            service_code="freight_groupage", groupage_transport_mode="sea",
            origin_port_code="FRLEH", destination_port_code="SNDKR")
        self.assertEqual(
            (mer.origin_port_id.code, mer.destination_port_id.code), ("FRLEH", "SNDKR"))

        air = self._soumettre(
            service_code="freight_groupage", groupage_transport_mode="air",
            origin_port_code="CDG", destination_port_code="DSS")
        self.assertEqual(
            (air.origin_port_id.code, air.destination_port_id.code), ("CDG", "DSS"))

    def test_un_port_maritime_est_ecarte_sur_une_demande_aerienne(self):
        devis = self._soumettre(
            service_code="freight_air",
            origin_port_code="FRLEH", destination_port_code="DSS")
        self.assertFalse(devis.origin_port_id)
        self.assertEqual(devis.destination_port_id.code, "DSS")

    def test_un_aeroport_est_ecarte_sur_une_demande_maritime(self):
        devis = self._soumettre(origin_port_code="CDG", destination_port_code="SNDKR")
        self.assertFalse(devis.origin_port_id)
        self.assertEqual(devis.destination_port_id.code, "SNDKR")

    def test_un_groupage_maritime_ecarte_un_aeroport(self):
        devis = self._soumettre(
            service_code="freight_groupage", groupage_transport_mode="sea",
            origin_port_code="CDG")
        self.assertFalse(devis.origin_port_id)

    def test_un_identifiant_ne_vaut_pas_un_code(self):
        """Le navigateur ne peut pas désigner un enregistrement par son id."""
        dakar = self.env.ref("dally_freight_data.port_sndkr")
        devis = self._soumettre(origin_port_code=str(dakar.id))
        self.assertFalse(devis.origin_port_id)

    def test_les_codes_inconnus_sont_ignores_sans_faire_echouer(self):
        devis = self._soumettre(
            origin_port_code="INEXISTANT", destination_state_code="ZZ",
            incoterm_code="ZZZ")
        self.assertTrue(devis.reference)
        self.assertFalse(devis.origin_port_id)
        self.assertFalse(devis.destination_state_id)
        self.assertFalse(devis.incoterm_id)

    def test_une_region_est_cherchee_dans_son_pays(self):
        """« DK » n'existe qu'au Sénégal ici ; sans le pays, il ne désigne rien."""
        avec = self._soumettre(
            destination_country_code="SN", destination_state_code="DK")
        self.assertEqual(avec.destination_state_id.code, "DK")

        sans = self._soumettre(destination_state_code="DK")
        self.assertFalse(sans.destination_state_id)

    def test_enlevement_livraison_et_date(self):
        devis = self._soumettre(
            pickup_requested="true", pickup_address="12 quai de Southampton",
            delivery_requested="true", delivery_address="3 avenue de la Gare",
            desired_date="2026-09-15")
        self.assertTrue(devis.pickup_requested)
        self.assertEqual(devis.pickup_address, "12 quai de Southampton")
        self.assertTrue(devis.delivery_requested)
        self.assertEqual(str(devis.desired_date), "2026-09-15")

    def test_une_date_invalide_est_ignoree(self):
        devis = self._soumettre(desired_date="demain")
        self.assertFalse(devis.desired_date)

    def test_le_vehicule_conserve_son_lieu_tant_que_le_mode_est_inconnu(self):
        """Rien n'est deviné, donc rien n'est effacé.

        Le mode d'un transport de véhicule se lit sur la cargaison, qui n'existe
        pas encore au moment de l'admission. Il n'y a alors aucune contradiction
        à détecter : un port déclaré par le client est conservé tel quel.
        """
        devis = self._soumettre(
            service_code="freight_vehicle", origin_port_code="SNDKR")
        self.assertFalse(devis._dally_transport())
        self.assertEqual(devis.origin_port_id.code, "SNDKR")

    def test_le_lieu_est_retire_quand_la_cargaison_declare_un_mode_incompatible(self):
        """Le nettoyage arrive avec l'information, pas avant.

        `vehicle_cargo_id` est un champ calculé : il n'apparaît jamais dans une
        écriture, et la demande ne peut donc pas surveiller elle-même le
        changement. C'est la cargaison qui la prévient.
        """
        devis = self._soumettre(
            service_code="freight_vehicle", origin_port_code="SNDKR")
        self.assertEqual(devis.origin_port_id.code, "SNDKR")

        self.env["dally.freight.vehicle.cargo"].create({
            "quote_request_id": devis.id, "make": "Toyota", "model": "Hilux",
            "category": "car", "condition": "running", "transport_mode": "road",
        })
        devis.invalidate_recordset()
        self.assertEqual(devis._dally_transport(), "land")
        self.assertFalse(devis.origin_port_id)

    def test_le_lieu_survit_a_une_cargaison_compatible(self):
        devis = self._soumettre(
            service_code="freight_vehicle", origin_port_code="SNDKR")
        self.env["dally.freight.vehicle.cargo"].create({
            "quote_request_id": devis.id, "make": "Toyota", "model": "Hilux",
            "category": "car", "condition": "running", "transport_mode": "sea",
        })
        devis.invalidate_recordset()
        self.assertEqual(devis._dally_transport(), "ocean")
        self.assertEqual(devis.origin_port_id.code, "SNDKR")

    def test_aucun_champ_interne_n_est_accepte_du_public(self):
        """Même envoyés, ils ne doivent atteindre aucun champ."""
        dakar = self.env.ref("dally_freight_data.port_sndkr")
        devis = self._soumettre(
            carrier_partner_id=1, vessel_id=1, airline_id=1,
            frequent_route_id=1, origin_port_code="SNDKR")
        self.assertEqual(devis.origin_port_id, dakar)
        self.assertFalse(devis.carrier_partner_id)
        self.assertFalse(devis.vessel_id)
        self.assertFalse(devis.airline_id)
        self.assertFalse(devis.frequent_route_id)
