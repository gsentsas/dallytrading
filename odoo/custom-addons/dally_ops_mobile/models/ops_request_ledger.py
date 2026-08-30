# -*- coding: utf-8 -*-
"""Le registre des demandes d'écriture venues du terrain.

## Pourquoi il existe

C'est la première écriture qu'un téléphone déclenche. Un entrepôt n'a pas la
4G d'un bureau : la requête part, Odoo crée la fiche, la réponse se perd, et
l'opérateur appuie une seconde fois. Sans registre, le client existe deux fois
et personne ne le saura avant l'audit.

Le registre retient donc l'issue de chaque demande, indexée par l'identifiant
que le téléphone a tiré **avant** le premier envoi. Rejouer devient alors une
relecture.

## Pourquoi une empreinte et non la charge

Deux demandes peuvent porter le même identifiant sans porter la même
intention — un bogue de l'application, un identifiant recyclé, une saisie
corrigée entre deux tentatives. Renvoyer le premier résultat serait alors un
mensonge silencieux : l'opérateur croirait avoir enregistré ce qu'il vient de
taper.

L'empreinte SHA-256 de la charge normalisée tranche : même identifiant et même
empreinte, c'est un rejeu ; même identifiant et empreinte différente, c'est un
conflit. Elle a un second mérite — elle ne recopie ni le nom, ni le numéro, ni
l'adresse dans une table de plus.
"""

from odoo import fields, models


class DallyOpsCustomerRequest(models.Model):
    _name = "dally.ops.customer.request"
    _description = "Dally Ops — registre d'idempotence des demandes client"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    operation = fields.Char(required=True, index=True, readonly=True)
    #: SHA-256 hexadécimal de la charge normalisée. Aucune donnée personnelle.
    payload_hash = fields.Char(required=True, readonly=True)
    state = fields.Selection(
        [("created", "Fiche créée"), ("existing", "Fiche existante retrouvée")],
        required=True, readonly=True,
    )
    partner_id = fields.Many2one("res.partner", index=True, ondelete="cascade", readonly=True)
    customer_handle_id = fields.Many2one(
        "dally.ops.customer.handle", ondelete="cascade", readonly=True)
    operator_user_id = fields.Many2one("res.users", required=True, readonly=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    # C'est cette contrainte qui fait l'idempotence : deux tentatives portant le
    # même identifiant ne peuvent pas produire deux lignes, donc pas deux fiches.
    _request_unique = models.Constraint(
        "UNIQUE(company_id, operation, request_uuid)",
        "Cette demande a déjà été traitée.")
