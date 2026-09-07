# -*- coding: utf-8 -*-
"""La preuve qu'un autre site ne peut pas agir avec le cookie de l'opérateur.

Ces tests passent par HTTP réel, et c'est indispensable : la barrière vit dans
``ir.http._pre_dispatch``, un point que seul un vrai routage traverse. Appeler
le service en Python ne prouverait rien.

Chaque refus est vérifié dans les deux sens — la requête hostile est refusée,
et la requête légitime qui n'en diffère que par l'en-tête incriminé passe. Un
test qui ne montrerait que le refus ne distinguerait pas une barrière d'une
route cassée.
"""

import json

from odoo.tests import HttpCase, tagged

from odoo.addons.dally_ops_mobile.models.ops_http import (
    METHODES_MUTANTES,
    PREFIXE_OPS,
)


@tagged("post_install", "-at_install", "dally")
class TestOpsCsrf(HttpCase):
    """La barrière inter-origine, éprouvée route par route et en-tête par en-tête."""

    MOT_DE_PASSE = "OpsCsrf!2026#probe"

    #: Une route mutante sans effet de bord observable : chercher un client ne
    #: crée rien. Ce qui est éprouvé ici, c'est la barrière, pas le métier.
    ROUTE = "/api/v1/ops/customers/search"

    def setUp(self):
        """Crée une session Ops réelle afin de tester la barrière HTTP."""
        super().setUp()
        self.operateur = self.env["res.users"].create({
            "name": "Gilles CSRF",
            "login": "ops.csrf",
            "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref(
                "dally_ops_mobile.group_dally_ops_logistician").id])],
        })
        self.authenticate("ops.csrf", self.MOT_DE_PASSE)

    def _poster(self, entetes=None, corps=None, route=None):
        """Un POST tel que la passerelle l'émet, sauf ce que le test change."""
        defaut = {"Content-Type": "application/json"}
        defaut.update(entetes or {})
        return self.url_open(
            route or self.ROUTE,
            data=json.dumps(corps if corps is not None else {"phone": "+221770000000"}),
            headers=defaut,
            allow_redirects=False,
            timeout=30,
        )

    # ------------------------------------------------------------------
    # Le vecteur réel : le formulaire HTML inter-site
    # ------------------------------------------------------------------

    def test_le_formulaire_texte_brut_est_refuse(self):
        """`text/plain` livre un corps JSON valide sans pré-vol CORS.

        C'est le vecteur exact : un formulaire HTML en
        ``enctype="text/plain"`` est une requête simple, le navigateur y joint
        le cookie, et les routes lisaient le corps brut sans regarder le type.
        """
        reponse = self._poster({"Content-Type": "text/plain"})
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(
            reponse.json()["error"]["code"], "cross_origin_refused")

    def test_le_formulaire_urlencode_est_refuse(self):
        """Un formulaire urlencoded ne peut pas atteindre une mutation Ops."""
        reponse = self._poster(
            {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(reponse.status_code, 403)

    def test_sans_content_type_est_refuse(self):
        """Un `Content-Type` absent ne vaut pas `application/json`."""
        reponse = self.url_open(
            self.ROUTE, data=json.dumps({"phone": "+221770000000"}),
            headers={"Content-Type": ""}, allow_redirects=False, timeout=30)
        self.assertEqual(reponse.status_code, 403)

    def test_le_json_de_la_passerelle_passe(self):
        """Le contre-test : mêmes cookie et corps, `application/json`, ça passe.

        Sans lui, les refus ci-dessus ne prouveraient pas que c'est le type de
        contenu qui décide — une route en panne les produirait aussi.
        """
        reponse = self._poster()
        self.assertNotEqual(reponse.status_code, 403)

    def test_le_parametre_du_content_type_ne_gene_pas(self):
        """`application/json; charset=utf-8` reste du JSON."""
        reponse = self._poster({"Content-Type": "application/json; charset=utf-8"})
        self.assertNotEqual(reponse.status_code, 403)

    def test_la_casse_du_content_type_ne_gene_pas(self):
        """Le type JSON reste admis indépendamment de sa casse."""
        reponse = self._poster({"Content-Type": "Application/JSON"})
        self.assertNotEqual(reponse.status_code, 403)

    # ------------------------------------------------------------------
    # L'origine
    # ------------------------------------------------------------------

    def test_une_origine_etrangere_est_refusee(self):
        """Même en JSON parfait : l'origine décide avant le type."""
        reponse = self._poster({"Origin": "https://attaquant.example"})
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(
            reponse.json()["error"]["code"], "cross_origin_refused")

    def test_l_origine_du_domaine_servi_passe(self):
        """L'origine égale à l'hôte servi est légitime."""
        reponse = self._poster({"Origin": self.base_url()})
        self.assertNotEqual(reponse.status_code, 403)

    def test_le_meme_hote_sur_un_autre_schema_est_refuse(self):
        """Même hôte mais autre schéma = autre origine, donc refus."""
        base = self.base_url()
        autre_schema = "https://" if base.startswith("http://") else "http://"
        origine = autre_schema + base.split("://", 1)[1]
        reponse = self._poster({"Origin": origine})
        self.assertEqual(reponse.status_code, 403)

    def test_l_absence_d_origine_passe(self):
        """La passerelle Next.js n'émet pas d'`Origin` : elle n'est pas un navigateur.

        C'est pourquoi la règle est « présent et étranger », et non
        « obligatoire ». La rendre obligatoire couperait la passerelle.
        """
        reponse = self._poster()
        self.assertNotIn("Origin", {})
        self.assertNotEqual(reponse.status_code, 403)

    def test_un_sous_domaine_voisin_est_refuse(self):
        """`ops.dallytrading.com` n'est pas `crm.dallytrading.com`.

        Le même site ne suffit pas : la comparaison porte sur l'autorité.
        """
        hote = self.base_url().split("://", 1)[1]
        reponse = self._poster({"Origin": "https://voisin.%s" % hote})
        self.assertEqual(reponse.status_code, 403)

    # ------------------------------------------------------------------
    # Le contexte de navigation
    # ------------------------------------------------------------------

    def test_un_contexte_croise_est_refuse(self):
        """Un contexte navigateur cross-site est refusé avant le contrôleur."""
        reponse = self._poster({"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(reponse.status_code, 403)

    def test_un_contexte_meme_origine_passe(self):
        """Un contexte same-origin reste compatible avec une mutation légitime."""
        reponse = self._poster({"Sec-Fetch-Site": "same-origin"})
        self.assertNotEqual(reponse.status_code, 403)

    def test_un_contexte_absent_passe(self):
        """Là encore, la passerelle n'en émet pas."""
        reponse = self._poster({"Sec-Fetch-Site": "none"})
        self.assertNotEqual(reponse.status_code, 403)

    # ------------------------------------------------------------------
    # Ce que la barrière ne doit pas casser
    # ------------------------------------------------------------------

    def test_une_lecture_n_est_pas_touchee(self):
        """`GET` reste libre : sans CORS, une page hostile ne lit pas la réponse."""
        reponse = self.url_open(
            "/api/v1/ops/me", headers={"Origin": "https://attaquant.example"},
            allow_redirects=False, timeout=30)
        self.assertNotEqual(reponse.status_code, 403)

    def test_une_route_hors_ops_n_est_pas_touchee(self):
        """La barrière est bornée à `/api/v1/ops/`.

        `/api/v1/freight/` s'authentifie par clé d'API : aucun identifiant
        ambiant n'y circule, donc rien à falsifier — et un pré-vol CORS
        empêcherait de toute façon un navigateur d'y joindre la clé. Le refus
        attendu ici est celui de la clé absente, jamais celui de l'origine.
        """
        reponse = self.url_open(
            "/api/v1/freight/sheet-outbox/ack", data="{}",
            headers={"Content-Type": "text/plain",
                     "Origin": "https://attaquant.example"},
            allow_redirects=False, timeout=30)
        corps = reponse.json()
        self.assertNotEqual(
            corps.get("error", {}).get("code"), "cross_origin_refused")
        # Et la requête a bien atteint le contrôleur d'API : sans cette
        # seconde assertion, le test passerait aussi si la route n'existait
        # plus. `request_id` n'est posé que par `DallyApiController`.
        self.assertIn("request_id", corps)

    def test_l_envoi_de_fichier_reste_possible(self):
        """`multipart/form-data` est exempté du contrôle de type.

        Un formulaire HTML sait l'émettre : le type ne discrimine donc rien
        ici, et l'exiger en JSON couperait l'envoi de photos. Ce sont
        `Origin` et `Sec-Fetch-Site` qui protègent ces deux routes — le test
        suivant le prouve.
        """
        reponse = self.url_open(
            "/api/v1/ops/intakes/INEXISTANT/photos",
            files={"file": ("p.jpg", b"\xff\xd8\xff", "image/jpeg")},
            data={"request_uuid": "x", "kind": "package"},
            allow_redirects=False, timeout=30)
        self.assertNotEqual(reponse.status_code, 403)

    def test_l_envoi_de_fichier_inter_origine_est_refuse(self):
        """Un multipart venant d’une origine étrangère reste refusé."""
        reponse = self.url_open(
            "/api/v1/ops/intakes/INEXISTANT/photos",
            files={"file": ("p.jpg", b"\xff\xd8\xff", "image/jpeg")},
            data={"request_uuid": "x", "kind": "package"},
            headers={"Origin": "https://attaquant.example"},
            allow_redirects=False, timeout=30)
        self.assertEqual(reponse.status_code, 403)

    # ------------------------------------------------------------------
    # La couverture : aucune route mutante ne doit échapper au préfixe
    # ------------------------------------------------------------------

    def test_toutes_les_routes_mutantes_ops_sont_couvertes(self):
        """Structurel : une route ajoutée demain hérite de la barrière.

        Le test lit le routage réel des contrôleurs plutôt qu'une liste écrite
        à la main — celle-ci vieillirait sans prévenir. Toute route mutante du
        module doit être soit sous `/api/v1/ops/`, donc protégée, soit
        authentifiée par clé d'API, donc sans identifiant ambiant à falsifier.
        """
        from odoo.addons.dally_ops_mobile import controllers as paquet

        echappees = []
        for module in vars(paquet).values():
            for objet in vars(module).values() if hasattr(module, "__dict__") else []:
                if not isinstance(objet, type):
                    continue
                for membre in vars(objet).values():
                    routage = getattr(membre, "original_routing", None)
                    if not routage:
                        continue
                    if not set(routage.get("methods") or []) & METHODES_MUTANTES:
                        continue
                    if routage.get("auth") == "none":
                        continue
                    echappees += [chemin for chemin in routage.get("routes") or []
                                  if not chemin.startswith(PREFIXE_OPS)]

        self.assertEqual(
            sorted(set(echappees)), [],
            "Ces routes mutantes échappent à la barrière inter-origine.")

    def test_le_recensement_de_couverture_voit_bien_les_routes(self):
        """Le test précédent serait vert s'il ne trouvait aucune route.

        Celui-ci lui interdit ce faux vert : le recensement doit compter au
        moins les vingt routes mutantes que l'audit a dénombrées.
        """
        from odoo.addons.dally_ops_mobile import controllers as paquet

        vues = []
        for module in vars(paquet).values():
            for objet in vars(module).values() if hasattr(module, "__dict__") else []:
                if not isinstance(objet, type):
                    continue
                for membre in vars(objet).values():
                    routage = getattr(membre, "original_routing", None)
                    if routage and set(routage.get("methods") or []) & METHODES_MUTANTES:
                        vues += routage.get("routes") or []

        self.assertGreaterEqual(len(set(vues)), 20, sorted(set(vues)))
