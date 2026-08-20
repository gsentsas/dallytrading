# -*- coding: utf-8 -*-
"""Les référentiels livrés, vérifiés sur ce qui peut réellement casser.

Un module de données n'a pas de logique : le tester revient à vérifier que ce
qui a été écrit est ce qui arrive en base, et surtout que le rejouer ne crée
rien en double. Trois familles d'assertions :

* **présence** — les enregistrements sont là, en nombre, et joignables par leur
  identifiant XML ; c'est cet identifiant qui rend le seeder idempotent, donc
  sa stabilité est le vrai contrat du module ;
* **cohérence** — les codes respectent l'unicité que le fournisseur impose, les
  itinéraires reliant deux lieux du même mode ;
* **abstention** — ce que le module ne doit *pas* faire : aucun navire, aucun
  transporteur routier inventé, aucun incoterm touché, aucun droit portail
  rouvert sur les modèles du fournisseur.

La dernière famille est la moins spectaculaire et la plus utile. Un seeder qui
en fait trop ne se voit pas : il ajoute des lignes que personne n'a demandées et
que tout le monde finit par croire vraies.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestFreightMasterData(TransactionCase):

    #: Les pays dont ce module crée les subdivisions, et leur compte attendu.
    SUBDIVISIONS = {
        "sn": 14, "ci": 14, "ml": 11, "bf": 13, "gn": 8,
        "tg": 5, "bj": 12, "ne": 8, "gh": 16, "ma": 12,
    }

    def _ref(self, nom):
        return self.env.ref("dally_freight_data.%s" % nom)

    # ─── Subdivisions ────────────────────────────────────────────────

    def test_subdivisions_creees_pour_les_dix_pays(self):
        total = 0
        for code_pays, attendu in self.SUBDIVISIONS.items():
            pays = self.env.ref("base.%s" % code_pays)
            obtenu = self.env["res.country.state"].search_count(
                [("country_id", "=", pays.id)])
            self.assertGreaterEqual(
                obtenu, attendu,
                "%s : %d subdivisions au lieu de %d" % (pays.name, obtenu, attendu))
            total += attendu
        self.assertEqual(total, 113)

    def test_les_codes_de_subdivision_sont_uniques_par_pays(self):
        """L'unicité est une contrainte SQL : ce test protège d'un doublon de
        données, pas du modèle."""
        for code_pays in self.SUBDIVISIONS:
            pays = self.env.ref("base.%s" % code_pays)
            etats = self.env["res.country.state"].search(
                [("country_id", "=", pays.id)])
            codes = etats.mapped("code")
            self.assertEqual(len(codes), len(set(codes)), pays.name)

    def test_quelques_subdivisions_nommement(self):
        """Un échantillon lisible : si les identifiants XML changent, ceci casse."""
        self.assertEqual(self._ref("state_sn_dk").name, "Dakar")
        self.assertEqual(self._ref("state_ci_ab").name, "Abidjan")
        self.assertEqual(self._ref("state_ml_bko").name, "Bamako")
        self.assertEqual(self._ref("state_gh_aa").name, "Greater Accra")
        self.assertEqual(self._ref("state_ma_06").name, "Casablanca-Settat")

    # ─── Lieux ───────────────────────────────────────────────────────

    def test_les_ports_maritimes_sont_livres(self):
        ports = self.env["freight.port"].search([("ocean", "=", True)])
        self.assertGreaterEqual(len(ports), 19)
        dakar = self._ref("port_sndkr")
        self.assertEqual(dakar.code, "SNDKR")
        self.assertTrue(dakar.ocean)
        self.assertFalse(dakar.air)
        self.assertEqual(dakar.country_id, self.env.ref("base.sn"))
        self.assertEqual(dakar.state_id, self._ref("state_sn_dk"))

    def test_les_aeroports_sont_livres(self):
        aeroports = self.env["freight.port"].search([("air", "=", True)])
        self.assertGreaterEqual(len(aeroports), 9)
        dss = self._ref("airport_dss")
        self.assertEqual(dss.code, "DSS")
        self.assertTrue(dss.air)
        self.assertFalse(dss.ocean)

    def test_chaque_lieu_porte_au_moins_un_mode(self):
        """Le fournisseur l'impose ; un lieu sans mode serait injoignable."""
        for lieu in self.env["freight.port"].search([]):
            self.assertTrue(lieu.ocean or lieu.air or lieu.land, lieu.name)

    def test_les_codes_de_lieu_sont_uniques_toutes_natures_confondues(self):
        codes = [l.code for l in self.env["freight.port"].search([]) if l.code]
        self.assertEqual(len(codes), len(set(codes)))

    # ─── Compagnies ──────────────────────────────────────────────────

    def test_les_compagnies_aeriennes_sont_livrees(self):
        self.assertGreaterEqual(self.env["freight.airline"].search_count([]), 13)
        af = self._ref("airline_af")
        self.assertEqual((af.code, af.icao), ("AF", "AFR"))
        self.assertEqual(af.country, self.env.ref("base.fr"))

    def test_aucune_capacite_ni_type_d_appareil_invente(self):
        """Ces deux champs existent chez le fournisseur mais n'ont pas de sens
        au niveau d'une compagnie ; les laisser vides est délibéré."""
        for compagnie in self.env["freight.airline"].search([]):
            self.assertFalse(compagnie.aircraft_type, compagnie.name)
            self.assertFalse(compagnie.capacity, compagnie.name)

    def test_les_compagnies_maritimes_sont_des_partenaires_etiquetes(self):
        etiquette = self._ref("partner_category_shipping_line")
        compagnies = self.env["res.partner"].search(
            [("category_id", "in", etiquette.ids)])
        self.assertGreaterEqual(len(compagnies), 7)
        for c in compagnies:
            self.assertTrue(c.is_company, c.name)
            self.assertTrue(c.country_id, c.name)

    def test_la_taxonomie_est_hierarchique(self):
        for nom in ("shipping_line", "road_carrier", "customs_broker"):
            categorie = self._ref("partner_category_%s" % nom)
            self.assertEqual(categorie.parent_id,
                             self._ref("partner_category_freight"))
        self.assertEqual(self._ref("partner_category_freight").parent_id,
                         self._ref("partner_category_dally"))

    def test_aucun_transporteur_routier_invente(self):
        """L'étiquette existe, le référentiel reste vide : les vrais
        transporteurs seront saisis quand ils travailleront avec nous."""
        etiquette = self._ref("partner_category_road_carrier")
        self.assertEqual(
            self.env["res.partner"].search_count(
                [("category_id", "in", etiquette.ids)]), 0)

    # ─── Itinéraires ─────────────────────────────────────────────────

    def test_les_itineraires_relient_deux_lieux_du_meme_mode(self):
        routes = self.env["freight.frequent.route"].search([])
        self.assertGreaterEqual(len(routes), 10)
        for route in routes:
            depart, arrivee = route.source_location_id, route.destination_location_id
            self.assertTrue(depart and arrivee, route.name)
            self.assertNotEqual(depart, arrivee, route.name)
            self.assertTrue(
                (depart.ocean and arrivee.ocean) or (depart.air and arrivee.air),
                "%s relie deux modes différents" % route.name)

    def test_le_nom_d_itineraire_suit_le_format_du_fournisseur(self):
        """`onchange` ne se déclenche pas dans un fichier de données : le nom
        est écrit à la main, et doit ressembler à une saisie manuelle."""
        for route in self.env["freight.frequent.route"].search([]):
            attendu = "%s - %s" % (route.source_location_id.name,
                                   route.destination_location_id.name)
            self.assertEqual(route.name, attendu)

    # ─── Abstentions ─────────────────────────────────────────────────

    def test_aucun_navire_livre(self):
        """Les navires n'apparaissent qu'avec une opération réelle."""
        self.assertEqual(self.env["freight.vessel"].search_count([]), 0)

    def test_les_incoterms_du_fournisseur_ne_sont_pas_peuples(self):
        """`account.incoterms` fait référence ; en remplir un second serait
        se donner deux vérités."""
        natifs = self.env["account.incoterms"].search_count([])
        self.assertGreaterEqual(natifs, 11)
        for xmlid in self.env["ir.model.data"].search([
                ("module", "=", "dally_freight_data")]):
            self.assertNotEqual(xmlid.model, "freight.incoterms")
            self.assertNotEqual(xmlid.model, "account.incoterms")

    def test_aucun_droit_portail_sur_les_modeles_du_fournisseur(self):
        """Le confinement de `tk_freight` doit tenir après ce module.

        L'invariant n'est pas « aucune ligne d'ACL » — le pont laisse les lignes
        du fournisseur en place et remet leurs quatre permissions à zéro, parce
        qu'écraser l'enregistrement par son identifiant XML est le seul moyen
        d'annuler un droit additif. L'invariant est « aucune permission
        accordée », et c'est le garde-fou du pont qui en fait foi : l'interroger
        vaut mieux que le réécrire ici, où la formulation dériverait.
        """
        anomalie = self.env["dally.freight.lockdown.guard"]._dally_audit_message()
        self.assertIsNone(anomalie, anomalie)

    def test_le_module_ne_declare_aucun_modele(self):
        """Sa raison d'être est de remplir, pas de créer."""
        self.assertEqual(
            self.env["ir.model.data"].search_count([
                ("module", "=", "dally_freight_data"), ("model", "=", "ir.model")]), 0)
