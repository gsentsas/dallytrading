# -*- coding: utf-8 -*-
"""
Active XOF sur une base où `dally_shop` était déjà installé.

`post_init_hook` ne s'exécute qu'à l'**installation**. Sur une base existante — la
production — il ne rejoue pas, et la devise du tarif resterait inactive : le
propriétaire ne la verrait dans aucune liste, et le tarif de la boutique serait
illisible.

Les données du module portent bien `ref('base.XOF')`, mais elles sont en
`noupdate="1"` : sur une base où le tarif existe déjà, aucun champ n'est réécrit.
Mesuré — après montée de version, le tarif restait en USD. Ce script répare donc
deux choses : l'`active` de la devise, et la devise du tarif **si et seulement si**
celui-ci ne porte encore aucune règle de prix.

Il ne sélectionne pas le tarif : ouvrir la tarification est une décision du
propriétaire, et une migration qui la prendrait à sa place ouvrirait la boutique
au premier déploiement.
"""

from odoo import api, SUPERUSER_ID

from odoo.addons.dally_shop.hooks import activer_devise_xof, regler_devise_du_tarif


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    activer_devise_xof(env)
    regler_devise_du_tarif(env)
