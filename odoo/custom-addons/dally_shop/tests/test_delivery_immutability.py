# -*- coding: utf-8 -*-
"""Une méthode de remise utilisée devient une définition historique immuable."""

import uuid

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally_shop")
class TestDeliveryMethodImmutability(TransactionCase):

    def test_definition_utilisee_est_gelee_mais_peut_etre_desactivee(self):
        method = self.env["dally.shop.delivery.method"].create({
            "name": "Méthode historique",
            "code": "historique-test",
            "kind": "delivery",
            "fee_policy": "fixed",
            "fixed_fee": 2500.0,
            "currency_id": self.env.company.currency_id.id,
            "client_help": "Aide initiale",
        })
        partner = self.env["res.partner"].create({"name": "Client historique"})
        order = self.env["sale.order"].create({
            "partner_id": partner.id,
            "dally_shop_order": True,
            "dally_shop_cart_uuid": str(uuid.uuid4()),
            "dally_shop_delivery_mode": "delivery_to_confirm",
        })
        order.sudo().write({"dally_shop_delivery_method_id": method.id})

        for values in (
            {"name": "Nouveau nom"},
            {"code": "nouveau-code"},
            {"kind": "pickup"},
            {"fee_policy": "free"},
            {"fixed_fee": 9999.0},
        ):
            with self.assertRaises(ValidationError):
                method.write(values)

        method.write({
            "active": False,
            "sequence": 99,
            "client_help": "Utilisez désormais la nouvelle méthode.",
        })
        self.assertFalse(method.active)
        self.assertEqual(method.sequence, 99)
        self.assertEqual(method.fixed_fee, 2500.0)
