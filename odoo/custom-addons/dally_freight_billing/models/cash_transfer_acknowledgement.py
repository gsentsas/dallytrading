# -*- coding: utf-8 -*-
"""L'accusé de réception d'un transfert de caisse.

## Pourquoi une remise n'est pas une réception

Quand Gilles remet cent mille francs à Dalanda, une seule des deux personnes
sait que l'argent est arrivé, et ce n'est pas Gilles. Un transfert enregistré
comme reçu au moment où il est saisi ne prouve donc rien : il enregistre une
intention, pas un fait.

Ces deux champs conservent le fait. Ils restent **facultatifs**, parce que le
flux historique du tableur n'a jamais eu d'accusé et n'en aura pas
rétroactivement : les rendre obligatoires refuserait des lignes qui existent
déjà et sont exactes.

## Pourquoi l'utilisateur, et pas seulement l'acteur

`to_actor` dit qui devait recevoir. `acknowledged_by_user_id` dit quel compte
a effectivement cliqué. Les deux se recoupent normalement — et le jour où ils
divergent, c'est précisément ce qu'on veut pouvoir lire.

C'est une trace technique, pas une responsabilité comptable : elle ne quitte
jamais le serveur, et aucune interface terrain ne l'expose.
"""

from odoo import fields, models


class DallyCashTransfer(models.Model):
    _inherit = "dally.cash.transfer"

    acknowledged_at = fields.Datetime(
        string="Réception confirmée le", copy=False, readonly=True,
        help="Horodatage de l'accusé de réception par le destinataire. "
             "Vide tant que les fonds n'ont pas été confirmés reçus.")
    acknowledged_by_user_id = fields.Many2one(
        "res.users", string="Confirmé par", copy=False, readonly=True,
        ondelete="restrict",
        help="Compte ayant confirmé la réception. Trace interne : le nom "
             "d'acteur de caisse reste la référence métier.")
