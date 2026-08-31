# -*- coding: utf-8 -*-
"""L'entrée d'état réservée au terrain : ce qu'elle ouvre, et ce qu'elle ne
touche pas.

## Pourquoi elle existe

Un opérateur de Dally Ops n'a pas `dally_core.group_dally_logistics`, et ne
doit pas l'obtenir : ce groupe implique `group_dally_readonly`, qui ouvre
vingt-et-un modèles en lecture à un compte vivant sur un téléphone d'entrepôt.
Le contrôle d'appartenance de `write()` lui barre donc la route, alors même que
son geste — « mettre en préparation » — est parfaitement légitime.

`_action_set_state_from_ops` ouvre cette barrière-là, et **elle seule**.

## Ce que ces tests interdisent

Qu'elle devienne un troisième contournement. La matrice, l'adjacence, la porte
« prêt » et la porte de départ doivent rester exactement ce qu'elles sont pour
un utilisateur Logistics. Un test lit la source de `_check_state_transition`
pour vérifier que le jeton n'y apparaît sous aucune forme : c'est la seule
manière de garantir qu'un ajout futur soit une décision et non un glissement.
"""

import ast
import inspect
import uuid

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestShipmentOpsStateEntry(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # `_write_historical_state` sert de mise en place et exige Manager.
        # C'est l'utilisateur de la classe qui l'emploie, jamais le compte de
        # terrain dont ces tests mesurent les droits.
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.societe = cls.env.company
        cls.partenaire = cls.env["res.partner"].create({
            "name": "Client Entrée Ops", "company_id": cls.societe.id})
        #: Un compte interne ordinaire : ni Logistics, ni Manager. C'est
        #: exactement la situation d'un logisticien Dally Ops.
        cls.terrain = cls.env["res.users"].create({
            "name": "Terrain sans Logistics",
            "login": "freight.terrain.%s" % uuid.uuid4().hex[:6],
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            "company_id": cls.societe.id,
            "company_ids": [(6, 0, [cls.societe.id])],
        })

    def _dossier(self, etat=None):
        dossier = self.env["dally.shipment"].sudo().create({
            "partner_id": self.partenaire.id,
            "company_id": self.societe.id,
            "external_reference": "AIR-ENTREE-OPS-%s" % uuid.uuid4().hex[:8].upper(),
            "transport_mode": "air", "direction": "export",
        })
        if etat:
            # Mise en place seulement : le chemin historique exige Manager et
            # court-circuite tout. Il place le dossier là où le test commence,
            # il ne fait pas partie de ce qui est mesuré.
            dossier._write_historical_state(etat)
        return dossier

    def _terrain(self, dossier):
        return dossier.with_user(self.terrain)

    # ─── C1 · la barrière existe bel et bien ─────────────────────────

    def test_C1_sans_group_logistics_action_set_state_est_refuse(self):
        dossier = self._dossier()
        self.assertFalse(
            self.terrain.has_group("dally_core.group_dally_logistics"))
        with self.assertRaises(AccessError):
            self._terrain(dossier).action_set_state("request_received")
        self.assertEqual(dossier.state, "draft")

    # ─── C2 · l'entrée Ops la franchit, pour une transition légitime ─

    def test_C2_lentree_ops_franchit_la_barriere_de_permission(self):
        dossier = self._dossier()
        self._terrain(dossier)._action_set_state_from_ops("request_received")
        dossier.invalidate_recordset(["state"])
        self.assertEqual(dossier.state, "request_received")
        # Et le compte n'a rien gagné au passage.
        self.assertFalse(
            self.terrain.has_group("dally_core.group_dally_logistics"))

    # ─── C3 à C5 · elle ne franchit rien d'autre ─────────────────────

    def test_C3_une_transition_non_adjacente_reste_refusee(self):
        dossier = self._dossier("goods_received")
        with self.assertRaises(UserError):
            self._terrain(dossier)._action_set_state_from_ops("ready")
        dossier.invalidate_recordset(["state"])
        self.assertEqual(dossier.state, "goods_received")

    def test_C4_un_etat_inconnu_reste_refuse(self):
        dossier = self._dossier("goods_received")
        for inconnu in ("brouillon", "preparing_", "", "READY"):
            with self.assertRaises(UserError):
                self._terrain(dossier)._action_set_state_from_ops(inconnu)
        dossier.invalidate_recordset(["state"])
        self.assertEqual(dossier.state, "goods_received")

    def test_C5_un_dossier_cloture_ne_se_rouvre_pas(self):
        for terminal in ("delivered", "cancelled"):
            dossier = self._dossier(terminal)
            with self.assertRaises(UserError):
                self._terrain(dossier)._action_set_state_from_ops("preparing")
            dossier.invalidate_recordset(["state"])
            self.assertEqual(dossier.state, terminal)

    # ─── C6 · le jeton n'entre pas dans la matrice ───────────────────

    def test_C6_le_jeton_ops_nest_teste_dans_aucun_chemin_de_bypass(self):
        """La garantie centrale de cette option, lue dans le code.

        `_check_state_transition` décide de l'adjacence et déclenche les deux
        portes. Le jour où quelqu'un y ajoute le jeton Ops, ce test tombe — et
        l'ajout devient une décision au lieu d'un glissement.
        """
        from odoo.addons.dally_freight.models import dally_shipment
        source = inspect.getsource(dally_shipment)
        arbre = ast.parse(source)
        controle = next(
            noeud for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_check_state_transition"
        )
        corps = ast.unparse(controle)
        self.assertNotIn("_OPS_STATE_WRITE_TOKEN", corps)
        self.assertNotIn("_dally_ops_state_write", corps)
        # Les deux jetons historiques, eux, y sont toujours : le test échouerait
        # aussi si quelqu'un les retirait par symétrie.
        self.assertIn("_STATE_BYPASS_TOKEN", corps)
        self.assertIn("_OPERATIONAL_SYNC_TOKEN", corps)

    # ─── C7/C8 · les deux portes métier restent fermées ──────────────

    def test_C7_la_porte_pret_reste_active_par_lentree_ops(self):
        """Un dossier sans colis ni poids ne devient pas « prêt »."""
        dossier = self._dossier("preparing")
        self.assertFalse(dossier.package_ids)
        with self.assertRaises(UserError) as refus:
            self._terrain(dossier)._action_set_state_from_ops("ready")
        self.assertIn("prêt", str(refus.exception).lower())
        dossier.invalidate_recordset(["state"])
        self.assertEqual(dossier.state, "preparing")

    def test_C8_la_porte_de_depart_reste_active_par_lentree_ops(self):
        """Dally Ops n'expose jamais `departed` — le privilège ne l'ouvre pas
        davantage pour un appelant futur."""
        dossier = self._dossier("ready")
        self.assertFalse(dossier.invoice_id)
        with self.assertRaises(UserError) as refus:
            self._terrain(dossier)._action_set_state_from_ops("departed")
        self.assertIn("départ", str(refus.exception).lower())
        dossier.invalidate_recordset(["state"])
        self.assertEqual(dossier.state, "ready")

    # ─── L'entrée reste privée ───────────────────────────────────────

    def test_lentree_ops_nest_pas_appelable_en_rpc(self):
        """Une méthode privée ne s'expose pas : le préfixe est la protection."""
        self.assertTrue(
            hasattr(self.env["dally.shipment"], "_action_set_state_from_ops"))
        self.assertTrue("_action_set_state_from_ops".startswith("_"))
