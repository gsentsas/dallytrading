"""
Tests de non-régression du confinement de `tk_freight`.

Chaque test rejoue une attaque **effectivement réussie** contre le module nu,
mesurée en stack jetable et consignée dans `docs/evaluations/TK-FREIGHT-EVALUATION.md`
partie II. Ce ne sont donc pas des hypothèses : ce sont des régressions connues.

Deux précautions de méthode, apprises en produisant ces mesures :

1. **Le cache ORM d'Odoo est porté par la transaction, pas par l'utilisateur.**
   Une valeur lue sous un utilisateur est resservie à un autre sans nouveau
   contrôle d'accès. Sans `invalidate_all()` entre les sondes, ces tests
   mesureraient le cache et passeraient à tort.
2. **Un refus n'est pas forcément un refus de sécurité.** On exige
   `AccessError` explicitement : un `ValueError` sur un champ inexistant ferait
   passer un test qui ne prouve rien.
"""

import base64

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged


class TkLockdownCommon(TransactionCase):
    """Deux clients portail distincts et une expédition appartenant au second."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groupe_portail = cls.env.ref("base.group_portal")

        cls.societe_a = cls.env["res.partner"].create({"name": "Bridge Societe A"})
        cls.societe_b = cls.env["res.partner"].create({"name": "Bridge Societe B"})

        cls.client_a = cls.env["res.users"].create(
            {
                "name": "Bridge Portal A",
                "login": "bridge.a@dally.invalid",
                "partner_id": cls.societe_a.id,
                "group_ids": [(6, 0, [groupe_portail.id])],
            }
        )
        cls.client_b = cls.env["res.users"].create(
            {
                "name": "Bridge Portal B",
                "login": "bridge.b@dally.invalid",
                "partner_id": cls.societe_b.id,
                "group_ids": [(6, 0, [groupe_portail.id])],
            }
        )

        # Expédition de B : c'est la cible que A ne doit atteindre par aucun
        # chemin — ni directement, ni par ses lignes rattachées.
        cls.expedition_b = cls.env["freight.shipment"].create(
            {
                "transport": "ocean",
                "operation": "direct",
                "ocean_shipment_type": "lcl",
                "consignee_id": cls.societe_b.id,
            }
        )
        cls.colis_b = cls.env["shipment.package.line"].create(
            {"shipment_id": cls.expedition_b.id, "qty": 1}
        )
        cls.document_b = cls.env["freight.documents"].create(
            {
                "freight_id": cls.expedition_b.id,
                "file_name": "contrat-confidentiel-b.pdf",
                "document": base64.b64encode(b"CANARI_DOCUMENT_DE_B").decode(),
            }
        )

    def _sous_a(self, modele):
        """Environnement du client A, cache vidé — voir l'en-tête, point 1."""
        self.env.invalidate_all()
        return self.env(user=self.client_a)[modele]


@tagged("post_install", "-at_install", "dally_freight")
class TestConfinementOrm(TkLockdownCommon):
    """Le portail ne doit atteindre aucun modèle fret par l'ORM."""

    def test_client_ne_lit_pas_expedition_d_autrui(self):
        with self.assertRaises(AccessError):
            self._sous_a("freight.shipment").browse(self.expedition_b.id).read(["name"])

    def test_client_ne_lit_pas_colis_d_autrui(self):
        """Régression mesurée : lecture autorisée sur le module nu."""
        with self.assertRaises(AccessError):
            self._sous_a("shipment.package.line").browse(self.colis_b.id).read(["qty"])

    def test_client_ne_modifie_pas_colis_d_autrui(self):
        """Régression mesurée : écriture autorisée sur le module nu.

        Le champ visé existe réellement — voir l'en-tête, point 2.
        """
        with self.assertRaises(AccessError):
            self._sous_a("shipment.package.line").browse(self.colis_b.id).write(
                {"carrier_seal": "MODIFIE_PAR_UN_TIERS"}
            )

    def test_client_n_exfiltre_pas_le_document_d_autrui(self):
        """La régression la plus grave : contenu binaire, pas seulement le nom.

        Sur le module nu, le canari était restitué mot pour mot.
        """
        with self.assertRaises(AccessError):
            self._sous_a("freight.documents").browse(self.document_b.id).read(
                ["document"]
            )

    def test_client_ne_modifie_pas_la_configuration_globale(self):
        """Un client renommait les incoterms de toute l'instance."""
        incoterm = self.env["freight.incoterms"].search([], limit=1)
        if not incoterm:
            incoterm = self.env["freight.incoterms"].create({"name": "FOB"})
        with self.assertRaises(AccessError):
            self._sous_a("freight.incoterms").browse(incoterm.id).write(
                {"name": "MODIFIE_PAR_UN_CLIENT"}
            )

    def test_aucune_recherche_ne_renvoie_de_ligne(self):
        """`search` ne doit pas se contenter de filtrer : l'accès est retiré."""
        for modele in (
            "freight.shipment",
            "freight.documents",
            "shipment.invoice",
            "shipment.quotation",
            "shipment.freight.booking",
            "shipment.package.line",
        ):
            with self.subTest(modele=modele), self.assertRaises(AccessError):
                self._sous_a(modele).search([])

    def test_le_garde_fou_ne_signale_aucune_ouverture(self):
        ouverts = self.env["dally.freight.lockdown.guard"]._dally_audit_portal_access()
        self.assertEqual(
            ouverts,
            [],
            "Des droits portail subsistent sur des modeles tk_freight. "
            "tk_freight a probablement ete mis a jour sans dally_freight_bridge.",
        )


@tagged("post_install", "-at_install", "dally_freight")
class TestConfinementRoutes(HttpCase):
    """Aucune route `tk_freight` ne doit servir de contenu métier.

    Retirer un lien d'interface ne ferme rien : ces requêtes visent les URL
    directement, comme le ferait quelqu'un qui les a lues dans le code source
    du module, public sur GitHub.

    ## Pourquoi on n'exige pas un 404 partout

    Une première version de ces tests exigeait exactement 404 et signalait
    quatre régressions. Vérification faite sur les corps de réponse, les quatre
    étaient des refus, obtenus **avant** d'atteindre le gestionnaire neutralisé :

    * les POST sans jeton sont rejetés en 400 par le contrôle CSRF du noyau,
      qui s'exécute avant la route ;
    * les routes de détail utilisent un convertisseur `<model(...)>`, qui
      résout l'enregistrement avant le gestionnaire et lève `AccessError` —
      403 — puisque le portail n'a plus d'ACL sur ces modèles.

    Exiger 404 mesurerait donc *par où* le refus arrive, ce qui est un détail
    d'implémentation. Ce qui compte est vérifié ici : la réponse n'est pas un
    succès, et elle ne contient aucune donnée métier.

    Effet de bord accepté et documenté : le 403 nomme le modèle interne
    (« freight.shipment »). C'est une divulgation mineure, à un utilisateur
    authentifié, sur un module dont le code est public. La refermer imposerait
    de dupliquer les routes avec un autre convertisseur, au prix d'une
    ambiguïté de routage — remède plus risqué que le mal.
    """

    #: Contenu qui ne doit apparaître dans aucune réponse.
    CONTENU_INTERDIT = ("Shipment Details", "OCEAN/", "BOOKING/", "FQ/")

    def _refuse(self, reponse, url):
        self.assertNotEqual(
            reponse.status_code,
            200,
            f"{url} repond en succes : une route tk_freight est rouverte.",
        )
        for marqueur in self.CONTENU_INTERDIT:
            self.assertNotIn(
                marqueur,
                reponse.text,
                f"{url} renvoie du contenu metier tiers ({marqueur}).",
            )

    def test_le_suivi_public_ne_repond_plus(self):
        """Sur le module nu : 200 et page de détail, sans authentification.

        La référence étant séquentielle, la route était un oracle
        d'énumération de tout le carnet d'expéditions.
        """
        for url in ("/shipment", "/track/shipment", "/track/shipment/OCEAN-2026-08-1"):
            with self.subTest(url=url):
                self._refuse(self.url_open(url), url)

    def test_les_routes_de_mutation_sans_csrf_ne_repondent_plus(self):
        """Sur le module nu, ce POST sans jeton créait une cotation réelle."""
        self.authenticate("admin", "admin")
        url = "/freight/shipment/booking/submit"
        avant = self.env["shipment.quotation"].sudo().search_count([])
        self._refuse(self.url_open(url, data={"shipper_id": "1"}), url)
        # Le point decisif n'est pas le code HTTP mais l'absence de mutation :
        # sur le module nu, ce POST creait une cotation reelle.
        self.assertEqual(
            self.env["shipment.quotation"].sudo().search_count([]),
            avant,
            "Le POST sans jeton a cree un enregistrement : csrf=False reste exploitable.",
        )

    def test_la_route_post_comment_ne_repond_plus(self):
        """IDOR présente dans le code du fournisseur, aujourd'hui masquée par
        un plantage (`fields.datetime`, absent d'Odoo 19). Un plantage n'est
        pas un contrôle : la route est fermée explicitement."""
        self.authenticate("admin", "admin")
        url = "/post/comment"
        avant = self.env["booking.line"].sudo().search_count([])
        self._refuse(self.url_open(url, data={"book_id": "1", "comment": "x"}), url)
        self.assertEqual(
            self.env["booking.line"].sudo().search_count([]),
            avant,
            "Un commentaire a ete cree sur un booking tiers.",
        )

    def test_les_listes_et_details_portail_ne_repondent_plus(self):
        self.authenticate("admin", "admin")
        for url in (
            "/freight/shipment/booking",
            "/freight/shipment/bookings",
            "/freight/shipment/quotation",
            "/freight/shipment/shipment",
            "/freight/shipment/booking/create",
            "/freight/shipment/shipment/details/1",
            "/freight/shipment/booking/details/1",
            "/freight/shipment/quotation/details/1",
        ):
            with self.subTest(url=url):
                self._refuse(self.url_open(url), url)


@tagged("post_install", "-at_install", "dally_freight")
class TestGardeFouRoutes(TransactionCase):
    """Le garde-fou doit voir arriver une route que le pont ne couvre pas.

    Vérifier que les 17 routes connues sont neutralisées ne protège que du
    passé. Ce test simule ce qu'une mise à jour du fournisseur ferait : ajouter
    une méthode portant une route destinée au client, sans que personne ne
    pense à la neutraliser.
    """

    def test_une_nouvelle_route_vendeur_est_detectee(self):
        from odoo import http
        from odoo.addons.tk_freight.controllers import main as tk_main

        garde = self.env["dally.freight.lockdown.guard"]
        self.assertEqual(
            garde._dally_audit_tk_routes(),
            [],
            "L'instance part deja avec des routes non couvertes.",
        )

        @http.route(
            ["/freight/nouvelle/route/client"],
            type="http",
            auth="public",
            website=True,
        )
        def route_ajoutee_par_une_mise_a_jour(self, **kw):  # pragma: no cover
            return "ne doit jamais etre servi"

        tk_main.BookingsCustom.route_ajoutee_par_une_mise_a_jour = (
            route_ajoutee_par_une_mise_a_jour
        )
        try:
            ouvertes = garde._dally_audit_tk_routes()
            self.assertIn(
                "/freight/nouvelle/route/client",
                ouvertes,
                "Une route vendeur ajoutee n'est pas detectee par le garde-fou.",
            )
        finally:
            # La classe du fournisseur est un objet de processus : ne pas la
            # restaurer contaminerait tous les tests suivants.
            del tk_main.BookingsCustom.route_ajoutee_par_une_mise_a_jour

        self.assertEqual(
            garde._dally_audit_tk_routes(),
            [],
            "L'etat du garde-fou n'a pas ete restaure.",
        )

    def test_l_allowlist_de_routes_reste_vide(self):
        """Le portail DallyTrading ne consomme aucune route du fournisseur.

        Une allowlist non vide serait le premier pas vers un chemin client qui
        traverse le moteur tiers.
        """
        from odoo.addons.dally_freight_bridge.models.lockdown_guard import (
            ROUTES_AUTORISEES,
        )

        self.assertEqual(ROUTES_AUTORISEES, frozenset())
