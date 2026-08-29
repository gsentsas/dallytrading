# -*- coding: utf-8 -*-
"""Contrat natif et HTTP de l'agenda Dally Ops."""

import ast
import inspect
import json
import uuid

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.dally_ops_mobile.controllers import ops_appointments
from odoo.addons.dally_ops_mobile.models.ops_errors import (
    DallyOpsConflict, DallyOpsError, DallyOpsNotFound)

from .common import MODELES_TECHNIQUES_LISIBLES, modeles_lisibles


def executable_source(module):
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


class AppointmentBase:
    @classmethod
    def setup_appointment_data(cls):
        cls.company = cls.env["res.company"].create({"name": "Ops Agenda SA"})
        cls.other_company = cls.env["res.company"].create({"name": "Ops Agenda Autre"})
        cls.logistician = cls._user(
            "agenda.gilles", "Gilles Agenda",
            "dally_ops_mobile.group_dally_ops_logistician")
        cls.supervisor = cls._user(
            "agenda.dalanda", "Dalanda Agenda",
            "dally_ops_mobile.group_dally_ops_supervisor")
        cls.non_ops = cls._user("agenda.other", "Sans rôle Agenda", "base.group_user")
        cls.customer = cls.env["res.partner"].create({
            "name": "Aissatou Kandji", "company_id": cls.company.id,
            "phone": "+221 77 123 45 67", "dally_whatsapp": "+221 76 987 65 43",
            "email": "private@example.invalid",
        })
        cls.handle = cls.env["dally.ops.customer.handle"].sudo().create({
            "company_id": cls.company.id, "partner_id": cls.customer.id,
        })
        cls.consolidation = cls._consolidation("AIR-DSS-CDG-AGENDA-001")

    @classmethod
    def _user(cls, login, name, group, company=None):
        company = company or cls.company
        return cls.env["res.users"].create({
            "name": name, "login": login,
            "group_ids": [Command.set([cls.env.ref(group).id])],
            "company_id": company.id,
            "company_ids": [Command.set([company.id])],
        })

    @classmethod
    def _consolidation(cls, reference, company=None, **changes):
        company = company or cls.company
        values = {
            "name": reference, "company_id": company.id,
            "state": "collecting", "active": True,
            "transport_mode": "air", "direction": "export",
            "origin_country_id": cls.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": cls.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        }
        values.update(changes)
        return cls.env["dally.freight.consolidation"].create(values)

    def service(self, user=None, company=None):
        return (self.env["dally.ops.appointment.service"]
                .with_user(user or self.logistician)
                .with_company(company or self.company))

    def payload(self, **changes):
        values = {
            "request_uuid": str(uuid.uuid4()),
            "customer_reference": self.handle.token,
            "kind": "dropoff",
            "start_at": "2026-08-31T10:00:00+00:00",
            "end_at": "2026-08-31T10:30:00+00:00",
            "consolidation_reference": self.consolidation.name,
            "location": "Dépôt Dakar",
            "note": "3 cartons annoncés",
        }
        values.update(changes)
        return values

    def create(self, **changes):
        return self.service().create_appointment(self.payload(**changes))

    def event(self, reference):
        return self.env["calendar.event"].sudo().search([
            ("dally_ops_reference", "=", reference)], limit=1)


@tagged("post_install", "-at_install", "dally")
class TestOpsAppointmentNative(AppointmentBase, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.setup_appointment_data()

    def test_native_calendar_owner_company_customer_and_times(self):
        result = self.create()
        event = self.event(result["appointment"]["reference"])
        self.assertEqual(event._name, "calendar.event")
        self.assertTrue(event.dally_ops_appointment)
        self.assertEqual(event.dally_ops_company_id, self.company)
        self.assertEqual(event.dally_ops_customer_id, self.customer)
        self.assertEqual(event.dally_ops_consolidation_id, self.consolidation)
        self.assertEqual(event.user_id, self.logistician)
        self.assertNotEqual(event.user_id.id, 1)
        self.assertEqual(event.dally_ops_created_by_user_id, self.logistician)
        self.assertEqual(fields.Datetime.to_string(event.start), "2026-08-31 10:00:00")
        self.assertEqual(fields.Datetime.to_string(event.stop), "2026-08-31 10:30:00")
        self.assertEqual(event.dally_ops_status, "scheduled")

    def test_share_logistician_and_supervisor_work_but_non_ops_does_not(self):
        self.assertTrue(self.logistician.share)
        self.assertTrue(self.supervisor.share)
        for user in (self.logistician, self.supervisor):
            result = self.service(user).create_appointment(self.payload())
            self.assertEqual(result["status"], "created")
        with self.assertRaises(AccessError):
            self.service(self.non_ops).create_appointment(self.payload())

    def test_zero_calendar_acl_and_only_currency_readable(self):
        for model in ("calendar.event", "calendar.attendee",
                      "dally.ops.appointment.request", "res.partner"):
            self.assertFalse(self.env[model].with_user(self.logistician).has_access("read"))
        self.assertEqual(
            modeles_lisibles(self.env, self.logistician),
            set(MODELES_TECHNIQUES_LISIBLES))

    def test_no_client_attendee_alarm_invitation_or_partner_write(self):
        write_date = self.customer.write_date
        attendee_count = self.env["calendar.attendee"].sudo().search_count([])
        mail_count = self.env["mail.mail"].sudo().search_count([])
        result = self.create()
        event = self.event(result["appointment"]["reference"])
        self.assertFalse(event.partner_ids)
        self.assertFalse(event.attendee_ids)
        self.assertFalse(event.alarm_ids)
        self.assertEqual(self.env["calendar.attendee"].sudo().search_count([]), attendee_count)
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mail_count)
        self.assertEqual(self.customer.write_date, write_date)

    def test_ops_events_declare_themselves_exempt_from_invitations(self):
        """La défense en profondeur, vérifiée pour elle-même.

        Sans participant, Odoo n'envoie rien de toute façon : retirer cette
        garde ne casse donc rien de visible, et c'est précisément pourquoi elle
        a besoin de son propre test. Le jour où un participant apparaîtra — par
        un import, une reprise, une main maladroite — c'est elle qui empêchera
        le client de recevoir une invitation d'agenda interne.
        """
        reference = self.create()["appointment"]["reference"]
        event = self.event(reference)
        self.assertTrue(event.sudo()._skip_send_mail_status_update())
        ordinary = self.env["calendar.event"].sudo().create({
            "name": "Réunion interne",
            "start": "2026-08-31 08:00:00", "stop": "2026-08-31 08:30:00",
            "partner_ids": [(6, 0, [])], "alarm_ids": [(6, 0, [])],
        })
        self.assertFalse(ordinary._skip_send_mail_status_update())

    def test_offset_aware_timestamps_are_normalized_without_shift(self):
        paris = self.create(
            start_at="2026-08-31T12:00:00+02:00",
            end_at="2026-08-31T12:30:00+02:00")
        dakar = self.create(
            start_at="2026-08-31T10:00:00+00:00",
            end_at="2026-08-31T10:30:00+00:00")
        self.assertEqual(paris["appointment"]["start_at"], "2026-08-31T10:00:00+00:00")
        self.assertEqual(paris["appointment"]["start_at"], dakar["appointment"]["start_at"])
        for value in ("2026-08-31T10:00:00", "31/08/2026 10:00", ""):
            with self.assertRaises(DallyOpsError) as error:
                self.create(start_at=value)
            self.assertEqual(error.exception.code, "timezone_required")

    def test_strict_fields_kinds_period_and_server_native_fields(self):
        for field, value in (
            ("partner_id", self.customer.id), ("user_id", self.logistician.id),
            ("name", "Pirate"), ("partner_ids", [self.customer.id]),
            ("attendee_ids", [self.customer.id]), ("alarm_ids", []),
            ("state", "done"), ("status", "present"), ("calendar_event_id", 1),
        ):
            with self.assertRaises(DallyOpsError):
                self.create(**{field: value})
        with self.assertRaises(DallyOpsError):
            self.create(kind="meeting")
        for start, stop in (
            ("2026-08-31T10:00:00+00:00", "2026-08-31T10:00:00+00:00"),
            ("2026-08-31T10:30:00+00:00", "2026-08-31T10:00:00+00:00"),
            ("2026-08-31T10:00:00+00:00", "2026-09-02T10:00:01+00:00"),
        ):
            with self.assertRaises(DallyOpsError):
                self.create(start_at=start, end_at=stop)

    def test_customer_handle_is_revalidated_without_cross_company_disclosure(self):
        with self.assertRaises(DallyOpsNotFound) as error:
            self.create(customer_reference=str(uuid.uuid4()))
        self.assertEqual(error.exception.code, "customer_not_found")
        self.customer.active = False
        with self.assertRaises(DallyOpsNotFound):
            self.create()
        self.customer.active = True
        other_partner = self.env["res.partner"].create({
            "name": "Autre", "company_id": self.other_company.id})
        other_handle = self.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": other_partner.id, "company_id": self.other_company.id})
        with self.assertRaises(DallyOpsNotFound) as error:
            self.create(customer_reference=other_handle.token)
        self.assertEqual(error.exception.code, "customer_not_found")

    def test_consolidation_optional_open_and_company_scoped(self):
        result = self.create(consolidation_reference=None)
        self.assertIsNone(result["appointment"]["consolidation_reference"])
        closed = self._consolidation("AIR-AGENDA-CLOSED", state="draft")
        for consolidation in (
            closed,
            self._consolidation("ROAD-AGENDA", transport_mode="road"),
            self._consolidation(
                "AIR-AGENDA-OTHER", company=self.other_company),
        ):
            with self.assertRaises(DallyOpsConflict) as error:
                self.create(consolidation_reference=consolidation.name)
            self.assertEqual(error.exception.code, "consolidation_not_open")

    def test_create_replay_conflict_and_public_dto(self):
        payload = self.payload()
        first = self.service().create_appointment(payload)
        second = self.service().create_appointment(payload)
        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "replayed")
        self.assertEqual(first["appointment"]["reference"], second["appointment"]["reference"])
        self.assertEqual(self.env["calendar.event"].sudo().search_count([
            ("dally_ops_reference", "=", payload["request_uuid"])]), 1)
        with self.assertRaises(DallyOpsConflict) as error:
            self.service().create_appointment({**payload, "note": "autre"})
        self.assertEqual(error.exception.code, "idempotency_conflict")
        rendered = json.dumps(first)
        for forbidden in ("calendar_event_id", "partner_id", "company_id",
                          "user_id", "attendee_id", "alarm_id"):
            self.assertNotIn(forbidden, rendered)
        # L'ensemble exact, et non une liste d'interdits : « id » est une
        # sous-chaîne de presque toutes les clés, et aucune recherche de
        # sous-chaîne ne peut donc l'attraper.
        self.assertEqual(set(first["appointment"]), {
            "reference", "kind", "status", "start_at", "end_at", "customer",
            "consolidation_reference", "location", "note",
            "rescheduled_from_reference", "rescheduled_to_reference"})
        self.assertEqual(set(first["appointment"]["customer"]),
                         {"name", "phone", "whatsapp"})
        self.assertEqual(self.env["dally.ops.audit.event"].sudo().search_count([
            ("action", "=", "appointment_recorded"),
            ("entity_res_id", "=", self.event(payload["request_uuid"]).id)]), 1)


@tagged("post_install", "-at_install", "dally")
class TestOpsAppointmentAgenda(AppointmentBase, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.setup_appointment_data()

    def test_today_week_order_company_isolation_and_standard_event_hidden(self):
        later = self.create(
            start_at="2026-08-31T15:00:00+00:00",
            end_at="2026-08-31T15:30:00+00:00")
        earlier = self.create(
            start_at="2026-08-31T09:00:00+00:00",
            end_at="2026-08-31T09:30:00+00:00")
        self.env["calendar.event"].sudo().create({
            "name": "Événement Odoo standard", "start": "2026-08-31 10:00:00",
            "stop": "2026-08-31 10:30:00",
            "partner_ids": [Command.set([])], "attendee_ids": [Command.clear()],
        })
        other_partner = self.env["res.partner"].create({
            "name": "Autre", "company_id": self.other_company.id})
        other_handle = self.env["dally.ops.customer.handle"].sudo().create({
            "partner_id": other_partner.id, "company_id": self.other_company.id})
        self.service(company=self.other_company, user=self._user(
            "agenda.othercompany", "Autre Ops",
            "dally_ops_mobile.group_dally_ops_logistician",
            self.other_company)).create_appointment({
                **self.payload(), "request_uuid": str(uuid.uuid4()),
                "customer_reference": other_handle.token,
                "consolidation_reference": None,
            })
        result = self.service().list_appointments(
            "2026-08-31T00:00:00+00:00", "2026-09-01T00:00:00+00:00")
        refs = [item["reference"] for item in result["appointments"]]
        self.assertEqual(refs, [earlier["appointment"]["reference"],
                                later["appointment"]["reference"]])
        self.assertNotIn("Événement Odoo standard", json.dumps(result))

    def test_range_maximal_and_list_privacy_detail_contact(self):
        result = self.create()
        listed = self.service().list_appointments(
            "2026-08-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00")
        item = listed["appointments"][0]
        self.assertEqual(set(item["customer"]), {"name"})
        rendered = json.dumps(item)
        self.assertNotIn(self.customer.phone, rendered)
        self.assertNotIn(self.customer.email, rendered)
        detail = self.service().get_appointment(result["appointment"]["reference"])
        self.assertEqual(detail["customer"], {
            "name": self.customer.name,
            "phone": self.customer.phone,
            "whatsapp": self.customer.dally_whatsapp,
        })
        self.assertNotIn("email", json.dumps(detail))
        with self.assertRaises(DallyOpsError) as error:
            self.service().list_appointments(
                "2026-08-01T00:00:00+00:00", "2026-09-01T00:00:01+00:00")
        self.assertEqual(error.exception.code, "invalid_appointment_range")

    def test_present_absent_replays_and_serialized_conflict(self):
        present_ref = self.create()["appointment"]["reference"]
        request_uuid = str(uuid.uuid4())
        first = self.service().mark_present(present_ref, {"request_uuid": request_uuid})
        replay = self.service().mark_present(present_ref, {"request_uuid": request_uuid})
        self.assertEqual(first["appointment"]["status"], "present")
        self.assertEqual(replay["status"], "replayed")
        with self.assertRaises(DallyOpsConflict) as error:
            self.service().mark_absent(
                present_ref, {"request_uuid": str(uuid.uuid4())})
        self.assertEqual(error.exception.code, "appointment_state_changed")
        self.assertEqual(self.env["dally.ops.audit.event"].sudo().search_count([
            ("action", "=", "appointment_marked_present"),
            ("entity_res_id", "=", self.event(present_ref).id)]), 1)

        absent_ref = self.create()["appointment"]["reference"]
        absent = self.service().mark_absent(
            absent_ref, {"request_uuid": str(uuid.uuid4())})
        self.assertEqual(absent["appointment"]["status"], "absent")
        with self.assertRaises(DallyOpsConflict):
            self.service().mark_present(
                absent_ref, {"request_uuid": str(uuid.uuid4())})

    def test_reschedule_creates_linked_history_once(self):
        old_ref = self.create()["appointment"]["reference"]
        self.service().mark_absent(old_ref, {"request_uuid": str(uuid.uuid4())})
        request = {
            "request_uuid": str(uuid.uuid4()),
            "start_at": "2026-09-01T15:00:00+00:00",
            "end_at": "2026-09-01T15:30:00+00:00",
        }
        before = self.event(old_ref)
        kept = (before.start, before.stop)
        first = self.service().reschedule(old_ref, request)
        replay = self.service().reschedule(old_ref, request)
        old = self.event(old_ref)
        # Un report crée une occurrence ; il ne réécrit pas l'horaire passé.
        # Sans cette assertion, déplacer l'ancien événement en plus de créer le
        # nouveau passait inaperçu — et l'historique devenait faux.
        self.assertEqual((old.start, old.stop), kept)
        new = self.event(first["appointment"]["reference"])
        self.assertEqual(old.dally_ops_status, "rescheduled")
        self.assertEqual(new.dally_ops_status, "scheduled")
        self.assertEqual(old.dally_ops_rescheduled_to_id, new)
        self.assertEqual(new.dally_ops_rescheduled_from_id, old)
        self.assertEqual(new.dally_ops_customer_id, old.dally_ops_customer_id)
        self.assertEqual(new.dally_ops_consolidation_id, old.dally_ops_consolidation_id)
        self.assertEqual(new.dally_ops_kind, old.dally_ops_kind)
        self.assertEqual(replay["appointment"]["reference"], new.dally_ops_reference)
        self.assertEqual(self.env["calendar.event"].sudo().search_count([
            ("dally_ops_rescheduled_from_id", "=", old.id)]), 1)
        self.assertEqual(self.env["dally.ops.audit.event"].sudo().search_count([
            ("action", "=", "appointment_rescheduled"),
            ("entity_res_id", "=", old.id)]), 1)
        with self.assertRaises(DallyOpsConflict):
            self.service().mark_present(old_ref, {"request_uuid": str(uuid.uuid4())})

    def test_prepare_reception_requires_present_returns_handle_without_a001(self):
        reference = self.create()["appointment"]["reference"]
        sequence = self.consolidation.intake_sequence_id.sudo()
        before_sequence = sequence.number_next_actual
        before_shipments = self.env["dally.shipment"].sudo().search_count([])
        for state in ("scheduled", "absent", "rescheduled"):
            event = self.event(reference)
            event.sudo().write({"dally_ops_status": state})
            with self.assertRaises(DallyOpsConflict) as error:
                self.service().prepare_reception(reference)
            self.assertEqual(error.exception.code, "appointment_not_present")
        self.event(reference).sudo().write({"dally_ops_status": "present"})
        result = self.service().prepare_reception(reference)
        self.assertEqual(result["customer_reference"], self.handle.token)
        self.assertEqual(result["customer_name"], self.customer.name)
        self.assertEqual(result["consolidation_reference"], self.consolidation.name)
        self.assertNotIn("partner_id", json.dumps(result))
        self.assertEqual(self.env["dally.shipment"].sudo().search_count([]), before_shipments)
        self.assertEqual(sequence.number_next_actual, before_sequence)

    def test_closed_consolidation_is_not_prefilled_but_customer_is(self):
        reference = self.create()["appointment"]["reference"]
        self.event(reference).sudo().write({"dally_ops_status": "present"})
        self.consolidation.sudo().write({"active": False})
        result = self.service().prepare_reception(reference)
        self.assertEqual(result["customer_reference"], self.handle.token)
        self.assertIsNone(result["consolidation_reference"])

    def test_controller_has_user_auth_and_no_sudo_or_api_key(self):
        source = executable_source(ops_appointments)
        self.assertNotIn(".sudo(", source)
        self.assertNotIn("API_KEY", source)
        self.assertIn('auth="user"', inspect.getsource(ops_appointments))


@tagged("post_install", "-at_install", "dally")
class TestOpsAppointmentsHttp(HttpCase):
    PASSWORD = "OpsAgenda!2026#http"

    def setUp(self):
        super().setUp()
        self.company = self.env["res.company"].create({"name": "Ops Agenda HTTP SA"})
        self.user = self._user(
            "agenda.http", "Gilles Agenda HTTP",
            "dally_ops_mobile.group_dally_ops_logistician")
        self.non_ops = self._user("agenda.http.other", "HTTP Other", "base.group_user")
        self.customer = self.env["res.partner"].create({
            "name": "Aissatou HTTP", "company_id": self.company.id,
            "phone": "+221771234567", "dally_whatsapp": "+221761234567"})
        self.handle = self.env["dally.ops.customer.handle"].sudo().create({
            "company_id": self.company.id, "partner_id": self.customer.id})
        self.consolidation = self.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-AGENDA-HTTP", "company_id": self.company.id,
            "state": "collecting", "transport_mode": "air", "direction": "export",
            "origin_country_id": self.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": self.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
        })

    def _user(self, login, name, group):
        return self.env["res.users"].create({
            "name": name, "login": login, "password": self.PASSWORD,
            "group_ids": [Command.set([self.env.ref(group).id])],
            "company_id": self.company.id,
            "company_ids": [Command.set([self.company.id])],
        })

    def _payload(self):
        return {
            "request_uuid": str(uuid.uuid4()),
            "customer_reference": self.handle.token, "kind": "dropoff",
            "start_at": "2026-08-31T10:00:00+00:00",
            "end_at": "2026-08-31T10:30:00+00:00",
            "consolidation_reference": self.consolidation.name,
            "location": "Dépôt Dakar", "note": "HTTP",
        }

    def _post(self, path, body, login="agenda.http"):
        self.authenticate(login, self.PASSWORD)
        return self.url_open(
            path, data=json.dumps(body),
            headers={"Content-Type": "application/json"}, allow_redirects=False)

    def test_real_http_create_list_detail_present_absent_reschedule_prepare(self):
        created_response = self._post("/api/v1/ops/appointments", self._payload())
        self.assertEqual(created_response.status_code, 200, created_response.content[:500])
        created = json.loads(created_response.content)["data"]
        reference = created["appointment"]["reference"]

        self.authenticate("agenda.http", self.PASSWORD)
        listed_response = self.url_open(
            "/api/v1/ops/appointments?from=2026-08-31T00%3A00%3A00%2B00%3A00"
            "&to=2026-09-01T00%3A00%3A00%2B00%3A00", allow_redirects=False)
        self.assertEqual(listed_response.status_code, 200)
        listed = json.loads(listed_response.content)["data"]["appointments"]
        self.assertIn(reference, [item["reference"] for item in listed])
        self.assertNotIn("phone", json.dumps(listed))

        detail_response = self.url_open(
            "/api/v1/ops/appointments/%s" % reference, allow_redirects=False)
        detail = json.loads(detail_response.content)["data"]
        self.assertEqual(detail["customer"]["phone"], self.customer.phone)

        present = self._post(
            "/api/v1/ops/appointments/%s/present" % reference,
            {"request_uuid": str(uuid.uuid4())})
        self.assertEqual(present.status_code, 200)
        prepared = self._post(
            "/api/v1/ops/appointments/%s/prepare-reception" % reference, {})
        self.assertEqual(prepared.status_code, 200)
        self.assertEqual(json.loads(prepared.content)["data"]["customer_reference"],
                         self.handle.token)

        absent_created = json.loads(self._post(
            "/api/v1/ops/appointments", self._payload()).content)["data"]
        absent_ref = absent_created["appointment"]["reference"]
        absent = self._post(
            "/api/v1/ops/appointments/%s/absent" % absent_ref,
            {"request_uuid": str(uuid.uuid4())})
        self.assertEqual(absent.status_code, 200)
        report = self._post(
            "/api/v1/ops/appointments/%s/reschedule" % absent_ref,
            {"request_uuid": str(uuid.uuid4()),
             "start_at": "2026-09-01T15:00:00+00:00",
             "end_at": "2026-09-01T15:30:00+00:00"})
        self.assertEqual(report.status_code, 200)
        self.assertNotEqual(
            json.loads(report.content)["data"]["appointment"]["reference"], absent_ref)

    def test_real_http_non_ops_is_forbidden(self):
        response = self._post(
            "/api/v1/ops/appointments", self._payload(), "agenda.http.other")
        self.assertEqual(response.status_code, 403)
