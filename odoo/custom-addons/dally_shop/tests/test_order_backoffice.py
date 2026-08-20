"""Backoffice E-commerce Pro : voir les commandes boutique, et seulement elles.

Le premier lot est volontairement en lecture seule. Ces tests vérifient les deux
frontières qui comptent : la record rule empêche l'opérateur de voir une vente
ordinaire, et l'ACL empêche toute mutation même sur une commande qu'il peut lire.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install", "dally_shop")
class TestOrderBackoffice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.partner = cls.env["res.partner"].create({
            "name": "Client Backoffice Boutique",
            "email": "backoffice.shop@essai.invalid",
        })
        cls.product = cls.env["product.template"].create({
            "name": "Produit Backoffice Boutique",
            "type": "consu",
            "sale_ok": True,
            "list_price": 25000.0,
        })

        cls.shop_order = cls.env["sale.order"].create({
            "partner_id": cls.partner.id,
            "dally_shop_order": True,
            "dally_shop_cart_uuid": "00000000-0000-4000-8000-000000000101",
            "dally_shop_delivery_mode": "pickup",
            "state": "draft",
            "order_line": [(0, 0, {
                "product_id": cls.product.product_variant_id.id,
                "product_uom_qty": 2,
            })],
        })
        cls.regular_order = cls.env["sale.order"].create({
            "partner_id": cls.partner.id,
            "state": "draft",
            "order_line": [(0, 0, {
                "product_id": cls.product.product_variant_id.id,
                "product_uom_qty": 1,
            })],
        })

        cls.group_operations = cls.env.ref("dally_shop.group_dally_shop_operations")
        cls.operator = cls.env["res.users"].create({
            "name": "Opérateur Boutique",
            "login": "shop.operations@essai.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.group_operations.id,
            ])],
        })

    def test_operateur_ne_voit_que_les_commandes_boutique(self):
        commandes = self.env["sale.order"].with_user(self.operator).search([
            ("id", "in", [self.shop_order.id, self.regular_order.id]),
        ])

        self.assertEqual(commandes.ids, self.shop_order.ids)

    def test_operateur_ne_voit_que_les_lignes_boutique(self):
        lignes = self.env["sale.order.line"].with_user(self.operator).search([
            ("id", "in", (
                self.shop_order.order_line | self.regular_order.order_line
            ).ids),
        ])

        self.assertEqual(lignes.ids, self.shop_order.order_line.ids)

    def test_operateur_peut_lire_mais_pas_modifier(self):
        commande = self.env["sale.order"].with_user(self.operator).browse(
            self.shop_order.id
        )
        self.assertEqual(commande.name, self.shop_order.name)
        self.assertEqual(commande.amount_total, self.shop_order.amount_total)

        with self.assertRaises(AccessError):
            commande.write({"client_order_ref": "interdit"})

        with self.assertRaises(AccessError):
            self.env["sale.order"].with_user(self.operator).create({
                "partner_id": self.partner.id,
            })

        with self.assertRaises(AccessError):
            commande.unlink()

    def test_action_reste_bornee_aux_commandes_boutique(self):
        action = self.env.ref("dally_shop.dally_shop_order_action")
        domaine = safe_eval(action.domain)

        self.assertIn(("dally_shop_order", "=", True), domaine)
        self.assertEqual(action.res_model, "sale.order")

    def test_vues_backoffice_sont_en_lecture_seule(self):
        liste = self.env.ref("dally_shop.view_dally_shop_order_list").arch_db
        formulaire = self.env.ref("dally_shop.view_dally_shop_order_form").arch_db

        for architecture in (liste, formulaire):
            self.assertIn('create="0"', architecture)
            self.assertIn('edit="0"', architecture)
            self.assertIn('delete="0"', architecture)
