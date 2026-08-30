# -*- coding: utf-8 -*-
"""Routes en lecture seule du journal opérationnel Dally Ops."""

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError

from .ops_base import DallyOpsController


PARAMETRES = frozenset({"date", "cursor", "limit", "type", "scope"})
PARAMETRES_DOSSIER = frozenset({"cursor", "limit", "type"})


class DallyOpsActivityController(DallyOpsController):

    @http.route(
        "/api/v1/ops/activity", type="http", auth="user", readonly=True,
        methods=["GET"], csrf=False, save_session=False)
    def activity(self, **kwargs):
        args = request.httprequest.args
        if set(args) - PARAMETRES:
            return self._erreur("invalid_request", _("Paramètre inconnu."), 400)
        return self._servir_activite(lambda service: service.list_activity(
            date=args.get("date"), cursor=args.get("cursor"),
            limit=args.get("limit"), event_type=args.get("type"),
            scope=args.get("scope") or "mine"), "ops/activity")

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/activity", type="http",
        auth="user", readonly=True, methods=["GET"], csrf=False,
        save_session=False)
    def intake_activity(self, reference, **kwargs):
        args = request.httprequest.args
        if set(args) - PARAMETRES_DOSSIER:
            return self._erreur("invalid_request", _("Paramètre inconnu."), 400)
        return self._servir_activite(lambda service: service.intake_activity(
            reference, cursor=args.get("cursor"), limit=args.get("limit"),
            event_type=args.get("type")), "ops/intakes/activity")

    def _servir_activite(self, operation, route):
        if not self._a_un_role_ops():
            return self._refus_ops(route)
        try:
            data = operation(request.env["dally.ops.activity.service"])
        except DallyOpsError as error:
            return self._erreur(error.code, str(error), error.status)
        except AccessError:
            return self._refus_ops(route)
        return self._json({"success": True, "data": data})

    @classmethod
    def _erreur(cls, code, message, status):
        return cls._json(
            {"success": False, "error": {"code": code, "message": message}},
            status=status,
        )
