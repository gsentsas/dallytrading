# -*- coding: utf-8 -*-
"""Request log and idempotency store (§41, §56).

Two jobs:

1. **Idempotency** — a client that retries after a timeout must get the original
   outcome, not a second record. The stored response is replayed verbatim.
2. **Traceability** — a correlation id links a website submission to the Odoo
   record it produced, so an incident can be followed end to end without
   guessing.

Payloads are stored, so this table holds customer-submitted data. It is
readable by administrators only, and never records credentials.
"""

import json

from odoo import _, api, fields, models

#: Characters of stored payload/response kept. Enough to diagnose, bounded so a
#: large upload cannot bloat the table.
PAYLOAD_MAX_LENGTH = 8000


class DallyApiRequest(models.Model):
    _name = "dally.api.request"
    _description = "DallyTrading API Request Log"
    _order = "create_date desc"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(
        string="Request UUID",
        required=True,
        index=True,
        readonly=True,
        help="Client-generated idempotency key.",
    )
    endpoint = fields.Char(string="Endpoint", required=True, readonly=True, index=True)
    api_key_id = fields.Many2one(
        comodel_name="dally.api.key",
        string="API Key",
        ondelete="restrict",
        readonly=True,
        index=True,
    )
    source_ip = fields.Char(string="Source IP", readonly=True)

    status_code = fields.Integer(string="HTTP Status", readonly=True, index=True)
    res_model = fields.Char(string="Created Model", readonly=True)
    res_id = fields.Integer(string="Created Record", readonly=True)

    payload = fields.Text(
        string="Request Payload",
        readonly=True,
        help="Truncated copy of the request, for diagnosis. Never contains the API key.",
    )
    response = fields.Text(
        string="Response",
        readonly=True,
        help="Response returned. Replayed verbatim when the same request UUID "
             "comes back, so a retry is indistinguishable from the original call.",
    )
    error_message = fields.Char(string="Error", readonly=True)

    _sql_constraints = [
        # The uniqueness guarantee behind idempotency. Enforced by the database
        # rather than by application logic, so two simultaneous retries cannot
        # both pass a "does it exist?" check.
        (
            "dally_api_request_uuid_endpoint_uniq",
            "UNIQUE(request_uuid, endpoint)",
            "This request has already been recorded for this endpoint.",
        ),
    ]

    @api.model
    def _truncate(self, value):
        if value is None:
            return False
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        if len(text) > PAYLOAD_MAX_LENGTH:
            return text[:PAYLOAD_MAX_LENGTH] + _("… [truncated]")
        return text

    @api.model
    def find_replay(self, request_uuid, endpoint):
        """Return a previous successful call to replay, if any.

        Only successful calls are replayed. A previous failure must be allowed to
        be retried — otherwise a transient error would be cached permanently and
        the customer could never resubmit.
        """
        if not request_uuid:
            return self.browse()
        return self.sudo().search(
            [
                ("request_uuid", "=", request_uuid),
                ("endpoint", "=", endpoint),
                ("status_code", ">=", 200),
                ("status_code", "<", 300),
            ],
            limit=1,
        )

    @api.model
    def log(self, request_uuid, endpoint, status_code, api_key=None, source_ip=None,
            payload=None, response=None, record=None, error_message=None):
        """Write a log entry. Never raises — logging must not break the API."""
        values = {
            "request_uuid": request_uuid or "",
            "endpoint": endpoint,
            "status_code": status_code,
            "api_key_id": api_key.id if api_key else False,
            "source_ip": source_ip or False,
            "payload": self._truncate(payload),
            "response": self._truncate(response),
            "error_message": (error_message or "")[:255] or False,
        }
        if record is not None and getattr(record, "id", False):
            values["res_model"] = record._name
            values["res_id"] = record.id

        try:
            return self.sudo().create(values)
        except Exception:  # noqa: BLE001
            # A duplicate uuid means a concurrent retry already logged it — the
            # unique constraint did its job. Any other failure must not turn a
            # successful business operation into a client-visible error.
            return self.browse()

    def action_open_record(self):
        """Open the Odoo record this request produced."""
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
            "target": "current",
        }
