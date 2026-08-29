# -*- coding: utf-8 -*-
"""La projection native des rendez-vous terrain dans Calendar.

Le client est une relation métier dédiée, jamais un participant Calendar.
Cela garde l'agenda natif sans transformer une saisie interne en invitation.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


KINDS = [
    ("dropoff", "Dépôt colis"),
    ("pickup", "Collecte client"),
    ("call", "Appel"),
    ("whatsapp", "WhatsApp"),
    ("other", "Autre"),
]

STATUSES = [
    ("scheduled", "Prévu"),
    ("present", "Présent"),
    ("absent", "Absent"),
    ("rescheduled", "Reporté"),
]


class CalendarEvent(models.Model):
    _inherit = "calendar.event"

    dally_ops_appointment = fields.Boolean(
        string="Rendez-vous Dally Ops", default=False, index=True, copy=False)
    dally_ops_reference = fields.Char(
        string="Référence Ops", index=True, copy=False, readonly=True)
    dally_ops_company_id = fields.Many2one(
        "res.company", string="Société Ops", index=True, copy=False,
        ondelete="restrict")
    dally_ops_customer_id = fields.Many2one(
        "res.partner", string="Client Ops", index=True, copy=False,
        ondelete="restrict")
    dally_ops_consolidation_id = fields.Many2one(
        "dally.freight.consolidation", string="Départ Ops", index=True,
        copy=False, ondelete="restrict")
    dally_ops_kind = fields.Selection(
        KINDS, string="Type Ops", index=True, copy=False)
    dally_ops_status = fields.Selection(
        STATUSES, string="Statut Ops", index=True, copy=False)
    dally_ops_created_by_user_id = fields.Many2one(
        "res.users", string="Créé par", index=True, copy=False,
        ondelete="restrict")
    dally_ops_rescheduled_from_id = fields.Many2one(
        "calendar.event", string="Reporté depuis", index=True, copy=False,
        ondelete="restrict")
    dally_ops_rescheduled_to_id = fields.Many2one(
        "calendar.event", string="Reporté vers", index=True, copy=False,
        ondelete="restrict")
    dally_ops_note = fields.Text(string="Note Ops", copy=False)

    _dally_ops_reference_unique = models.Constraint(
        "UNIQUE(dally_ops_reference)",
        "Une référence de rendez-vous Ops ne peut être utilisée qu'une fois.")

    @api.constrains(
        "dally_ops_appointment", "dally_ops_reference", "dally_ops_company_id",
        "dally_ops_customer_id", "dally_ops_kind", "dally_ops_status",
        "dally_ops_created_by_user_id")
    def _check_dally_ops_required_fields(self):
        for event in self.filtered("dally_ops_appointment"):
            if not all((
                event.dally_ops_reference,
                event.dally_ops_company_id,
                event.dally_ops_customer_id,
                event.dally_ops_kind,
                event.dally_ops_status,
                event.dally_ops_created_by_user_id,
            )):
                raise ValidationError(
                    "Un rendez-vous Dally Ops doit porter son identité métier complète.")

    def _skip_send_mail_status_update(self):
        """Défense en profondeur : un rendez-vous Ops n'envoie jamais d'invitation."""
        self.ensure_one()
        return bool(
            self.dally_ops_appointment
            or super()._skip_send_mail_status_update())
