# -*- coding: utf-8 -*-
"""Rattache les commandes boutique historiques aux méthodes de remise Lot C.

Migration strictement descriptive : elle ne confirme aucune vente, ne crée aucun
picking, ne modifie pas le workflow commercial et n'envoie aucun message. Les
adresses historiques sont copiées depuis le partenaire uniquement pour figer ce
qui existait déjà au moment de l'upgrade.
"""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Order = env["sale.order"].sudo()

    pickup = env.ref("dally_shop.delivery_method_pickup")
    delivery = env.ref("dally_shop.delivery_method_delivery_to_confirm")

    orders = Order.search([
        ("dally_shop_order", "=", True),
        ("dally_shop_delivery_method_id", "=", False),
    ])

    for order in orders:
        method = pickup if order.dally_shop_delivery_mode == "pickup" else delivery
        fee_state, fee_amount = method._dally_shop_fee_snapshot()
        values = {
            "dally_shop_delivery_method_id": method.id,
            "dally_shop_delivery_fee_state": fee_state,
            "dally_shop_delivery_fee": fee_amount,
            "dally_shop_fulfillment_state": "pending",
            "dally_shop_fulfillment_authorized": False,
        }

        if method.requires_address:
            partner = order.partner_id
            values.update({
                "dally_shop_shipping_name": partner.name or False,
                "dally_shop_shipping_phone": partner.phone or False,
                "dally_shop_shipping_street": partner.street or False,
                "dally_shop_shipping_street2": partner.street2 or False,
                "dally_shop_shipping_city": partner.city or False,
                "dally_shop_shipping_zip": partner.zip or False,
                "dally_shop_shipping_country_code": partner.country_id.code or False,
            })

        order.write(values)
