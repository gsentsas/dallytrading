# -*- coding: utf-8 -*-
"""Correction gardée de l'adresse de livraison avant préparation."""

import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally_shop")
class TestShippingManagement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "Client adresse historique",
            "email": "adresse.historique@essai.invalid",
        })
        cls.product = cls.env["product.template"].create({
            "name": "Produit adresse historique",
            "type": "consu",
            "sale_ok": True,
            "list_price": 1000.0,
        })
        cls.operator = cls.env["res.users"].create({
            "name": "Opérateur adresse boutique",
            "login": "shop.shipping.operator@essai.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("dally_shop.group_dally_shop_operations").id,
            ])],
        })
        cls.readonly = cls.env["res.users"].create({
            "name": "Lecteur adresse boutique",
            "login": "shop.shipping.readonly@essai.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("dally_core.group_dally_readonly").id,
            ])],
        })
        cls.delivery = cls.env.ref(
            "dally_shop.delivery_method_delivery_to_confirm"
        )

    def _order(self):
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "dally_shop_order": True,
            "dally_shop_cart_uuid": str(uuid.uuid4()),
            "dally_shop_delivery_mode": "delivery_to_confirm",
            "dally_shop_delivery_method_id": self.delivery.id,
            "dally_shop_delivery_fee_state": "pending_quote",
            "dally_shop_fulfillment_state": "pending",
            "state": "draft",
            "order_line": [(0, 0, {
                "product_id": self.product.product_variant_id.id,
                "product_uom_qty": 1,
            })],
        })

    @staticmethod
    def _address():
        return {
            "name": "Dépôt destinataire",
            "phone": "+221770000099",
            "street": "10 avenue du Port",
            "street2": "Hangar C",
            "city": "Dakar",
            "zip": "11000",
            "country_code": "SN",
        }

    def test_operateur_peut_completer_une_adresse_historique(self):
        order = self._order()
        operated = self.env["sale.order"].with_user(self.operator).browse(order.id)

        operated._dally_shop_set_shipping_address(self._address())
        order.invalidate_recordset()

        self.assertEqual(order.dally_shop_shipping_name, "Dépôt destinataire")
        self.assertEqual(order.dally_shop_shipping_street, "10 avenue du Port")
        self.assertEqual(order.dally_shop_shipping_city, "Dakar")
        self.assertEqual(order.dally_shop_shipping_country_code, "SN")
        self.assertTrue(order.dally_shop_shipping_updated_at)
        self.assertEqual(order.dally_shop_shipping_updated_by_id, self.operator)
        self.assertEqual(order.state, "draft")
        self.assertFalse(order.dally_shop_fulfillment_authorized)

    def test_lecteur_ne_peut_pas_modifier_adresse(self):
        order = self._order()
        readonly = self.env["sale.order"].with_user(self.readonly).browse(order.id)

        with self.assertRaises(AccessError):
            readonly._dally_shop_set_shipping_address(self._address())

    def test_adresse_est_gelee_apres_autorisation_preparation(self):
        order = self._order()
        operated = self.env["sale.order"].with_user(self.operator).browse(order.id)
        operated._dally_shop_set_shipping_address(self._address())
        operated.action_dally_shop_validate()
        operated._dally_shop_set_delivery_fee(1500.0)
        operated.action_dally_shop_authorize_fulfillment()

        with self.assertRaises(ValidationError):
            operated._dally_shop_set_shipping_address({
                **self._address(),
                "street": "99 rue interdite après préparation",
            })

        order.invalidate_recordset()
        self.assertEqual(order.dally_shop_shipping_street, "10 avenue du Port")
        self.assertTrue(order.dally_shop_fulfillment_authorized)
