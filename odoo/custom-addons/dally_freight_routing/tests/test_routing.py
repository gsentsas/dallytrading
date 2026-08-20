# -*- coding: utf-8 -*-
"""Le formulaire intelligent, éprouvé mode par mode.

Trois choses peuvent mal tourner ici, et chacune a sa famille d'assertions.

**Le mode peut être mal déduit.** C'est la plus grave : tout le reste en
découle — les lieux proposés, les transporteurs, ce qui s'affiche. Six modes
sont donc vérifiés un par un, y compris les deux qui ne se déduisent pas du
service mais de la marchandise.

**Un domaine peut laisser passer ce qu'il devrait exclure.** Un test qui
vérifie qu'un port maritime apparaît en maritime ne prouve rien tant qu'on n'a
pas vérifié qu'il disparaît en aérien. Les deux sens sont donc mesurés, sur les
mêmes enregistrements réels.

**Le ménage peut ne pas se faire, ou se faire trop.** Changer de mode doit
vider ce qui devient faux et *seulement* cela ; et l'écriture directe, sans
passer par un écran, doit nettoyer comme le formulaire.
"""

import uuid

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightRouting(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partenaire = self.env["res.partner"].create({"name": "Client acheminement"})
        self.dakar = self.env.ref("dally_freight_data.port_sndkr")
        self.havre = self.env.ref("dally_freight_data.port_frleh")
        self.tanger = self.env.ref("dally_freight_data.port_maptm")
        self.dss = self.env.ref("dally_freight_data.airport_dss")
        self.cdg = self.env.ref("dally_freight_data.airport_cdg")
        self.route_mer = self.env.ref("dally_freight_data.route_frleh_sndkr")
        self.route_air = self.env.ref("dally_freight_data.route_cdg_dss")

    def _service(self, code):
        return self.env["dally.service.type"].search([("code", "=", code)], limit=1)

    def _devis(self, code_service, **valeurs):
        valeurs.setdefault("service_type_id", self._service(code_service).id)
        return self.env["dally.quote.request"].new(valeurs)

    def _expedition(self, mode, **valeurs):
        valeurs.update({"partner_id": self.partenaire.id, "transport_mode": mode})
        valeurs.setdefault("service_type_id", self._service("freight_sea").id)
        return self.env["dally.shipment"].create(valeurs)

    # ─── Les six modes ───────────────────────────────────────────────

    def test_sea(self):
        self.assertEqual(self._devis("freight_sea")._dally_transport(), "ocean")
        self.assertEqual(self._expedition("sea").freight_transport, "ocean")

    def test_air(self):
        self.assertEqual(self._devis("freight_air")._dally_transport(), "air")
        self.assertEqual(self._expedition("air").freight_transport, "air")

    def test_road(self):
        self.assertEqual(self._expedition("road").freight_transport, "land")

    def test_groupage_sea(self):
        devis = self._devis("freight_groupage", groupage_transport_mode="sea")
        self.assertEqual(devis._dally_transport(), "ocean")
        self.assertEqual(devis.port_domain, [("ocean", "=", True)])

    def test_groupage_air(self):
        devis = self._devis("freight_groupage", groupage_transport_mode="air")
        self.assertEqual(devis._dally_transport(), "air")
        self.assertEqual(devis.port_domain, [("air", "=", True)])

    def test_vehicle_suit_la_marchandise_et_non_le_service(self):
        """Un véhicule sur un roulier est du maritime ; sur un camion, du
        terrestre. Le service commercial est le même dans les deux cas."""
        devis = self.env["dally.quote.request"].create({
            "service_type_id": self._service("freight_vehicle").id,
            "partner_id": self.partenaire.id,
            "contact_name": "Client véhicule",
            "email": "vehicule@example.invalid",
            # Clé d'idempotence, obligatoire en base : c'est elle qui empêche
            # une soumission rejouée de créer une seconde demande.
            "request_uuid": str(uuid.uuid4()),
        })
        for mode_vehicule, attendu in (("sea", "ocean"), ("road", "land")):
            cargo = self.env["dally.freight.vehicle.cargo"].create({
                "quote_request_id": devis.id, "make": "Toyota", "model": "Hilux",
                "category": "car", "condition": "running",
                "transport_mode": mode_vehicule,
            })
            devis.invalidate_recordset()
            self.assertEqual(devis._dally_transport(), attendu, mode_vehicule)
            cargo.unlink()

    def test_un_service_sans_mode_ne_se_replie_sur_rien(self):
        """Ni maritime par défaut, ni domaine restreint : l'absence de mode se
        dit, elle ne se devine pas."""
        for code in ("logistics", "trade", "sourcing"):
            devis = self._devis(code)
            self.assertFalse(devis._dally_transport(), code)
            self.assertEqual(devis.port_domain, [])
            self.assertEqual(devis.carrier_domain, [])

    # ─── Domaines ────────────────────────────────────────────────────

    def test_pays_puis_regions(self):
        """La région proposée appartient au pays choisi, et à aucun autre."""
        senegal = self.env.ref("base.sn")
        regions = self.env["res.country.state"].search([("country_id", "=", senegal.id)])
        self.assertGreaterEqual(len(regions), 14)
        self.assertIn(self.env.ref("dally_freight_data.state_sn_dk"), regions)
        self.assertNotIn(self.env.ref("dally_freight_data.state_ci_ab"), regions)

    def test_une_region_d_un_autre_pays_est_retiree(self):
        expedition = self._expedition("sea")
        expedition.origin_country_id = self.env.ref("base.sn")
        expedition.origin_state_id = self.env.ref("dally_freight_data.state_sn_dk")
        expedition.origin_country_id = self.env.ref("base.ci")
        expedition._onchange_origin_country_routing()
        self.assertFalse(expedition.origin_state_id)

    def test_un_port_maritime_est_impossible_en_aerien(self):
        Lieu = self.env["freight.port"]
        domaine_air = self._expedition("air").port_domain
        self.assertFalse(Lieu.search_count(domaine_air + [("id", "=", self.dakar.id)]))
        self.assertTrue(Lieu.search_count(domaine_air + [("id", "=", self.dss.id)]))

    def test_un_aeroport_est_impossible_en_maritime(self):
        Lieu = self.env["freight.port"]
        domaine_mer = self._expedition("sea").port_domain
        self.assertFalse(Lieu.search_count(domaine_mer + [("id", "=", self.dss.id)]))
        self.assertTrue(Lieu.search_count(domaine_mer + [("id", "=", self.dakar.id)]))

    def test_le_lieu_n_est_pas_bride_au_pays(self):
        """Décision explicite : une expédition partie de Bamako s'embarque à
        Dakar. Filtrer les ports sur le pays d'origine interdirait le cas le
        plus courant de la sous-région."""
        expedition = self._expedition("sea", origin_country_id=self.env.ref("base.ml").id)
        self.assertTrue(self.env["freight.port"].search_count(
            expedition.port_domain + [("id", "=", self.dakar.id)]))

    def test_le_transporteur_suit_la_taxonomie(self):
        maritime = self._expedition("sea").carrier_domain
        routier = self._expedition("road").carrier_domain
        self.assertTrue(maritime and routier and maritime != routier)
        Partenaire = self.env["res.partner"]
        cma = self.env.ref("dally_freight_data.partner_cma_cgm")
        self.assertTrue(Partenaire.search_count(maritime + [("id", "=", cma.id)]))
        self.assertFalse(Partenaire.search_count(routier + [("id", "=", cma.id)]))

    def test_en_aerien_le_transporteur_partenaire_n_est_pas_filtre(self):
        """Il est masqué à l'écran : c'est `airline_id` qui fait foi. Un domaine
        vide plutôt qu'un domaine faux."""
        self.assertEqual(self._expedition("air").carrier_domain, [])

    # ─── Itinéraire fréquent ─────────────────────────────────────────

    def test_l_itineraire_propose_les_deux_lieux(self):
        expedition = self._expedition("sea")
        expedition.frequent_route_id = self.route_mer
        expedition._onchange_frequent_route_id()
        self.assertEqual(expedition.origin_port_id, self.havre)
        self.assertEqual(expedition.destination_port_id, self.dakar)

    def test_l_itineraire_n_ecrase_jamais_un_choix(self):
        expedition = self._expedition("sea", origin_port_id=self.tanger.id)
        expedition.frequent_route_id = self.route_mer
        expedition._onchange_frequent_route_id()
        self.assertEqual(expedition.origin_port_id, self.tanger)
        self.assertEqual(expedition.destination_port_id, self.dakar)

    def test_l_itineraire_reste_modifiable_ensuite(self):
        expedition = self._expedition("sea")
        expedition.frequent_route_id = self.route_mer
        expedition._onchange_frequent_route_id()
        expedition.origin_port_id = self.tanger
        self.assertEqual(expedition.origin_port_id, self.tanger)
        self.assertEqual(expedition.frequent_route_id, self.route_mer)

    def test_les_itineraires_proposes_suivent_le_mode(self):
        Route = self.env["freight.frequent.route"]
        domaine_air = self._expedition("air").frequent_route_domain
        self.assertTrue(Route.search_count(domaine_air + [("id", "=", self.route_air.id)]))
        self.assertFalse(Route.search_count(domaine_air + [("id", "=", self.route_mer.id)]))

    # ─── Ménage au changement de mode ────────────────────────────────

    def test_sea_vers_air_nettoie_ce_qui_devient_faux(self):
        navire = self.env["freight.vessel"].create({"name": "MV Test", "code": "TST-V1"})
        expedition = self._expedition("sea")
        expedition.write({
            "vessel_id": navire.id, "origin_port_id": self.dakar.id,
            "destination_port_id": self.havre.id,
            "carrier_partner_id": self.env.ref("dally_freight_data.partner_maersk").id,
            "frequent_route_id": self.route_mer.id,
        })
        expedition.write({"transport_mode": "air"})

        self.assertFalse(expedition.vessel_id)
        self.assertFalse(expedition.origin_port_id)
        self.assertFalse(expedition.destination_port_id)
        self.assertFalse(expedition.carrier_partner_id)
        self.assertFalse(expedition.frequent_route_id)
        self.assertEqual(expedition.freight_transport, "air")

    def test_air_vers_sea_nettoie_la_compagnie_aerienne(self):
        expedition = self._expedition("air")
        expedition.write({
            "airline_id": self.env.ref("dally_freight_data.airline_af").id,
            "origin_port_id": self.dss.id,
        })
        expedition.write({"transport_mode": "sea"})
        self.assertFalse(expedition.airline_id)
        self.assertFalse(expedition.origin_port_id)

    def test_le_menage_ne_touche_pas_ce_qui_reste_vrai(self):
        """L'incoterm, la géographie et les quantités survivent : ils ne
        dépendent pas du mode."""
        expedition = self._expedition("sea")
        expedition.write({
            "incoterm_id": self.env.ref("account.incoterm_FOB").id,
            "origin_country_id": self.env.ref("base.sn").id,
            "origin_state_id": self.env.ref("dally_freight_data.state_sn_dk").id,
            "origin_city": "Dakar", "weight_kg": 1200.0,
        })
        expedition.write({"transport_mode": "air"})
        self.assertTrue(expedition.incoterm_id)
        self.assertEqual(expedition.origin_country_id, self.env.ref("base.sn"))
        self.assertTrue(expedition.origin_state_id)
        self.assertEqual(expedition.origin_city, "Dakar")
        self.assertEqual(expedition.weight_kg, 1200.0)

    def test_le_menage_a_lieu_meme_sans_formulaire(self):
        """Une écriture directe — RPC, import, provisionnement — doit nettoyer
        comme l'écran, sinon l'enregistrement se contredit en silence."""
        navire = self.env["freight.vessel"].create({"name": "MV RPC", "code": "TST-V2"})
        expedition = self._expedition("sea")
        expedition.write({"vessel_id": navire.id})
        self.env["dally.shipment"].browse(expedition.id).write({"transport_mode": "road"})
        self.assertFalse(expedition.vessel_id)

    # ─── Compatibilité ───────────────────────────────────────────────

    def test_les_champs_texte_historiques_survivent(self):
        expedition = self._expedition("sea", origin_city="Bamako",
                                      destination_city="Le Havre",
                                      carrier_name="Transporteur historique")
        self.assertEqual(expedition.origin_city, "Bamako")
        self.assertEqual(expedition.carrier_name, "Transporteur historique")
        expedition.write({"transport_mode": "air"})
        self.assertEqual(expedition.origin_city, "Bamako")
        self.assertEqual(expedition.carrier_name, "Transporteur historique")

    def test_le_lieu_alimente_la_ville_sans_l_ecraser(self):
        vide = self._expedition("sea")
        vide.origin_port_id = self.dakar
        vide._onchange_origin_port_id()
        self.assertEqual(vide.origin_city, self.dakar.city)

        saisie = self._expedition("sea", origin_city="Rufisque")
        saisie.origin_port_id = self.dakar
        saisie._onchange_origin_port_id()
        self.assertEqual(saisie.origin_city, "Rufisque")

    def test_le_transporteur_alimente_son_miroir_texte(self):
        expedition = self._expedition("sea")
        expedition.carrier_partner_id = self.env.ref("dally_freight_data.partner_maersk")
        expedition._onchange_carrier_partner_id()
        self.assertEqual(expedition.carrier_name, "Maersk")

    # ─── Les écrans se construisent ──────────────────────────────────

    def test_les_formulaires_se_construisent(self):
        for modele in ("dally.quote.request", "dally.shipment"):
            vues = self.env[modele].get_views(
                [(None, "form"), (None, "list"), (None, "search")])
            self.assertEqual(len(vues["views"]), 3, modele)
            arch = vues["views"]["form"]["arch"]
            for champ in ("origin_port_id", "destination_port_id",
                          "incoterm_id", "frequent_route_id"):
                self.assertIn(champ, arch, "%s / %s" % (modele, champ))
