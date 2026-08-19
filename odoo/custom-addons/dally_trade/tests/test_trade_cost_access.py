# -*- coding: utf-8 -*-
"""Ouvrir le pipeline ne doit rien exiger qu'on n'ait le droit de savoir.

Un commercial ne pouvait plus ouvrir une affaire du tout :

    AccessError: DallyTrading Trade Cost (dally.trade.cost)

Les coûts étaient pourtant bien protégés — onglet et champs portaient
`groups=`, et l'architecture servie n'en contenait aucune trace. Mais
`get_view` renvoie aussi la liste des modèles que la vue utilise, et cette
liste est calculée **tous groupes confondus** puis mise en cache pour tout le
monde : le filtrage par groupe ne s'applique qu'à l'architecture. `get_views`
appelle ensuite `fields_get` sur chaque modèle annoncé, où notre garde de
schéma (`dally_portal`) exige une ACL de lecture.

D'où la règle que ce fichier surveille : **un modèle confidentiel ne doit
apparaître dans aucune vue qu'un non-autorisé peut charger**. Le masquage ne
suffit pas ; seule l'absence compte.

Les assertions vont donc par paires : ce que le refusé ne reçoit pas, et ce que
l'autorisé continue de recevoir. Une vérification qui ne peut pas échouer ne
prouve rien.
"""

import re

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import TradeCase


@tagged("post_install", "-at_install", "dally")
class TestTradeCostAccess(TradeCase):

    #: Les modèles dont la seule mention dans une vue suffit à bloquer.
    CONFIDENTIELS = ("dally.trade.cost", "dally.trade.commission")

    def setUp(self):
        super().setUp()
        base = self.env.ref("base.group_user").id

        def compte(nom, login, groupe):
            return self.env["res.users"].create({
                "name": nom, "login": login,
                "group_ids": [(6, 0, [base, self.env.ref(groupe).id])],
            })

        self.commercial = compte(
            "Commercial", "cost.commercial@dallytrading.test",
            "dally_trade.group_dally_trade_user")
        self.responsable = compte(
            "Trade Responsable", "cost.responsable@dallytrading.test",
            "dally_trade.group_dally_trade_manager")
        self.finance = compte(
            "Finance", "cost.finance@dallytrading.test",
            "dally_core.group_dally_finance")
        self.manager = compte(
            "Manager", "cost.manager@dallytrading.test",
            "dally_core.group_dally_manager")

        self.deal = self._deal()
        self._line(self.deal)
        self.cost = self.env["dally.trade.cost"].create({
            "opportunity_id": self.deal.id, "name": "Fret maritime",
            "amount": 1234.56,
        })
        self.commission = self.env["dally.trade.commission"].create({
            "opportunity_id": self.deal.id, "name": "Apporteur",
            "partner_id": self.broker.id, "fixed_amount": 99.0,
        })
        self.env.flush_all()

    def _vues(self, user, types=("kanban", "list", "form", "search")):
        return self.env["dally.trade.opportunity"].with_user(user).get_views(
            [(None, t) for t in types]
        )

    # ─── Le commercial : l'affaire s'ouvre ───────────────────────────

    def test_le_commercial_ouvre_le_pipeline(self):
        """Le test du bug signalé : plus aucune AccessError."""
        vues = self._vues(self.commercial)
        self.assertEqual(sorted(vues["views"]), ["form", "kanban", "list", "search"])

    def test_aucun_modele_confidentiel_annonce_au_commercial(self):
        """La cause exacte : c'est l'annonce, pas l'affichage, qui bloquait."""
        annonces = self._vues(self.commercial)["models"]
        for modele in self.CONFIDENTIELS:
            self.assertNotIn(modele, annonces)

    def test_aucun_modele_confidentiel_annonce_a_personne(self):
        """Y compris pour un autorisé : le cache d'annonce est partagé.

        C'est ce qui rend la correction robuste. Si l'annonce dépendait des
        droits, elle repasserait sur le dos du premier utilisateur à remplir
        le cache.
        """
        annonces = self._vues(self.responsable)["models"]
        for modele in self.CONFIDENTIELS:
            self.assertNotIn(modele, annonces)

    def test_aucun_champ_sensible_dans_les_architectures(self):
        """Ni coût, ni marge, ni prix d'achat — dans le HTML lui-même."""
        interdits = {"cost_ids", "commission_ids", "cost_total_analysis",
                     "commission_total_analysis", "gross_margin", "net_margin",
                     "margin_rate", "revenue_analysis", "purchase_subtotal",
                     "purchase_order_ids"}
        vues = self._vues(self.commercial, ("kanban", "list", "form", "search",
                                            "pivot", "graph"))
        for type_vue, vue in vues["views"].items():
            presents = set(re.findall(r'name="([a-z_][a-z0-9_]*)"', vue["arch"]))
            self.assertFalse(presents & interdits,
                             "%s laisse passer %s" % (type_vue, presents & interdits))

    def test_le_commercial_lit_ce_que_le_client_demande(self):
        """Un masquage CSS ne suffirait pas : on lit vraiment les champs.

        La spécification est celle que le client construit — les champs de
        l'architecture qu'on vient de lui servir — et la lecture doit aboutir
        sans lever, sinon la fiche ne s'ouvre pas.
        """
        vues = self._vues(self.commercial, ("form",))
        annonces = vues["models"]["dally.trade.opportunity"]["fields"]
        arch = vues["views"]["form"]["arch"]
        demandes = set(re.findall(r'name="([a-z_][a-z0-9_]*)"', arch)) & set(annonces)
        donnees = self.env["dally.trade.opportunity"].with_user(
            self.commercial).browse(self.deal.id).web_read(
                {f: {} for f in demandes})
        charge = repr(donnees)
        self.assertNotIn("1234.56", charge, "le coût est ressorti dans la charge RPC")
        self.assertNotIn(str(self.deal.purchase_subtotal), charge)

    def test_les_compteurs_restent_lisibles_sans_droits_financiers(self):
        """`sale_order_count` pilote un bloc de la fiche : il doit se lire.

        Il partageait son calcul avec `purchase_order_count`, protégé lui par
        `groups=` — demander l'un levait à cause de l'autre.
        """
        deal = self.env["dally.trade.opportunity"].with_user(
            self.commercial).browse(self.deal.id)
        self.assertEqual(deal.read(["sale_order_count"])[0]["sale_order_count"], 0)

    # ─── Le commercial : et rien de plus ─────────────────────────────

    def test_les_contournements_directs_sont_refuses(self):
        for modele in self.CONFIDENTIELS:
            with self.assertRaises(AccessError):
                self.env[modele].with_user(self.commercial).search_read([], ["id"])
            with self.assertRaises(AccessError):
                self.env[modele].with_user(self.commercial).fields_get()

    def test_marge_et_prix_achat_refuses_au_commercial(self):
        deal = self.env["dally.trade.opportunity"].with_user(
            self.commercial).browse(self.deal.id)
        for champ in ("net_margin", "gross_margin", "cost_total_analysis",
                      "purchase_subtotal"):
            with self.assertRaises(AccessError, msg=champ):
                deal.read([champ])

    # ─── Les autorisés : rien n'a été perdu ──────────────────────────

    def test_le_responsable_garde_acces_aux_couts(self):
        arch = self._vues(self.responsable, ("form",))["views"]["form"]["arch"]
        self.assertIn("action_view_costs", arch)
        self.assertIn("action_view_commissions", arch)

        deal = self.env["dally.trade.opportunity"].with_user(
            self.responsable).browse(self.deal.id)
        action = deal.action_view_costs()
        self.assertEqual(action["res_model"], "dally.trade.cost")
        self.assertEqual(action["context"]["default_opportunity_id"], self.deal.id)
        lignes = self.env["dally.trade.cost"].with_user(self.responsable).search(
            action["domain"])
        self.assertEqual(lignes, self.cost)
        self.assertEqual(deal.cost_count, 1)
        self.assertEqual(deal.commission_count, 1)

    def test_la_finance_voit_couts_et_marge(self):
        deal = self.env["dally.trade.opportunity"].with_user(
            self.finance).browse(self.deal.id)
        self.assertEqual(deal.cost_total_analysis, 1234.56)
        self.assertTrue(self._vues(self.finance, ("form",)))
        arch = self._vues(self.finance, ("form",))["views"]["form"]["arch"]
        self.assertIn("action_view_costs", arch)

    def test_le_manager_conserve_son_comportement(self):
        """Il n'est pas dans `INTERNAL_GROUPS` en propre, mais implique Finance."""
        arch = self._vues(self.manager, ("form",))["views"]["form"]["arch"]
        self.assertIn("action_view_costs", arch)
        deal = self.env["dally.trade.opportunity"].with_user(
            self.manager).browse(self.deal.id)
        self.assertEqual(deal.cost_count, 1)

    def test_le_calcul_de_marge_survit_a_une_ecriture_de_commercial(self):
        """Les champs stockés se calculent en superutilisateur.

        `compute_sudo` vaut True par défaut pour un champ calculé stocké
        (`odoo/orm/fields.py`). C'est ce qui permet à un commercial de modifier
        une affaire sans que le recalcul de marge bute sur les coûts — et c'est
        assez fragile pour mériter une assertion.
        """
        deal = self.env["dally.trade.opportunity"].with_user(
            self.commercial).browse(self.deal.id)
        deal.write({"name": "Renommée par le commercial"})
        self.env.flush_all()
        self.assertEqual(self.deal.cost_total_analysis, 1234.56)
