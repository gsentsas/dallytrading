# -*- coding: utf-8 -*-
"""Qui a fait quoi, et quand.

## Pourquoi ce journal est nécessaire

Les écritures Ops passent par un privilège serveur. `create_uid` porte donc le
superutilisateur, et la trace native d'Odoo répond « le système » à la question
« qui a créé cette fiche ? ». Ce n'est pas une réponse.

Ce journal conserve l'opérateur réel, celui dont la session a été présentée.

## Pourquoi il ne contient aucune donnée personnelle

Un audit sert à retrouver un geste, pas à reconstituer un fichier clients.
Recopier ici le nom, le numéro et l'adresse créerait une seconde base de
données personnelles — avec les mêmes obligations et une surveillance moindre.
On garde le modèle et l'identifiant technique de l'objet touché : de quoi
remonter à la fiche quand c'est légitime, rien de plus.
"""

import uuid

from odoo import fields, models


class DallyOpsAuditEvent(models.Model):
    _name = "dally.ops.audit.event"
    _description = "Dally Ops — journal des gestes opérateur"
    _order = "created_at desc, id desc"
    _rec_name = "action"

    event_uuid = fields.Char(
        required=True, index=True, readonly=True, copy=False,
        default=lambda self: str(uuid.uuid4()))
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    operator_user_id = fields.Many2one("res.users", required=True, index=True, readonly=True)
    action = fields.Char(required=True, index=True, readonly=True)
    entity_model = fields.Char(readonly=True)
    entity_res_id = fields.Integer(readonly=True)
    request_uuid = fields.Char(index=True, readonly=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _event_uuid_unique = models.Constraint(
        "UNIQUE(event_uuid)", "Un événement d'audit ne peut être enregistré deux fois.")
