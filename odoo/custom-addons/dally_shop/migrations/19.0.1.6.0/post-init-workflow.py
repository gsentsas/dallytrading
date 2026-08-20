# -*- coding: utf-8 -*-
"""Initialise le workflow Lot B sur les commandes boutique déjà présentes.

Aucune notification n'est créée ici : un déploiement ne doit pas renvoyer en
masse un e-mail « commande reçue » pour des commandes historiques. La migration
ne change pas ``sale.order.state`` et ne confirme, n'annule, ne facture ni ne
prépare rien.
"""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Order = env["sale.order"].sudo()
    Transition = env["dally.shop.order.transition"].sudo()

    orders = Order.search([
        ("dally_shop_order", "=", True),
        ("dally_shop_workflow_state", "=", False),
    ])

    for order in orders:
        order.write({"dally_shop_workflow_state": "received"})
        if not Transition.search_count([
            ("order_id", "=", order.id),
            ("to_state", "=", "received"),
        ]):
            Transition.create({
                "order_id": order.id,
                "from_state": False,
                "to_state": "received",
                "changed_by_id": SUPERUSER_ID,
                "notification_queued": False,
            })
