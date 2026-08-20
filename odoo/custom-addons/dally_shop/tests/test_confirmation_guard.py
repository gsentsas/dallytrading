# -*- coding: utf-8 -*-
"""Le verrou natif de confirmation des commandes boutique Lot C."""

import uuid

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally_shop")
class TestShopConfirmationGuard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "Client garde confirmation boutique",
        })
        cls.product = cls.env["product.template"].create({
            "name": "Produit garde confirmation boutique",
            "type": "consu",
            "sale_ok": True,
            "list_price": 1000.0,
        })

    def _line(self):
        return [(0, 0, {
            "product_id": self.product.product_variant_id.id,
            "product_uom_qty": 1,
        })]

    def test_action_confirm_directe_est_bloquee_sur_commande_boutique(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "dally_shop_order": True,
            "dally_shop_cart_uuid": str(uuid.uuid4()),
            "dally_shop_delivery_mode": "pickup",
            "order_line": self._line(),
        })

        with self.assertRaises(ValidationError):
            order.action_confirm()

        self.assertEqual(order.state, "draft")
        self.assertFalse(order.dally_shop_fulfillment_authorized)

    def test_vente_ordinaire_reste_confirmable(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": self._line(),
        })

        order.action_confirm()

        self.assertEqual(order.state, "sale")
        self.assertFalse(order.dally_shop_order)
