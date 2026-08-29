# -*- coding: utf-8 -*-
"""Ce que Dally Ops a déjà fait, pour ne pas le refaire.

Deux registres, parce que ce sont deux gestes : remettre, et confirmer avoir
reçu. Un seul registre les mélangerait, et un identifiant de demande rejoué
sur la mauvaise opération passerait inaperçu.

Aucun des deux n'a d'ACL : ils sont écrits par le service sous privilège
serveur, et rien ni personne n'a besoin de les lire depuis un téléphone.
"""

import uuid

from odoo import fields, models


class DallyOpsCashTransferRequest(models.Model):
    _name = "dally.ops.cash.transfer.request"
    _description = "Dally Ops — demandes de transfert de caisse"
    _order = "created_at desc, id desc"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    payload_hash = fields.Char(required=True, readonly=True)
    transfer_id = fields.Many2one(
        "dally.cash.transfer", required=True, index=True, readonly=True,
        ondelete="cascade")
    operator_user_id = fields.Many2one("res.users", required=True, readonly=True)
    result_snapshot = fields.Text(required=True, readonly=True)
    created_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True)

    _request_unique = models.Constraint(
        "UNIQUE(company_id, request_uuid)",
        "Une demande de transfert ne peut être enregistrée deux fois.")


class DallyOpsCashTransferAckRequest(models.Model):
    _name = "dally.ops.cash.transfer.ack.request"
    _description = "Dally Ops — accusés de réception de transfert"
    _order = "created_at desc, id desc"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    payload_hash = fields.Char(required=True, readonly=True)
    transfer_id = fields.Many2one(
        "dally.cash.transfer", required=True, index=True, readonly=True,
        ondelete="cascade")
    operator_user_id = fields.Many2one("res.users", required=True, readonly=True)
    result_snapshot = fields.Text(required=True, readonly=True)
    created_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True)

    _request_unique = models.Constraint(
        "UNIQUE(company_id, request_uuid)",
        "Un accusé de réception ne peut être enregistré deux fois.")
