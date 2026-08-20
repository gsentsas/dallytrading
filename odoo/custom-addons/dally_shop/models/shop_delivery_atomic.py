# -*- coding: utf-8 -*-
"""Rend indivisible la création d'une commande et son snapshot de remise.

Le socle checkout crée d'abord ``sale.order`` puis le Lot C y rattache méthode,
frais et adresse. Même si toutes les validations connues sont effectuées avant la
création, une contrainte future sur l'un de ces champs ne doit jamais laisser une
commande boutique partiellement créée parce qu'un contrôleur a traduit
l'exception en réponse HTTP.

Le savepoint englobe donc l'ensemble de la chaîne ``dally_shop_place_order``. Une
exception lors du snapshot annule aussi la commande, ses lignes, sa transition
initiale et le mail mis en file dans la même transaction.
"""

from odoo import api, models


class SaleOrderShopDeliveryAtomic(models.Model):
    _inherit = "sale.order"

    @api.model
    def dally_shop_place_order(
        self,
        cart_uuid,
        partner,
        lignes,
        mode_remise,
        invite=False,
        shipping=None,
    ):
        with self.env.cr.savepoint():
            return super().dally_shop_place_order(
                cart_uuid,
                partner,
                lignes,
                mode_remise,
                invite=invite,
                shipping=shipping,
            )
