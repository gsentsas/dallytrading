# -*- coding: utf-8 -*-
"""E-commerce Pro Lot B : workflow commercial des commandes boutique."""

import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally_shop")
class TestOrderWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "Client Workflow Boutique",
            "email": "workflow.shop@essai.invalid",
        })
        cls.product = cls.env["product.template"].create({
            "name": "Produit Workflow Boutique",
            "type": "consu",
            "sale_ok": True,
            "list_price": 25000.0,
        })
        cls.group_operations = cls.env.ref("dally_shop.group_dally_shop_operations")
        cls.operator = cls.env["res.users"].create({
            "name": "Opérateur Workflow Boutique",
            "login": "shop.workflow@essai.invalid",
            "email": "shop.workflow@essai.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.group_operations.id,
            ])],
        })
        cls.readonly = cls.env["res.users"].create({
            "name": "Lecteur Workflow Boutique",
            "login": "shop.workflow.readonly@essai.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("dally_core.group_dally_readonly").id,
            ])],
        })

    def _order(self):
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "dally_shop_order": True,
            "dally_shop_cart_uuid": str(uuid.uuid4()),
            "dally_shop_delivery_mode": "pickup",
            "state": "draft",
            "order_line": [(0, 0, {
                "product_id": self.product.product_variant_id.id,
                "product_uom_qty": 1,
            })],
        })

    def _as_operator(self, order):
        return self.env["sale.order"].with_user(self.operator).browse(order.id)

    def test_creation_initialise_recue_sans_confirmer_vente(self):
        order = self._order()

        self.assertEqual(order.dally_shop_workflow_state, "received")
        self.assertEqual(order.state, "draft")
        self.assertEqual(len(order.dally_shop_transition_ids), 1)
        transition = order.dally_shop_transition_ids
        self.assertFalse(transition.from_state)
        self.assertEqual(transition.to_state, "received")
        self.assertTrue(transition.notification_queued)

    def test_validation_explicite_ne_cree_aucun_effet_sale(self):
        order = self._order()
        before_pickings = self.env["stock.picking"].search_count([
            ("origin", "=", order.name),
        ])

        self._as_operator(order).action_dally_shop_validate()
        order.invalidate_recordset()

        self.assertEqual(order.dally_shop_workflow_state, "validated")
        self.assertEqual(order.state, "draft")
        self.assertEqual(
            self.env["stock.picking"].search_count([("origin", "=", order.name)]),
            before_pickings,
        )
        self.assertFalse(order.invoice_ids)
        self.assertEqual(order.dally_shop_transition_ids[0].to_state, "validated")

    def test_validation_est_idempotente(self):
        order = self._order()
        operated = self._as_operator(order)
        operated.action_dally_shop_validate()
        count_after_first = self.env["dally.shop.order.transition"].search_count([
            ("order_id", "=", order.id),
            ("to_state", "=", "validated"),
        ])

        operated.action_dally_shop_validate()
        count_after_second = self.env["dally.shop.order.transition"].search_count([
            ("order_id", "=", order.id),
            ("to_state", "=", "validated"),
        ])

        self.assertEqual(count_after_first, 1)
        self.assertEqual(count_after_second, 1)

    def test_refus_exige_un_motif_client(self):
        order = self._order()
        operated = self._as_operator(order)

        with self.assertRaises(ValidationError):
            operated._dally_shop_transition("rejected", "   ")

        operated._dally_shop_transition("rejected", "Article indisponible")
        order.invalidate_recordset()
        self.assertEqual(order.dally_shop_workflow_state, "rejected")
        self.assertEqual(order.dally_shop_customer_reason, "Article indisponible")
        self.assertEqual(order.state, "draft")

    def test_annulation_seulement_apres_validation(self):
        order = self._order()
        operated = self._as_operator(order)

        with self.assertRaises(ValidationError):
            operated._dally_shop_transition("cancelled", "Demande du client")

        operated.action_dally_shop_validate()
        operated._dally_shop_transition("cancelled", "Demande du client")
        order.invalidate_recordset()
        self.assertEqual(order.dally_shop_workflow_state, "cancelled")
        self.assertEqual(order.dally_shop_customer_reason, "Demande du client")
        self.assertEqual(order.state, "draft")

    def test_lecteur_sans_role_operations_ne_peut_pas_transitionner(self):
        order = self._order()
        readonly_order = self.env["sale.order"].with_user(self.readonly).browse(order.id)

        with self.assertRaises(AccessError):
            readonly_order.action_dally_shop_validate()

    def test_une_vente_ordinaire_ne_peut_pas_entrer_dans_le_workflow(self):
        regular = self.env["sale.order"].create({"partner_id": self.partner.id})

        with self.assertRaises(ValidationError):
            regular.action_dally_shop_validate()
        self.assertFalse(regular.dally_shop_workflow_state)

    def test_notifications_sont_mises_en_file_sans_envoi_synchrone(self):
        order = self._order()
        self._as_operator(order).action_dally_shop_validate()

        mails = self.env["mail.mail"].sudo().search([
            ("email_to", "=", self.partner.email),
            ("subject", "ilike", order.name),
        ])
        self.assertGreaterEqual(len(mails), 2)  # réception + validation
        self.assertTrue(all(mail.state == "outgoing" for mail in mails))

    def test_projection_portail_utilise_le_workflow_et_seulement_le_motif_client(self):
        order = self._order()
        self._as_operator(order)._dally_shop_transition(
            "rejected", "Référence momentanément indisponible"
        )
        order.sudo().write({"note": "NOTE_INTERNE_NE_DOIT_PAS_SORTIR"})

        projection = order._dally_shop_portal_detail()
        self.assertEqual(projection["state"], "rejected")
        self.assertEqual(
            projection["stateLabel"],
            "Commande refusée — Référence momentanément indisponible",
        )
        self.assertNotIn("stateReason", projection)
        self.assertNotIn("NOTE_INTERNE_NE_DOIT_PAS_SORTIR", str(projection))

    def test_journal_est_lecture_seule_pour_operateur(self):
        order = self._order()
        transition = order.dally_shop_transition_ids.with_user(self.operator)
        self.assertEqual(transition.to_state, "received")

        with self.assertRaises(AccessError):
            transition.write({"reason": "interdit"})
        with self.assertRaises(AccessError):
            transition.unlink()
