# -*- coding: utf-8 -*-
"""La chaîne d'authentification terrain, éprouvée par HTTP réel.

Ce qui se vérifie ici ne se vérifie nulle part ailleurs : qu'un compte **non
interne** — sans `base.group_user`, donc sans les 186 modèles du socle — peut
malgré tout se connecter, tenir une session, franchir `auth="user"` et être
reconnu comme opérateur.

C'est la preuve dont dépend toute l'architecture Ops. Si elle ne tenait pas,
il faudrait revenir à des comptes internes et accepter une surface de lecture
bien plus large sur des téléphones d'entrepôt.
"""

import json

from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, tagged


from .common import (
    MODELES_METIER_FERMES,
    MODELES_TECHNIQUES_LISIBLES,
    modeles_lisibles,
)

@tagged("post_install", "-at_install", "dally")
class TestOpsIdentity(HttpCase):

    #: Un mot de passe de banc, jamais réutilisé ailleurs.
    MOT_DE_PASSE = "OpsProbe!2026#sess"

    def setUp(self):
        super().setUp()
        self.logisticien = self._compte(
            "ops.logi", "Gilles Test",
            ["dally_ops_mobile.group_dally_ops_logistician"])
        self.responsable = self._compte(
            "ops.resp", "Dalanda Test",
            ["dally_ops_mobile.group_dally_ops_supervisor"])
        self.etranger = self._compte("ops.etranger", "Sans rôle", ["base.group_user"])

    def _compte(self, login, nom, groupes):
        """Un compte **non interne** dès que le rôle Ops suffit.

        `group_ids` en remplacement complet : ne pas ajouter `base.group_user`
        est tout l'intérêt du montage.
        """
        return self.env["res.users"].create({
            "name": nom,
            "login": login,
            "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [self.env.ref(g).id for g in groupes])],
        })

    def _appel(self, login=None):
        """Se connecte si demandé, puis appelle la route."""
        if login:
            self.authenticate(login, self.MOT_DE_PASSE)
        else:
            self.authenticate(None, None)
        return self.url_open("/api/v1/ops/me")

    # ─── La preuve centrale ──────────────────────────────────────────

    def test_un_compte_non_interne_est_bien_non_interne(self):
        self.assertTrue(self.logisticien.share)
        self.assertFalse(self.logisticien.has_group("base.group_user"))
        self.assertTrue(
            self.logisticien.has_group("dally_ops_mobile.group_dally_ops_logistician"))

    def test_un_compte_non_interne_ne_lit_aucun_modele(self):
        """186 modèles pour un compte interne, zéro ici. C'est la raison d'être
        de ce montage."""
        self.assertEqual(
            modeles_lisibles(self.env, self.logisticien),
            set(MODELES_TECHNIQUES_LISIBLES),
            "la liste blanche technique a changé")

    def test_le_logisticien_obtient_son_identite(self):
        reponse = self._appel("ops.logi")
        self.assertEqual(reponse.status_code, 200)
        charge = json.loads(reponse.content)

        self.assertTrue(charge["success"])
        donnees = charge["data"]
        self.assertEqual(donnees["user"]["id"], self.logisticien.id)
        self.assertEqual(donnees["user"]["name"], "Gilles Test")
        self.assertEqual(donnees["user"]["login"], "ops.logi")
        self.assertEqual(donnees["role"], "logistician")

    def test_le_responsable_est_reconnu_comme_tel(self):
        reponse = self._appel("ops.resp")
        self.assertEqual(reponse.status_code, 200)
        donnees = json.loads(reponse.content)["data"]
        self.assertEqual(donnees["role"], "supervisor")
        self.assertTrue(donnees["capabilities"]["supervise"])

    # ─── Refus ───────────────────────────────────────────────────────

    def test_un_utilisateur_sans_role_ops_est_refuse(self):
        reponse = self._appel("ops.etranger")
        self.assertEqual(reponse.status_code, 403)
        charge = json.loads(reponse.content)
        self.assertFalse(charge["success"])
        self.assertEqual(charge["error"]["code"], "forbidden")

    def test_le_refus_ne_renseigne_pas_sur_les_groupes(self):
        """Un refus n'a pas à décrire la structure des droits."""
        texte = self._appel("ops.etranger").text
        for indice in ("group_", "logistician", "supervisor", "res.groups"):
            self.assertNotIn(indice, texte, indice)

    def test_un_anonyme_est_renvoye_vers_la_connexion(self):
        """Comportement documenté : `auth="user"` sur une route `type="http"`
        ne rend pas 401 mais redirige vers la page de connexion d'Odoo. Le BFF
        n'a donc jamais à interpréter le corps — un code hors 200 suffit à
        conclure que la session est absente ou expirée.
        """
        self.authenticate(None, None)
        # Sans suivre la redirection : `url_open` la suit par défaut et
        # ramènerait la page de connexion en 200, ce qui masquerait ce qui se
        # passe réellement.
        reponse = self.url_open("/api/v1/ops/me", allow_redirects=False)
        self.assertIn(reponse.status_code, (301, 302, 303, 307, 308, 401, 403))
        self.assertNotIn("cash_actor", reponse.text)

        # Et en suivant la redirection, on atterrit sur la connexion, jamais
        # sur l'identité.
        suivie = self.url_open("/api/v1/ops/me")
        self.assertNotIn("cash_actor", suivie.text)

    # ─── L'exception technique, sur le compte non interne ────────────

    def test_l_exception_technique_est_exactement_res_currency(self):
        """L'invariant, énoncé sur le sujet qui compte.

        Ce fichier est le seul dont l'utilisateur est **non interne** : sans
        `base.group_user`, sans groupe de lecture. C'est donc ici que
        l'affirmation « zéro modèle métier, une seule exception technique »
        se vérifie sur le bon compte.
        """
        self.assertTrue(self.logisticien.share)
        self.assertEqual(
            modeles_lisibles(self.env, self.logisticien),
            set(MODELES_TECHNIQUES_LISIBLES))

    def test_res_currency_est_lisible_et_rien_de_plus(self):
        """La seule exception, et sa portée exacte."""
        Devise = self.env["res.currency"].with_user(self.logisticien)
        self.assertTrue(Devise.has_access("read"))
        for operation in ("write", "create", "unlink"):
            self.assertFalse(
                Devise.has_access(operation),
                "res.currency ne doit être accessible qu'en lecture (%s)" % operation)

    def test_res_currency_ne_peut_pas_etre_mutee(self):
        """Le droit de lire l'arrondi n'est pas celui de le changer."""
        devise = self.env["res.currency"].search([], limit=1)
        vue_par_ops = devise.with_user(self.logisticien)
        self.assertTrue(vue_par_ops.name)

        with self.assertRaises(AccessError):
            vue_par_ops.write({"rounding": 0.5})
        with self.assertRaises(AccessError):
            self.env["res.currency"].with_user(self.logisticien).create(
                {"name": "XXT", "symbol": "X"})
        with self.assertRaises(AccessError):
            vue_par_ops.unlink()

    def test_les_modeles_metier_restent_fermes(self):
        """Ce que l'exception technique n'a surtout pas ouvert."""
        for nom in MODELES_METIER_FERMES:
            if nom not in self.env.registry:
                continue
            with self.subTest(modele=nom):
                self.assertFalse(
                    self.env[nom].with_user(self.logisticien).has_access("read"),
                    "%s est devenu lisible" % nom)

    def test_les_taux_de_change_restent_fermes(self):
        """`res.currency.rate` est une donnée commerciale ; l'arrondi non."""
        self.assertNotIn("res.currency.rate", MODELES_TECHNIQUES_LISIBLES)
        self.assertFalse(
            self.env["res.currency.rate"].with_user(self.logisticien).has_access("read"))

    # ─── L'acteur de caisse ──────────────────────────────────────────

    def test_l_application_s_ouvre_sans_acteur_configure(self):
        """Ne pas bloquer la connexion : seules les opérations de caisse
        exigeront l'identité."""
        donnees = json.loads(self._appel("ops.logi").content)["data"]
        self.assertIsNone(donnees["cash_actor"])
        self.assertFalse(donnees["cash_actor_configured"])

    def test_l_acteur_configure_apparait(self):
        self.logisticien.sudo().dally_ops_cash_actor = "Gilles"
        donnees = json.loads(self._appel("ops.logi").content)["data"]
        self.assertEqual(donnees["cash_actor"], "Gilles")
        self.assertTrue(donnees["cash_actor_configured"])

    def test_un_nom_parlant_ne_vaut_pas_un_acteur(self):
        """« Gilles » dans le nom affiché ne configure rien."""
        self.assertEqual(self.logisticien.name, "Gilles Test")
        donnees = json.loads(self._appel("ops.logi").content)["data"]
        self.assertIsNone(donnees["cash_actor"])

    def test_le_renommage_ne_change_pas_l_acteur(self):
        self.logisticien.sudo().dally_ops_cash_actor = "Gilles"
        self.logisticien.sudo().name = "Gilles DUPONT"
        donnees = json.loads(self._appel("ops.logi").content)["data"]
        self.assertEqual(donnees["cash_actor"], "Gilles")

    def test_les_espaces_sont_retires_et_le_vide_refuse(self):
        self.logisticien.sudo().dally_ops_cash_actor = "  Gilles  "
        self.assertEqual(self.logisticien.dally_ops_cash_actor, "Gilles")
        with self.assertRaises(UserError):
            self.logisticien.sudo().dally_ops_cash_actor = "   "
        # Vider reste permis : on retire son acteur à qui quitte le poste.
        self.logisticien.sudo().dally_ops_cash_actor = False
        self.assertFalse(self.logisticien.dally_ops_cash_actor)

    def test_un_logisticien_ne_definit_pas_son_propre_acteur(self):
        """Sinon il imputerait ses dépenses à qui il veut."""
        with self.assertRaises(AccessError):
            self.logisticien.with_user(self.logisticien).write(
                {"dally_ops_cash_actor": "Alain"})

    def test_un_responsable_de_terrain_ne_le_definit_pas_non_plus(self):
        """Mesuré : aucun compte Ops n'écrit sur `res.users`.

        N'étant pas internes, ni le logisticien ni le responsable n'ont ce
        droit — l'ORM refuse avant même notre contrôle. Configurer l'acteur de
        caisse est donc une tâche d'administration, pas une action du terrain,
        et c'est cohérent : elle se fait une fois, à l'arrivée d'un opérateur.
        """
        self.assertFalse(
            self.env["res.users"].with_user(self.responsable).has_access("write"))
        with self.assertRaises(AccessError):
            self.logisticien.with_user(self.responsable).write(
                {"dally_ops_cash_actor": "Gilles"})

    def test_un_administrateur_interne_le_definit(self):
        """Le contrôle positif : sans lui, le test ci-dessus ne prouverait pas
        que le champ est configurable du tout."""
        administrateur = self.env["res.users"].create({
            "name": "Admin Ops", "login": "ops.admin",
            "password": self.MOT_DE_PASSE,
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("base.group_erp_manager").id,
                self.env.ref("dally_ops_mobile.group_dally_ops_supervisor").id,
            ])],
        })
        self.logisticien.with_user(administrateur).write(
            {"dally_ops_cash_actor": "Gilles"})
        self.assertEqual(self.logisticien.dally_ops_cash_actor, "Gilles")

    # ─── Le contrat de sortie ────────────────────────────────────────

    def test_la_charge_ne_contient_que_le_contrat(self):
        donnees = json.loads(self._appel("ops.logi").content)["data"]
        self.assertEqual(
            set(donnees),
            {"user", "role", "cash_actor", "cash_actor_configured", "capabilities"})
        self.assertEqual(set(donnees["user"]), {"id", "name", "login"})

    def test_la_charge_ne_laisse_fuir_ni_session_ni_portee(self):
        texte = self._appel("ops.logi").text
        for interdit in ("session_id", "password", "api_key", "freight:",
                         "group_", "scope", "csrf"):
            self.assertNotIn(interdit, texte, interdit)

    def test_les_capacites_sont_des_verbes_metier(self):
        capacites = json.loads(self._appel("ops.logi").content)["data"]["capabilities"]
        self.assertEqual(
            set(capacites),
            {"intake_create", "payment_create", "expense_create",
             "transfer_create", "appointment_manage", "supervise"})
        self.assertTrue(capacites["intake_create"])
        self.assertTrue(capacites["payment_create"])
        self.assertTrue(capacites["expense_create"])
        self.assertTrue(capacites["transfer_create"])
        self.assertTrue(capacites["appointment_manage"])
        # La supervision, elle, ne dépend pas d'un écran mais du rôle : un
        # logisticien ne la reçoit jamais, quel que soit le nombre d'écrans
        # ouverts.
        self.assertFalse(capacites["supervise"])

    def test_la_reponse_n_est_jamais_mise_en_cache(self):
        entetes = self._appel("ops.logi").headers
        self.assertIn("no-store", entetes.get("Cache-Control", ""))

    # ─── Aucune clé, aucun sudo ──────────────────────────────────────

    def test_la_route_ne_contient_aucun_sudo(self):
        """Le contrôleur lit l'utilisateur courant ; Odoo autorise déjà chacun
        à lire ses propres champs, même sans droit général sur `res.users`."""
        import inspect
        from odoo.addons.dally_ops_mobile.controllers import ops_identity
        source = inspect.getsource(ops_identity)
        self.assertNotIn("sudo(", source)

    def test_aucune_cle_d_api_n_est_requise(self):
        """Aucune portée Freight n'apparaît dans le contrôleur."""
        import inspect
        from odoo.addons.dally_ops_mobile.controllers import ops_identity
        source = inspect.getsource(ops_identity)
        for portee in ("freight:write", "freight:payment", "freight:cash",
                       "X-API-Key", "api_key"):
            self.assertNotIn(portee, source, portee)
