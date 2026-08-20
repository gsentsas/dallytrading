# -*- coding: utf-8 -*-
"""Record rule du journal de remise Lot C."""

import uuid

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally_shop")
class TestFulfillmentSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Client sécurité remise"})
        cls.operator = cls.env["res.users"].create({
            "name": "Opérateur sécurité remise",
            "login": "shop.fulfillment.security@essai.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("dally_shop.group_dally_shop_operations").id,
            ])],
        })

    def test_operateur_ne_lit_que_les_evenements_de_commandes_boutique(self):
        shop = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "dally_shop_order": True,
            "dally_shop_cart_uuid": str(uuid.uuid4()),
            "dally_shop_delivery_mode": "pickup",
        })
        regular = self.env["sale.order"].create({"partner_id": self.partner.id})

        events = self.env["dally.shop.fulfillment.event"].sudo()
        shop_event = events.create({
            "order_id": shop.id,
            "to_state": "preparing",
            "changed_by_id": self.env.user.id,
        })
        regular_event = events.create({
            "order_id": regular.id,
            "to_state": "preparing",
            "changed_by_id": self.env.user.id,
        })

        visible = self.env["dally.shop.fulfillment.event"].with_user(self.operator).search([
            ("id", "in", [shop_event.id, regular_event.id]),
        ])
        self.assertEqual(visible, shop_event)
