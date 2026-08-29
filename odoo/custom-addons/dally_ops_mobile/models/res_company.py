# -*- coding: utf-8 -*-
"""Le bénéficiaire opérationnel des encaissements Wave.

## Pourquoi une configuration et non une constante

Les transferts Wave du terrain arrivent tous sur un même compte : celui de la
personne qui tient la caisse Dakar. Écrire « Gilles » dans le code en ferait
une vérité de programme — fausse le jour où il part en congé, change de rôle
ou quitte l'entreprise, et corrigeable seulement par un déploiement.

Écrire son identifiant numérique serait pire encore : un `id` PostgreSQL ne
survit pas à une restauration, ne veut rien dire dans une autre base, et rend
un test vert pour de mauvaises raisons.

Le champ porte donc un **nom d'acteur de caisse** — la même identité métier
stable que les dépenses et les transferts internes emploient déjà — et c'est
`dally.ops.cash.actor.service` qui le résout en un compte unique, refusant de
choisir si la configuration est ambiguë.

## Pourquoi il n'a pas de valeur par défaut

Fail closed, comme `dally_ops_cash_actor`. Un encaissement dont le
bénéficiaire n'est pas configuré doit s'arrêter bruyamment et se corriger en
une minute, plutôt que de créditer une caisse choisie par défaut.
"""

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    dally_ops_wave_beneficiary = fields.Char(
        string="Bénéficiaire Wave (acteur de caisse)",
        copy=False,
        help="Nom d'acteur de caisse sur lequel arrivent les encaissements "
             "Wave du terrain. Doit correspondre exactement à l'acteur d'un "
             "seul compte Ops actif : le serveur refuse de choisir si "
             "plusieurs comptes le revendiquent.")
