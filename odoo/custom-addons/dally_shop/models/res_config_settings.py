# -*- coding: utf-8 -*-
"""
Réglage du tarif boutique.

Le tarif public est une décision commerciale, pas une constante de code : il
appartient au propriétaire, et il doit pouvoir en changer sans déploiement. Un
`ir.config_parameter` exposé dans les réglages est la façon dont Odoo traite
exactement ce cas.

Il n'y a volontairement aucune valeur par défaut. Tant que le tarif n'est pas
choisi, la boutique refuse d'afficher des prix — voir
`product.template._dally_shop_pricelist`.
"""

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    dally_shop_pricelist_id = fields.Many2one(
        comodel_name="product.pricelist",
        string="Tarif de la boutique",
        config_parameter="dally_shop.pricelist_id",
        help="Le tarif qui décide des prix publics. Sans lui, la boutique "
             "n'affiche aucun prix plutôt que de retomber sur le prix de liste, "
             "qui n'a pas été décidé pour la vente publique.",
    )
