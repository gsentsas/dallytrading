# -*- coding: utf-8 -*-
"""La référence client opaque de Dally Ops.

## Pourquoi ne pas envoyer l'identifiant Odoo

`partner_id: 3728` dans le navigateur, c'est un compteur. Il se décrémente, il
se recopie dans une barre d'adresse, il dit combien de clients existent et il
permet d'en désigner un qu'on n'a jamais rencontré. Rien de tout cela n'est
nécessaire pour réceptionner un colis.

Le jeton posé ici est un UUID version 4 : tiré au hasard, sans ordre, sans
information sur le contenu de la base. Le connaître ne permet pas d'en deviner
un autre.

## Pourquoi une table plutôt qu'un chiffrement

Un identifiant chiffré aurait évité la table, mais il aurait aussi rendu le
lien indestructible : révoquer l'accès à une fiche aurait demandé de changer
une clé globale. Ici, la correspondance est une ligne — elle s'inspecte, elle
se supprime, et elle disparaît avec le partenaire (`ondelete="cascade"`).

## Ce que ce modèle n'est pas

Il n'est pas une autorisation. Détenir un jeton ne donne aucun droit : les
routes qui l'accepteront devront, à chaque fois, revérifier la société, l'état
du dossier et les droits de l'opérateur. Le jeton désigne, il n'autorise pas.
"""

import uuid

from odoo import fields, models


class DallyOpsCustomerHandle(models.Model):
    _name = "dally.ops.customer.handle"
    _description = "Dally Ops — référence client opaque"
    _rec_name = "token"

    token = fields.Char(
        required=True, index=True, copy=False, readonly=True,
        default=lambda self: str(uuid.uuid4()),
        string="Référence Ops",
    )
    partner_id = fields.Many2one(
        "res.partner", required=True, index=True, ondelete="cascade",
        string="Client",
    )
    company_id = fields.Many2one(
        "res.company", required=True, index=True, string="Société",
    )
    created_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True,
        string="Créée le",
    )

    _token_unique = models.Constraint(
        "UNIQUE(token)", "Une référence Ops ne peut désigner qu'un seul client.")
    # Un client, une référence par société. C'est cette contrainte qui rend la
    # course de création inoffensive : le perdant relit ce que le gagnant a
    # écrit, au lieu de créer un doublon.
    _partner_company_unique = models.Constraint(
        "UNIQUE(company_id, partner_id)",
        "Ce client possède déjà une référence Ops dans cette société.")
