# -*- coding: utf-8 -*-
"""Registre sans PII des demandes de réception Dally Ops."""

from odoo import fields, models


class DallyOpsIntakeRequest(models.Model):
    _name = "dally.ops.intake.request"
    _description = "Dally Ops — registre d'idempotence des réceptions"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    payload_hash = fields.Char(required=True, readonly=True)
    state = fields.Selection(
        [("created", "Réception créée")], required=True, readonly=True,
    )
    shipment_id = fields.Many2one(
        "dally.shipment", required=True, index=True, ondelete="cascade", readonly=True,
    )
    package_id = fields.Many2one(
        "dally.shipment.package", required=True, index=True,
        ondelete="cascade", readonly=True,
    )
    line_uuid = fields.Char(required=True, readonly=True)
    operator_user_id = fields.Many2one(
        "res.users", required=True, index=True, readonly=True,
    )
    created_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True,
    )

    _request_unique = models.Constraint(
        "UNIQUE(company_id, request_uuid)",
        "Cette demande de réception a déjà été traitée.",
    )
