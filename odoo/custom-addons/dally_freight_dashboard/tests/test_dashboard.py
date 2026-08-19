# -*- coding: utf-8 -*-
"""Le tableau de bord, éprouvé sur la seule promesse qui compte.

Un indicateur ne vaut que si l'écran qu'il ouvre contient exactement ce qu'il
annonce. Tout le reste — la couleur de la tuile, la place du chiffre — se
corrige en regardant. Un écart entre le compteur et la liste, non : il ne se
voit pas, il s'accumule, et il finit par faire prendre une décision sur un
chiffre faux.

Ces tests portent donc, dans l'ordre :

* **la parité** — pour chaque carte et chaque profil, le compteur est comparé au
  nombre de lignes que l'action rend réellement, avec les droits de ce profil ;
* **l'absence de lien mort** — chaque carte visible ouvre quelque chose, y
  compris quand elle affiche zéro ;
* **le cloisonnement** — ce qu'un profil ne peut pas lire ne se compte pas et
  ne s'affiche pas, et le tableau de bord lui-même reste fermé au portail ;
* **la cohérence des données** — un code déclaré dans `CARTES` sans
  enregistrement, ou l'inverse, produirait une tuile morte ou une carte
  invisible ; les deux sont vérifiés dans les deux sens.
"""

import uuid

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_freight_dashboard.models.dally_freight_dashboard import CARTES


@tagged("post_install", "-at_install", "dally")
class TestFreightDashboard(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Carte = self.env["dally.freight.dashboard"]
        self.partenaire = self.env["res.partner"].create({"name": "Client tableau"})
        self.service_mer = self._service("freight_sea")

        # Les compteurs sont mesurés en **écart**, jamais en valeur absolue.
        # Une base d'essai n'est pas vide — elle porte les données des autres
        # tests et parfois celles d'une exploration manuelle — et un test qui
        # attend « 4 » échoue alors pour une raison qui n'a rien à voir avec ce
        # qu'il prétend vérifier.
        self.avant = {code: carte.count
                      for code, carte in self._cartes_par_code().items()}

        # Un jeu de données volontairement asymétrique : des compteurs tous
        # égaux laisseraient passer une inversion de domaine.
        for mode, etat, combien in (
            ("sea", "in_transit", 3), ("air", "arrived", 2), ("road", "customs", 1),
            ("groupage", "delivered", 2), ("vehicle", "cancelled", 1),
            ("sea", "available", 1),
        ):
            for _ in range(combien):
                self._expedition(mode, etat)
        for etat, combien in (("new", 4), ("qualified", 2), ("quoted", 1), ("won", 1)):
            for _ in range(combien):
                self._demande(etat)
        self.env.flush_all()

    def _cartes_par_code(self):
        self.Carte.invalidate_model()
        return {carte.code: carte for carte in self.Carte.search([])}

    def _ecart(self, code):
        """De combien cette carte a-t-elle augmenté depuis le début du test ?"""
        return self._cartes_par_code()[code].count - self.avant[code]

    def _service(self, code):
        return self.env["dally.service.type"].search([("code", "=", code)], limit=1)

    def _expedition(self, mode, etat):
        return self.env["dally.shipment"].create({
            "partner_id": self.partenaire.id, "transport_mode": mode,
            "service_type_id": self.service_mer.id, "state": etat,
        })

    def _demande(self, etat):
        return self.env["dally.quote.request"].create({
            "service_type_id": self.service_mer.id, "contact_name": "Client",
            "email": "tableau@example.invalid", "request_uuid": str(uuid.uuid4()),
            "state": etat,
        })

    def _utilisateur(self, nom, groupe):
        return self.env["res.users"].create({
            "name": nom, "login": "dash.%s@dallytrading.invalid" % nom,
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id, self.env.ref(groupe).id])],
        })

    # ─── Cohérence des données ───────────────────────────────────────

    def test_chaque_code_declare_a_son_enregistrement(self):
        codes_en_base = set(self.Carte.search([]).mapped("code"))
        self.assertEqual(codes_en_base, set(CARTES),
                         "CARTES et le fichier de données ont divergé")

    def test_les_dix_sept_cartes_demandees_existent(self):
        attendues = {
            "quote_requests", "to_qualify", "quotations", "bookings", "shipments",
            "sea", "air", "road", "groupage", "vehicle",
            "in_transit", "arrived", "customs", "available",
            "out_for_delivery", "delivered", "cancelled",
        }
        self.assertEqual(set(CARTES), attendues)

    # ─── Aucun lien mort ─────────────────────────────────────────────

    def test_chaque_carte_ouvre_une_action_utilisable(self):
        for carte in self.Carte.search([]):
            action = carte.action_open()
            self.assertEqual(action["type"], "ir.actions.act_window", carte.code)
            self.assertIn(action["res_model"], self.env, carte.code)
            self.assertIsInstance(action["domain"], list, carte.code)
            self.assertIn("list", action["view_mode"], carte.code)

    def test_une_carte_vide_ouvre_une_liste_vide_sans_erreur(self):
        carte = self.Carte.search([("code", "=", "out_for_delivery")])
        self.assertEqual(carte.count, 0)
        action = carte.action_open()
        self.assertEqual(
            self.env[action["res_model"]].search_count(action["domain"]), 0)

    # ─── Parité, la propriété centrale ───────────────────────────────

    def _verifier_parite(self, utilisateur):
        Carte = self.Carte.with_user(utilisateur)
        visibles = Carte.search([("available", "=", True)])
        self.assertTrue(visibles, "aucune carte visible")
        for carte in visibles:
            action = carte.action_open()
            reel = self.env[action["res_model"]].with_user(utilisateur).search_count(
                action["domain"])
            self.assertEqual(
                carte.count, reel,
                "%s annonce %s et ouvre %s" % (carte.code, carte.count, reel))

    def test_parite_pour_un_commercial(self):
        self._verifier_parite(
            self._utilisateur("commercial", "dally_trade.group_dally_trade_user"))

    def test_parite_pour_la_logistique(self):
        self._verifier_parite(
            self._utilisateur("logistique", "dally_core.group_dally_logistics"))

    def test_parite_pour_un_manager(self):
        self._verifier_parite(
            self._utilisateur("manager", "dally_core.group_dally_manager"))

    def test_parite_en_lecture_seule(self):
        self._verifier_parite(
            self._utilisateur("lecture", "dally_core.group_dally_readonly"))

    # ─── Les domaines comptent bien ce qu'ils prétendent ─────────────

    def test_les_modes_comptent_leur_mode(self):
        for code, attendu in (("sea", 4), ("air", 2), ("road", 1),
                              ("groupage", 2), ("vehicle", 1)):
            self.assertEqual(self._ecart(code), attendu, code)

    def test_les_etapes_comptent_leur_etat(self):
        for code, attendu in (("in_transit", 3), ("arrived", 2), ("customs", 1),
                              ("available", 1), ("delivered", 2),
                              ("cancelled", 1), ("out_for_delivery", 0)):
            self.assertEqual(self._ecart(code), attendu, code)

    def test_le_pipeline_compte_les_demandes_de_fret(self):
        self.assertEqual(self._ecart("quote_requests"), 8)
        self.assertEqual(self._ecart("to_qualify"), 4)
        self.assertEqual(self._ecart("quotations"), 3)

    def test_une_demande_hors_fret_n_est_pas_comptee(self):
        """Le périmètre est le préfixe du service, pas une liste close."""
        avant = self._cartes_par_code()["quote_requests"].count
        self.env["dally.quote.request"].create({
            "service_type_id": self._service("trade").id, "contact_name": "Négoce",
            "email": "negoce@example.invalid", "request_uuid": str(uuid.uuid4()),
        })
        self.assertEqual(self._cartes_par_code()["quote_requests"].count, avant)

    # ─── Cloisonnement ───────────────────────────────────────────────

    def test_le_portail_n_atteint_pas_le_tableau_de_bord(self):
        portail = self.env["res.users"].create({
            "name": "Portail", "login": "dash.portail@dallytrading.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        self.assertFalse(self.Carte.with_user(portail).has_access("read"))
        with self.assertRaises(AccessError):
            self.Carte.with_user(portail).search([])

    def test_les_compteurs_respectent_les_regles_d_enregistrement(self):
        """Sans `sudo`, un lecteur ne compte que ce qu'il pourrait lister.

        Le portail a une règle « mes expéditions » : ses compteurs doivent donc
        tomber à zéro sur des dossiers qui ne sont pas les siens, alors que le
        total en base ne l'est pas. C'est la preuve que le chiffre est calculé
        avec ses droits et non en superutilisateur.
        """
        portail = self.env["res.users"].create({
            "name": "Portail compteur", "login": "dash.pcount@dallytrading.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        self.assertGreater(self.env["dally.shipment"].sudo().search_count([]), 0)
        self.assertEqual(
            self.env["dally.shipment"].with_user(portail).search_count([]), 0)

    def test_une_carte_dont_le_modele_est_illisible_est_indisponible(self):
        """`available` repose sur le droit de lire le modèle source.

        Le portail est le seul profil qui échoue vraiment sur un modèle du
        fournisseur — le confinement lui retire toute ACL tk. Il ne voit pas le
        tableau de bord non plus, si bien qu'on ne peut pas observer la tuile
        disparaître de son écran : on éprouve donc le prédicat qui la fait
        disparaître, et le fait que le modèle lui est bien fermé.
        """
        portail = self.env["res.users"].create({
            "name": "Portail booking", "login": "dash.pb@dallytrading.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        carte = self.Carte.search([("code", "=", "bookings")])
        modele, _domaine = carte._dally_carte()
        self.assertEqual(modele, "shipment.freight.booking")

        self.assertFalse(
            self.env["shipment.freight.booking"].with_user(portail).has_access("read"))
        self.assertFalse(carte.with_user(portail)._dally_lisible(modele))
        # Et un modèle qui n'existe pas ne rend jamais une carte disponible.
        self.assertFalse(carte._dally_lisible("modele.inexistant"))

    # ─── Le tableau de bord du fournisseur ───────────────────────────

    def test_le_menu_du_fournisseur_est_retire(self):
        menu = self.env.ref("tk_freight.dasboard_id")
        self.assertFalse(menu.active, "le tableau de bord fournisseur est visible")

    def test_le_menu_du_fournisseur_ne_figure_plus_dans_l_arborescence(self):
        """Désactivé ne suffit pas à affirmer « invisible » : on le vérifie là
        où l'utilisateur regarde, c'est-à-dire dans le menu qu'Odoo lui rend."""
        menu = self.env.ref("tk_freight.dasboard_id")
        utilisateur = self._utilisateur("menu", "dally_core.group_dally_readonly")
        visibles = self.env["ir.ui.menu"].with_user(utilisateur).search([])
        self.assertNotIn(menu, visibles)

    def test_l_action_du_fournisseur_reste_intacte(self):
        """Le menu part, l'action reste : rien n'est supprimé chez le
        fournisseur, et elle reste joignable pour qui la cherche."""
        action = self.env.ref(
            "tk_freight.action_freight_dashboard", raise_if_not_found=False)
        self.assertTrue(action, "l'action du fournisseur a disparu")
        self.assertEqual(action._name, "ir.actions.client")

    def test_le_tableau_de_bord_dally_est_visible(self):
        menu = self.env.ref("dally_freight_dashboard.menu_dally_freight_dashboard")
        self.assertTrue(menu.active)
        utilisateur = self._utilisateur("visible", "dally_core.group_dally_readonly")
        visibles = self.env["ir.ui.menu"].with_user(utilisateur).search([])
        self.assertIn(menu, visibles)

    def test_ce_module_n_elargit_aucun_droit(self):
        """Ses ACL ne portent que sur son propre modèle.

        Un module qui masque un écran n'a aucune raison de toucher aux droits ;
        l'écrire ici évite qu'une ligne s'y glisse plus tard sans être vue.
        """
        acl = self.env["ir.model.access"].search([("id", "in", [
            data.res_id for data in self.env["ir.model.data"].search([
                ("module", "=", "dally_freight_dashboard"),
                ("model", "=", "ir.model.access"),
            ])
        ])])
        self.assertTrue(acl)
        for regle in acl:
            self.assertEqual(regle.model_id.model, "dally.freight.dashboard")
        # Et aucune règle d'enregistrement, aucun groupe créé.
        for modele in ("ir.rule", "res.groups"):
            self.assertFalse(self.env["ir.model.data"].search_count([
                ("module", "=", "dally_freight_dashboard"), ("model", "=", modele)]))

    def test_le_tableau_de_bord_ignore_le_negoce(self):
        """Ni coût, ni marge, ni opportunité : aucune carte n'y touche."""
        for _code, (modele, _domaine, _libelle, _groupe) in CARTES.items():
            self.assertFalse(modele.startswith("dally.trade"), modele)
