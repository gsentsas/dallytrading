# -*- coding: utf-8 -*-
"""Agenda partagé Dally Ops, projeté sur ``calendar.event`` natif."""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError

from .calendar_event import KINDS
from .ops_errors import DallyOpsConflict, DallyOpsError, DallyOpsNotFound


CREATE_FIELDS = frozenset({
    "request_uuid", "customer_reference", "kind", "start_at", "end_at",
    "consolidation_reference", "location", "note",
})
CREATE_REQUIRED = CREATE_FIELDS - {"consolidation_reference"}
RESCHEDULE_FIELDS = frozenset({"request_uuid", "start_at", "end_at"})
ACTION_FIELDS = frozenset({"request_uuid"})
FORBIDDEN_FIELDS = frozenset({
    "id", "calendar_event_id", "partner_id", "customer_id", "company_id",
    "user_id", "organizer_id", "name", "partner_ids", "attendee_ids",
    "alarm_ids", "state", "status", "dally_ops_status",
    "dally_ops_reference", "rescheduled_from_id", "rescheduled_to_id",
})
KIND_CODES = frozenset(code for code, _label in KINDS)
KIND_LABELS = dict(KINDS)
MAX_RANGE_SECONDS = 31 * 24 * 60 * 60
MAX_DURATION_SECONDS = 24 * 60 * 60


class DallyOpsAppointmentService(models.AbstractModel):
    _name = "dally.ops.appointment.service"
    _description = "Dally Ops — agenda client"

    # ------------------------------------------------------------------
    # Création et lectures
    # ------------------------------------------------------------------

    @api.model
    def create_appointment(self, payload):
        self._require_ops()
        data = self._validate_create(payload)
        digest = self._digest(data)
        with self.env.cr.savepoint():
            self._lock_request("create", data["request_uuid"])
            replay = self._replay("create", data["request_uuid"], digest)
            if replay is not None:
                self._audit(
                    "appointment_create_replayed", replay["event"],
                    data["request_uuid"])
                return replay["result"]

            customer = self._resolve_customer(data["customer_reference"])
            consolidation = self._resolve_consolidation(
                data.get("consolidation_reference"))
            event = self._create_event(
                reference=data["request_uuid"], customer=customer,
                consolidation=consolidation, kind=data["kind"],
                start=data["start"], stop=data["stop"],
                location=data["location"], note=data["note"],
                rescheduled_from=False)
            result = {
                "status": "created",
                "appointment": self._dto_detail(event),
            }
            self._record_request(
                "create", data["request_uuid"], digest, event, result)
            self._audit("appointment_recorded", event, data["request_uuid"])
            return result

    @api.model
    def list_appointments(self, start_at, end_at):
        self._require_ops()
        start, stop = self._validate_period(start_at, end_at)
        events = self.env["calendar.event"].sudo().search([
            *self._domain(),
            ("start", ">=", fields.Datetime.to_string(start)),
            ("start", "<", fields.Datetime.to_string(stop)),
        ], order="start asc, id asc", limit=500)
        return {
            "from": self._iso(start),
            "to": self._iso(stop),
            "appointments": [self._dto_list(event) for event in events],
        }

    @api.model
    def get_appointment(self, reference):
        self._require_ops()
        return self._dto_detail(self._resolve_event(reference))

    # ------------------------------------------------------------------
    # Transitions discrètes
    # ------------------------------------------------------------------

    @api.model
    def mark_present(self, reference, payload):
        return self._transition(reference, payload, "present")

    @api.model
    def mark_absent(self, reference, payload):
        return self._transition(reference, payload, "absent")

    @api.model
    def _transition(self, reference, payload, target):
        self._require_ops()
        reference = self._uuid(reference, "reference")
        request_uuid = self._validate_action(payload)
        operation = target
        digest = self._digest({"reference": reference, "target": target})
        with self.env.cr.savepoint():
            self._lock_request(operation, request_uuid)
            replay = self._replay(operation, request_uuid, digest)
            if replay is not None:
                self._audit(
                    "appointment_%s_replayed" % target,
                    replay["event"], request_uuid)
                return replay["result"]

            event = self._resolve_event(reference)
            self._lock_event(event)
            if event.dally_ops_status != "scheduled":
                raise DallyOpsConflict(
                    _("Le rendez-vous a déjà changé d'état."),
                    code="appointment_state_changed")
            event.sudo().write({"dally_ops_status": target})
            result = {
                "status": target,
                "appointment": self._dto_detail(event),
            }
            self._record_request(
                operation, request_uuid, digest, event, result)
            self._audit(
                "appointment_marked_%s" % target, event, request_uuid)
            return result

    @api.model
    def reschedule(self, reference, payload):
        self._require_ops()
        reference = self._uuid(reference, "reference")
        data = self._validate_reschedule(payload)
        digest = self._digest({
            "reference": reference,
            "start_at": self._iso(data["start"]),
            "end_at": self._iso(data["stop"]),
        })
        with self.env.cr.savepoint():
            self._lock_request("reschedule", data["request_uuid"])
            replay = self._replay(
                "reschedule", data["request_uuid"], digest)
            if replay is not None:
                self._audit(
                    "appointment_reschedule_replayed", replay["event"],
                    data["request_uuid"])
                return replay["result"]

            old = self._resolve_event(reference)
            self._lock_event(old)
            if old.dally_ops_status not in ("scheduled", "absent"):
                raise DallyOpsConflict(
                    _("Le rendez-vous ne peut plus être reporté."),
                    code="appointment_state_changed")

            new = self._create_event(
                reference=str(uuid.uuid4()),
                customer=old.dally_ops_customer_id,
                consolidation=old.dally_ops_consolidation_id,
                kind=old.dally_ops_kind,
                start=data["start"], stop=data["stop"],
                location=old.location or "", note=old.dally_ops_note or "",
                rescheduled_from=old)
            old.sudo().write({
                "dally_ops_status": "rescheduled",
                "dally_ops_rescheduled_to_id": new.id,
            })
            result = {
                "status": "rescheduled",
                "appointment": self._dto_detail(new),
                "previous_reference": old.dally_ops_reference,
            }
            self._record_request(
                "reschedule", data["request_uuid"], digest, old, result,
                result_event=new)
            self._audit("appointment_rescheduled", old, data["request_uuid"])
            return result

    # ------------------------------------------------------------------
    # Passage vers la réception existante
    # ------------------------------------------------------------------

    @api.model
    def prepare_reception(self, reference):
        self._require_ops()
        event = self._resolve_event(reference)
        self._lock_event(event)
        if event.dally_ops_status != "present":
            raise DallyOpsConflict(
                _("Le client doit être présent avant la réception."),
                code="appointment_not_present")
        customer = self._validate_partner(event.dally_ops_customer_id)
        consolidation = event.dally_ops_consolidation_id
        if consolidation and not self._consolidation_is_open(consolidation):
            consolidation = self.env["dally.freight.consolidation"].browse()

        handle = self.env["dally.ops.customer.service"].get_or_create_handle(customer)
        result = {
            "customer_reference": handle,
            "customer_name": customer.name or "",
            "consolidation_reference": consolidation.name if consolidation else None,
        }
        self._audit("appointment_reception_prepared", event, False)
        return result

    # ------------------------------------------------------------------
    # Résolution et écriture native
    # ------------------------------------------------------------------

    @api.model
    def _create_event(self, *, reference, customer, consolidation, kind,
                      start, stop, location, note, rescheduled_from):
        operator = self.env.user
        Event = (
            self.env["calendar.event"].sudo()
            .with_company(self.env.company)
            .with_context(
                no_mail_to_attendees=True,
                dont_notify=True,
                skip_attendee_notification=True,
                skip_contact_description=True,
                mail_create_nolog=True,
                mail_notrack=True,
                tracking_disable=True,
            )
        )
        return Event.create({
            "name": "Dally Ops — %s — %s" % (
                KIND_LABELS[kind], customer.name or _("Client")),
            "start": fields.Datetime.to_string(start),
            "stop": fields.Datetime.to_string(stop),
            "allday": False,
            # Le sudo donne l'accès au modèle ; il ne choisit jamais le owner.
            "user_id": operator.id,
            "partner_ids": [Command.set([])],
            "attendee_ids": [Command.clear()],
            "alarm_ids": [Command.set([])],
            "description": False,
            "notes": False,
            "location": location,
            "privacy": "confidential",
            "show_as": "busy",
            "dally_ops_appointment": True,
            "dally_ops_reference": reference,
            "dally_ops_company_id": self.env.company.id,
            "dally_ops_customer_id": customer.id,
            "dally_ops_consolidation_id": consolidation.id if consolidation else False,
            "dally_ops_kind": kind,
            "dally_ops_status": "scheduled",
            "dally_ops_created_by_user_id": operator.id,
            "dally_ops_rescheduled_from_id": (
                rescheduled_from.id if rescheduled_from else False),
            "dally_ops_note": note,
        })

    @api.model
    def _resolve_customer(self, token):
        handle = self.env["dally.ops.customer.handle"].sudo().search([
            ("token", "=", token),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not handle:
            raise DallyOpsNotFound(_("Client introuvable."), code="customer_not_found")
        return self._validate_partner(handle.partner_id)

    @api.model
    def _validate_partner(self, partner):
        if (
            not partner
            or not partner.active
            or (partner.company_id and partner.company_id != self.env.company)
        ):
            raise DallyOpsNotFound(_("Client introuvable."), code="customer_not_found")
        return partner

    @api.model
    def _resolve_consolidation(self, reference):
        if reference in (None, False, ""):
            return self.env["dally.freight.consolidation"].browse()
        if not isinstance(reference, str) or not reference.strip():
            raise DallyOpsConflict(
                _("Le départ n'est pas ouvert."), code="consolidation_not_open")
        consolidation = self.env["dally.freight.consolidation"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("name", "=", reference.strip()),
            ("active", "=", True),
            ("state", "=", "collecting"),
            ("transport_mode", "in", ["air", "sea"]),
        ], limit=1)
        if not consolidation:
            raise DallyOpsConflict(
                _("Le départ n'est pas ouvert."), code="consolidation_not_open")
        return consolidation

    @api.model
    def _consolidation_is_open(self, consolidation):
        return bool(
            consolidation
            and consolidation.company_id == self.env.company
            and consolidation.active
            and consolidation.state == "collecting"
            and consolidation.transport_mode in ("air", "sea"))

    @api.model
    def _resolve_event(self, reference):
        reference = self._uuid(reference, "reference")
        event = self.env["calendar.event"].sudo().search([
            *self._domain(),
            ("dally_ops_reference", "=", reference),
        ], limit=1)
        if not event:
            raise DallyOpsNotFound(
                _("Rendez-vous introuvable."), code="appointment_not_found")
        return event

    @api.model
    def _domain(self):
        return [
            ("dally_ops_appointment", "=", True),
            ("dally_ops_company_id", "=", self.env.company.id),
            ("active", "=", True),
        ]

    @api.model
    def _lock_event(self, event):
        event.flush_recordset(["dally_ops_status"])
        self.env.cr.execute(
            "SELECT id FROM calendar_event WHERE id = %s FOR UPDATE",
            [event.id])
        event.invalidate_recordset([
            "dally_ops_status", "dally_ops_rescheduled_to_id"])

    # ------------------------------------------------------------------
    # Validation stricte
    # ------------------------------------------------------------------

    @api.model
    def _validate_create(self, payload):
        self._validate_keys(payload, CREATE_FIELDS, CREATE_REQUIRED)
        start, stop = self._times(payload.get("start_at"), payload.get("end_at"))
        kind = payload.get("kind")
        if kind not in KIND_CODES:
            raise DallyOpsError(_("Type de rendez-vous invalide."), status=422)
        consolidation = payload.get("consolidation_reference")
        if consolidation is not None:
            consolidation = self._text(
                consolidation, "consolidation_reference", 120)
        return {
            "request_uuid": self._uuid(payload.get("request_uuid"), "request_uuid"),
            "customer_reference": self._uuid(
                payload.get("customer_reference"), "customer_reference"),
            "kind": kind,
            "start": start,
            "stop": stop,
            "start_at": self._iso(start),
            "end_at": self._iso(stop),
            "consolidation_reference": consolidation,
            "location": self._text(payload.get("location"), "location", 200),
            "note": self._text(
                payload.get("note"), "note", 2000, allow_empty=True),
        }

    @api.model
    def _validate_reschedule(self, payload):
        self._validate_keys(payload, RESCHEDULE_FIELDS, RESCHEDULE_FIELDS)
        start, stop = self._times(payload.get("start_at"), payload.get("end_at"))
        return {
            "request_uuid": self._uuid(payload.get("request_uuid"), "request_uuid"),
            "start": start,
            "stop": stop,
        }

    @api.model
    def _validate_action(self, payload):
        self._validate_keys(payload, ACTION_FIELDS, ACTION_FIELDS)
        return self._uuid(payload.get("request_uuid"), "request_uuid")

    @staticmethod
    def _validate_keys(payload, allowed, required):
        if not isinstance(payload, dict):
            raise DallyOpsError(_("Demande invalide."))
        unknown = set(payload) - allowed
        if unknown:
            message = (
                _("Champ réservé au serveur.")
                if unknown & FORBIDDEN_FIELDS
                else _("Champ non pris en charge."))
            raise DallyOpsError(message)
        if not required.issubset(payload):
            raise DallyOpsError(_("Un champ obligatoire est manquant."))

    @classmethod
    def _times(cls, start_value, stop_value):
        start = cls._aware_datetime(start_value, "start_at")
        stop = cls._aware_datetime(stop_value, "end_at")
        seconds = (stop - start).total_seconds()
        if seconds <= 0 or seconds > MAX_DURATION_SECONDS:
            raise DallyOpsError(
                _("La durée du rendez-vous est invalide."),
                code="invalid_appointment_period", status=422)
        return start, stop

    @classmethod
    def _validate_period(cls, start_value, stop_value):
        start = cls._aware_datetime(start_value, "from")
        stop = cls._aware_datetime(stop_value, "to")
        seconds = (stop - start).total_seconds()
        if seconds <= 0 or seconds > MAX_RANGE_SECONDS:
            raise DallyOpsError(
                _("La plage d'agenda est invalide."),
                code="invalid_appointment_range", status=422)
        return start, stop

    @staticmethod
    def _aware_datetime(value, field_name):
        if not isinstance(value, str) or not value.strip():
            raise DallyOpsError(
                _("Date et heure avec fuseau obligatoires : %s.", field_name),
                code="timezone_required", status=422)
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise DallyOpsError(
                _("Date et heure avec fuseau obligatoires : %s.", field_name),
                code="timezone_required", status=422)
        return parsed.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)

    @staticmethod
    def _uuid(value, field_name):
        if not isinstance(value, str):
            raise DallyOpsError(_("Identifiant invalide : %s.", field_name))
        try:
            return str(uuid.UUID(value.strip()))
        except (ValueError, AttributeError):
            raise DallyOpsError(_("Identifiant invalide : %s.", field_name))

    @staticmethod
    def _text(value, field_name, limit, allow_empty=False):
        if not isinstance(value, str):
            raise DallyOpsError(_("Champ invalide : %s.", field_name))
        text = value.strip()
        if (not text and not allow_empty) or len(text) > limit:
            raise DallyOpsError(_("Champ invalide : %s.", field_name))
        return text

    # ------------------------------------------------------------------
    # Idempotence, audit et DTO
    # ------------------------------------------------------------------

    @api.model
    def _lock_request(self, operation, request_uuid):
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ["ops-appointment:%s:%s:%s" % (
                self.env.company.id, operation, request_uuid)])

    @api.model
    def _replay(self, operation, request_uuid, digest):
        row = self.env["dally.ops.appointment.request"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("operation", "=", operation),
            ("request_uuid", "=", request_uuid),
        ], limit=1)
        if not row:
            return None
        if row.payload_hash != digest:
            raise DallyOpsConflict(
                _("Cette demande a déjà été traitée autrement."),
                code="idempotency_conflict")
        result = json.loads(row.result_snapshot)
        result["status"] = "replayed"
        return {"event": row.calendar_event_id, "result": result}

    @api.model
    def _record_request(self, operation, request_uuid, digest, event, result,
                        result_event=False):
        self.env["dally.ops.appointment.request"].sudo().create({
            "request_uuid": request_uuid,
            "company_id": self.env.company.id,
            "operation": operation,
            "payload_hash": digest,
            "calendar_event_id": event.id,
            "result_calendar_event_id": result_event.id if result_event else False,
            "operator_user_id": self.env.uid,
            "result_snapshot": json.dumps(
                result, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")),
        })

    @api.model
    def _audit(self, action, event, request_uuid):
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": action,
            "entity_model": "calendar.event",
            "entity_res_id": event.id,
            "request_uuid": request_uuid or False,
        })

    @staticmethod
    def _digest(data):
        serializable = {
            key: value for key, value in data.items()
            if key not in ("start", "stop", "request_uuid")
        }
        canonical = json.dumps(
            serializable, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _iso(value):
        return value.replace(tzinfo=timezone.utc).isoformat()

    @classmethod
    def _dto_list(cls, event):
        return {
            "reference": event.dally_ops_reference,
            "kind": event.dally_ops_kind,
            "status": event.dally_ops_status,
            "start_at": cls._iso(event.start),
            "end_at": cls._iso(event.stop),
            "customer": {"name": event.dally_ops_customer_id.name or ""},
            "consolidation_reference": (
                event.dally_ops_consolidation_id.name
                if event.dally_ops_consolidation_id else None),
            "location": event.location or "",
        }

    @classmethod
    def _dto_detail(cls, event):
        result = cls._dto_list(event)
        customer = event.dally_ops_customer_id
        result["customer"] = {
            "name": customer.name or "",
            "phone": customer.phone or "",
            "whatsapp": customer.dally_whatsapp or "",
        }
        result["note"] = event.dally_ops_note or ""
        result["rescheduled_from_reference"] = (
            event.dally_ops_rescheduled_from_id.dally_ops_reference
            if event.dally_ops_rescheduled_from_id else None)
        result["rescheduled_to_reference"] = (
            event.dally_ops_rescheduled_to_id.dally_ops_reference
            if event.dally_ops_rescheduled_to_id else None)
        return result

    @api.model
    def _require_ops(self):
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))
