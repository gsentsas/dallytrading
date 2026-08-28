# -*- coding: utf-8 -*-
"""Les deux rôles terrain, et l'identité de caisse.

Un module de rôles se teste par ce qu'il **refuse**. Les assertions vont donc
par paires : ce que le rôle permet, et ce qu'il ne permet pas — sans la
seconde, un groupe qui impliquerait tout passerait le premier test sans
broncher.

Deux propriétés comptent plus que les autres.

**Aucun rôle humain n'hérite d'une identité technique.** Les groupes
`Freight Sync API` et `Freight Billing API` servent une clé d'API : ils ouvrent
l'écriture en masse sur les clients, les dossiers et la facturation. Les faire
impliquer par un rôle de terrain donnerait à un téléphone les pouvoirs d'un
automate, et retirerait tout sens à la règle « aucun secret dans le
navigateur ».

**L'acteur de caisse ne se devine pas.** Il est déclaré, ou l'opération est
refusée. Un repli sur `display_name` imputerait une dépense au mauvais
collègue, silencieusement.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestOpsRoles(TransactionCase):

    #: Identités techniques qu'aucun rôle humain ne doit emporter.
    GROUPES_TECHNIQUES = (
        "dally_freight_billing.group_dally_freight_sync_api",
        "dally_freight_billing.group_dally_freight_billing_api",
    )

    def setUp(self):
        super().setUp()
        self.logisticien = self._utilisateur(
            "logisticien", "dally_ops_mobile.group_dally_ops_logistician")
        self.responsable = self._utilisateur(
            "responsable", "dally_ops_mobile.group_dally_ops_supervisor")

    def _utilisateur(self, nom, groupe):
        return self.env["res.users"].create({
            "name": "Ops %s" % nom,
            "login": "ops.%s@dallytrading.invalid" % nom,
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref(groupe).id,
            ])],
        })

    # ─── Les rôles existent, et s'emboîtent ──────────────────────────

    def test_les_deux_roles_existent(self):
        for xmlid in ("group_dally_ops_logistician", "group_dally_ops_supervisor"):
            groupe = self.env.ref("dally_ops_mobile.%s" % xmlid)
            self.assertTrue(groupe.name)

    def test_le_logisticien_peut_lire_le_perimetre_dally(self):
        """Sans lecture, il saisirait à l'aveugle."""
        self.assertTrue(
            self.logisticien.has_group("dally_core.group_dally_readonly"))

    def test_le_responsable_est_aussi_logisticien(self):
        """Ce qu'il corrige, il doit d'abord pouvoir le saisir."""
        self.assertTrue(
            self.responsable.has_group("dally_ops_mobile.group_dally_ops_logistician"))

    # ─── Ce que les rôles ne donnent pas ─────────────────────────────

    def test_aucun_role_n_herite_d_une_identite_technique(self):
        for utilisateur in (self.logisticien, self.responsable):
            for groupe in self.GROUPES_TECHNIQUES:
                self.assertFalse(
                    utilisateur.has_group(groupe),
                    "%s hérite de %s" % (utilisateur.name, groupe))

    def test_aucun_role_n_ouvre_l_administration(self):
        for utilisateur in (self.logisticien, self.responsable):
            for groupe in ("base.group_system", "base.group_erp_manager"):
                self.assertFalse(utilisateur.has_group(groupe), groupe)

    def test_aucun_role_n_ouvre_la_finance_ni_le_management(self):
        """Corriger un poids n'exige pas d'accéder aux marges."""
        for utilisateur in (self.logisticien, self.responsable):
            for groupe in ("dally_core.group_dally_finance",
                           "dally_core.group_dally_manager",
                           "dally_core.group_dally_admin"):
                self.assertFalse(utilisateur.has_group(groupe), groupe)

    def test_le_logisticien_ne_lit_pas_les_couts_du_negoce(self):
        """Contrôle concret plutôt que déclaratif : on tente la lecture."""
        self.assertFalse(
            self.env["dally.trade.cost"].with_user(self.logisticien).has_access("read"))

    # ─── L'acteur de caisse ──────────────────────────────────────────

    def test_sans_acteur_configure_l_operation_est_refusee(self):
        """Fail closed : mieux vaut un refus bruyant qu'une imputation fausse."""
        self.assertFalse(self.logisticien.dally_ops_cash_actor)
        with self.assertRaises(UserError):
            self.logisticien._dally_ops_actor()

    def test_l_acteur_configure_est_rendu_tel_quel(self):
        self.logisticien.dally_ops_cash_actor = "Gilles"
        self.assertEqual(self.logisticien._dally_ops_actor(), "Gilles")

    def test_l_acteur_n_est_jamais_deduit_du_nom_affiche(self):
        """Le nom affiché change ; l'imputation ne doit pas changer avec lui."""
        self.logisticien.dally_ops_cash_actor = "Gilles"
        self.logisticien.name = "Gilles DUPONT-Martin"
        self.assertEqual(self.logisticien._dally_ops_actor(), "Gilles")

        # Et l'inverse : un nom affiché parlant ne suffit pas.
        autre = self._utilisateur("sansacteur", "dally_ops_mobile.group_dally_ops_logistician")
        autre.name = "Alain"
        with self.assertRaises(UserError):
            autre._dally_ops_actor()

    def test_les_espaces_sont_ignores(self):
        self.logisticien.dally_ops_cash_actor = "  Gilles  "
        self.assertEqual(self.logisticien._dally_ops_actor(), "Gilles")
        self.logisticien.dally_ops_cash_actor = "   "
        with self.assertRaises(UserError):
            self.logisticien._dally_ops_actor()

    # ─── Le rôle courant ─────────────────────────────────────────────

    def test_le_role_est_resolu_du_plus_fort_au_plus_faible(self):
        Users = self.env["res.users"]
        self.assertEqual(
            Users.with_user(self.logisticien)._dally_ops_role(), "logistician")
        self.assertEqual(
            Users.with_user(self.responsable)._dally_ops_role(), "supervisor")

    def test_un_utilisateur_ordinaire_n_a_aucun_role_ops(self):
        ordinaire = self.env["res.users"].create({
            "name": "Ops aucun", "login": "ops.aucun@dallytrading.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.assertFalse(self.env["res.users"].with_user(ordinaire)._dally_ops_role())
