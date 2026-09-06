# -*- coding: utf-8 -*-
"""Administration explicite des comptes Dally Ops."""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install", "dally")
class TestOpsUserAccessAdmin(TransactionCase):

    def setUp(self):
        super().setUp()
        self.logisticien = self.env.ref(
            "dally_ops_mobile.group_dally_ops_logistician")
        self.responsable = self.env.ref(
            "dally_ops_mobile.group_dally_ops_supervisor")
        self.admin = self.env["res.users"].create({
            "name": "Admin Accès Ops",
            "login": "ops.access.admin",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("base.group_erp_manager").id,
            ])],
        })
        self.cible = self.env["res.users"].create({
            "name": "Opérateur à configurer",
            "login": "ops.access.target",
            "group_ids": [(6, 0, [])],
        })

    def _recharger(self):
        self.cible.invalidate_recordset()
        return self.cible

    def test_admin_attribue_logisticien_et_acteur(self):
        self.cible.with_user(self.admin).write({
            "dally_ops_access_role": "logistician",
            "dally_ops_cash_actor": "  Gilles  ",
        })
        cible = self._recharger()
        self.assertTrue(cible.has_group(
            "dally_ops_mobile.group_dally_ops_logistician"))
        self.assertFalse(cible.has_group(
            "dally_ops_mobile.group_dally_ops_supervisor"))
        self.assertEqual(cible.dally_ops_access_role, "logistician")
        self.assertEqual(cible.dally_ops_cash_actor, "Gilles")
        self.assertTrue(cible.share)
        self.assertFalse(cible.has_group("base.group_user"))

    def test_admin_promeut_responsable_sans_ouvrir_admin_odoo(self):
        self.cible.with_user(self.admin).write({
            "dally_ops_access_role": "supervisor",
            "dally_ops_cash_actor": "Dalanda",
        })
        cible = self._recharger()
        self.assertTrue(cible.has_group(
            "dally_ops_mobile.group_dally_ops_supervisor"))
        self.assertTrue(cible.has_group(
            "dally_ops_mobile.group_dally_ops_logistician"))
        self.assertEqual(cible.dally_ops_access_role, "supervisor")
        self.assertFalse(cible.has_group("base.group_user"))
        self.assertFalse(cible.has_group("base.group_erp_manager"))
        self.assertTrue(
            self.env["res.users"].with_user(cible)
            ._dally_ops_capabilities()["supervise"])

    def test_un_compte_interne_conserve_ses_droits_existants(self):
        interne = self.env["res.users"].create({
            "name": "Opérateur interne existant",
            "login": "ops.access.internal",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
            ])],
        })
        self.assertFalse(interne.share)

        interne.with_user(self.admin).write({
            "dally_ops_access_role": "logistician",
            "dally_ops_cash_actor": "Gilles",
        })
        interne.invalidate_recordset()
        self.assertTrue(interne.has_group("base.group_user"))
        self.assertTrue(interne.has_group(
            "dally_ops_mobile.group_dally_ops_logistician"))
        self.assertFalse(interne.share)

        interne.with_user(self.admin).dally_ops_access_role = "supervisor"
        interne.invalidate_recordset()
        self.assertTrue(interne.has_group("base.group_user"))
        self.assertTrue(interne.has_group(
            "dally_ops_mobile.group_dally_ops_supervisor"))
        self.assertFalse(interne.share)

    def test_admin_peut_retrograder_puis_retirer_acces(self):
        cible = self.cible.with_user(self.admin)
        cible.dally_ops_access_role = "supervisor"
        cible.dally_ops_access_role = "logistician"
        self._recharger()
        self.assertEqual(self.cible.dally_ops_access_role, "logistician")
        self.assertFalse(self.cible.has_group(
            "dally_ops_mobile.group_dally_ops_supervisor"))

        self.cible.with_user(self.admin).dally_ops_access_role = "none"
        self._recharger()
        self.assertEqual(self.cible.dally_ops_access_role, "none")
        self.assertFalse(self.cible.has_group(
            "dally_ops_mobile.group_dally_ops_logistician"))
        self.assertFalse(self.cible.has_group(
            "dally_ops_mobile.group_dally_ops_supervisor"))

    def test_un_responsable_ops_ne_peut_pas_promouvoir_un_collegue(self):
        responsable = self.env["res.users"].create({
            "name": "Responsable terrain",
            "login": "ops.access.supervisor",
            "group_ids": [(6, 0, [self.responsable.id])],
        })
        with self.assertRaises(AccessError):
            self.cible.with_user(responsable).write({
                "dally_ops_access_role": "supervisor",
            })

    def test_action_admin_liste_les_comptes_ops_externes(self):
        self.cible.with_user(self.admin).write({
            "dally_ops_access_role": "logistician",
            "dally_ops_cash_actor": "Gilles",
        })
        action = self.env.ref("dally_ops_mobile.action_dally_ops_users")
        self.assertNotIn("search_default_filter_no_share", action.context or "")
        ids = self.env["res.users"].search(safe_eval(action.domain)).ids
        self.assertIn(self.cible.id, ids)
        self.assertTrue(self.cible.share)

    def test_nouveau_compte_depuis_action_est_logisticien_par_defaut(self):
        action = self.env.ref("dally_ops_mobile.action_dally_ops_users")
        contexte = safe_eval(action.context)
        self.assertEqual(
            contexte["default_group_ids"], [(4, self.logisticien.id)])
        self.assertNotIn("search_default_filter_no_share", contexte)

        nouveau = self.env["res.users"].with_context(**contexte).create({
            "name": "Nouveau Logisticien",
            "login": "ops.access.new",
        })
        self.assertTrue(nouveau.has_group(
            "dally_ops_mobile.group_dally_ops_logistician"))
        self.assertFalse(nouveau.has_group("base.group_user"))
        self.assertTrue(nouveau.share)
        self.assertEqual(nouveau.dally_ops_access_role, "logistician")

    def test_vue_admin_expose_role_et_acteur(self):
        vue = self.env.ref("dally_ops_mobile.view_users_form_dally_ops_access")
        self.assertIn("dally_ops_access_role", vue.arch_db)
        self.assertIn("dally_ops_cash_actor", vue.arch_db)
        self.assertIn("base.group_erp_manager", vue.arch_db)

    def test_menu_est_reserve_aux_administrateurs_des_droits(self):
        menu = self.env.ref("dally_ops_mobile.menu_dally_ops_users")
        self.assertIn(self.env.ref("base.group_erp_manager"), menu.group_ids)
        self.assertNotIn(self.responsable, menu.group_ids)
