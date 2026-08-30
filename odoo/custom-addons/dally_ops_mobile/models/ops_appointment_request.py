# -*- coding: utf-8 -*-
"""Registre sans PII des créations et transitions de rendez-vous Ops."""

from odoo import fields, models


class DallyOpsAppointmentRequest(models.Model):
    _name = "dally.ops.appointment.request"
    _description = "Dally Ops — demandes de rendez-vous"
    _order = "created_at desc, id desc"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", required=True, index=True, readonly=True)
    operation = fields.Selection([
        ("create", "Création"),
        ("present", "Présent"),
        ("absent", "Absent"),
        ("reschedule", "Report"),
    ], required=True, index=True, readonly=True)
    payload_hash = fields.Char(required=True, readonly=True)
    calendar_event_id = fields.Many2one(
        "calendar.event", required=True, index=True, readonly=True,
        ondelete="cascade")
    result_calendar_event_id = fields.Many2one(
        "calendar.event", index=True, readonly=True, ondelete="cascade")
    operator_user_id = fields.Many2one(
        "res.users", required=True, index=True, readonly=True)
    result_snapshot = fields.Text(required=True, readonly=True)
    created_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True)

    _request_unique = models.Constraint(
        "UNIQUE(company_id, operation, request_uuid)",
        "Cette demande de rendez-vous a déjà été traitée.")
