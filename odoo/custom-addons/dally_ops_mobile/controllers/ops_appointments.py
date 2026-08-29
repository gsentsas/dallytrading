# -*- coding: utf-8 -*-
"""Routes Agenda Dally Ops. Le privilège reste entièrement dans le service."""

import json

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError

from .ops_base import DallyOpsController


class DallyOpsAppointmentsController(DallyOpsController):

    @http.route(
        "/api/v1/ops/appointments", type="http", auth="user",
        methods=["GET"], csrf=False, save_session=False, readonly=True)
    def list_appointments(self, **kwargs):
        if set(request.httprequest.args) - {"from", "to"}:
            return self._error("invalid_request", _("Paramètre inconnu."), 400)
        return self._serve(
            lambda service: service.list_appointments(
                request.httprequest.args.get("from"),
                request.httprequest.args.get("to")),
            "ops/appointments/list")

    @http.route(
        "/api/v1/ops/appointments", type="http", auth="user",
        methods=["POST"], csrf=False, save_session=False)
    def create_appointment(self, **kwargs):
        return self._serve_body(
            lambda service, body: service.create_appointment(body),
            "ops/appointments/create")

    @http.route(
        "/api/v1/ops/appointments/<string:reference>", type="http",
        auth="user", methods=["GET"], csrf=False, save_session=False,
        readonly=True)
    def get_appointment(self, reference, **kwargs):
        return self._serve(
            lambda service: service.get_appointment(reference),
            "ops/appointments/detail")

    @http.route(
        "/api/v1/ops/appointments/<string:reference>/present", type="http",
        auth="user", methods=["POST"], csrf=False, save_session=False)
    def present(self, reference, **kwargs):
        return self._serve_body(
            lambda service, body: service.mark_present(reference, body),
            "ops/appointments/present")

    @http.route(
        "/api/v1/ops/appointments/<string:reference>/absent", type="http",
        auth="user", methods=["POST"], csrf=False, save_session=False)
    def absent(self, reference, **kwargs):
        return self._serve_body(
            lambda service, body: service.mark_absent(reference, body),
            "ops/appointments/absent")

    @http.route(
        "/api/v1/ops/appointments/<string:reference>/reschedule", type="http",
        auth="user", methods=["POST"], csrf=False, save_session=False)
    def reschedule(self, reference, **kwargs):
        return self._serve_body(
            lambda service, body: service.reschedule(reference, body),
            "ops/appointments/reschedule")

    @http.route(
        "/api/v1/ops/appointments/<string:reference>/prepare-reception",
        type="http", auth="user", methods=["POST"], csrf=False,
        save_session=False)
    def prepare_reception(self, reference, **kwargs):
        body = self._body()
        if body is None or body != {}:
            return self._error(
                "invalid_request", _("Cette action n'accepte aucun champ."), 400)
        return self._serve(
            lambda service: service.prepare_reception(reference),
            "ops/appointments/prepare-reception")

    def _serve_body(self, operation, route):
        body = self._body()
        if body is None:
            return self._error(
                "invalid_request", _("Corps de requête illisible."), 400)
        return self._serve(lambda service: operation(service, body), route)

    @staticmethod
    def _body():
        try:
            return json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return None

    def _serve(self, operation, route):
        if not self._a_un_role_ops():
            return self._refus_ops(route)
        try:
            data = operation(request.env["dally.ops.appointment.service"])
        except DallyOpsError as error:
            return self._error(error.code, str(error), error.status)
        except AccessError:
            return self._refus_ops(route)
        return self._json({"success": True, "data": data})

    @classmethod
    def _error(cls, code, message, status):
        return cls._json({
            "success": False,
            "error": {"code": code, "message": message},
        }, status=status)
