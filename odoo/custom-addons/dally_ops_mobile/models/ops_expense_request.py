# -*- coding: utf-8 -*-
"""Les registres d'idempotence des dépenses de terrain.

Deux registres, parce que ce sont deux gestes : enregistrer la dépense, et lui
joindre une preuve. Les séparer est la condition pour que la photo puisse
échouer — ou être reprise plus tard — sans jamais remettre en cause l'argent
déjà sorti de la caisse.
"""

from odoo import fields, models


class DallyOpsExpenseRequest(models.Model):
    _name = "dally.ops.expense.request"
    _description = "Dally Ops — registre d'idempotence des dépenses"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    payload_hash = fields.Char(required=True, readonly=True)
    expense_id = fields.Many2one(
        "dally.cash.expense", required=True, index=True,
        ondelete="cascade", readonly=True)
    result_snapshot = fields.Text(required=True, readonly=True)
    operator_user_id = fields.Many2one("res.users", required=True, readonly=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _request_unique = models.Constraint(
        "UNIQUE(company_id, request_uuid)", "Cette dépense a déjà été enregistrée.")


class DallyOpsExpenseReceiptRequest(models.Model):
    _name = "dally.ops.expense.receipt.request"
    _description = "Dally Ops — registre d'idempotence des justificatifs"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    expense_id = fields.Many2one(
        "dally.cash.expense", required=True, index=True,
        ondelete="cascade", readonly=True)
    attachment_id = fields.Many2one(
        "ir.attachment", required=True, ondelete="restrict", readonly=True)
    #: SHA-256 du contenu binaire. Le contenu lui-même n'est jamais journalisé.
    content_hash = fields.Char(required=True, readonly=True)
    operator_user_id = fields.Many2one("res.users", required=True, readonly=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _request_unique = models.Constraint(
        "UNIQUE(company_id, request_uuid)", "Ce justificatif a déjà été envoyé.")
