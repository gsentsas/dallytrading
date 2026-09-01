# -*- coding: utf-8 -*-
"""Les deux routes des événements opérationnels.

Aucun `sudo` ici, aucune clé d'API : le privilège vit dans le service, derrière
le rôle Ops. Le dossier est désigné par sa référence publique, jamais par un
identifiant interne.

Il n'existe volontairement ni `PUT` ni `DELETE`. Un événement est un fait : on
n'en réécrit pas l'histoire depuis un téléphone. Une correction, le jour où le
besoin apparaîtra, sera une décision métier séparée.
"""

import json

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError

from .ops_base import DallyOpsController


class DallyOpsEventsController(DallyOpsController):

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/events",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_events_list(self, reference, **kwargs):
        """Les événements saisis du dossier, terrain et backoffice."""
        return self._servir_evenement(
            lambda service: service.list_events(reference),
            "ops/intakes/events",
        )

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/events",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_event_create(self, reference, **kwargs):
        """Consigne un fait sur le dossier. L'état, lui, ne bouge pas."""
        try:
            corps = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return self._erreur(
                "invalid_request", _("Corps de requête illisible."), 400)
        if not isinstance(corps, dict):
            return self._erreur(
                "invalid_request", _("Corps de requête illisible."), 400)
        return self._servir_evenement(
            lambda service: service.create_event(reference, corps),
            "ops/intakes/events",
        )

    def _servir_evenement(self, operation, route):
        if not self._a_un_role_ops():
            return self._refus_ops(route)
        try:
            data = operation(request.env["dally.ops.event.service"])
        except DallyOpsError as erreur:
            return self._erreur(erreur.code, str(erreur), erreur.status)
        except AccessError:
            return self._refus_ops(route)
        return self._json({"success": True, "data": data})

    @classmethod
    def _erreur(cls, code, message, status):
        return cls._json(
            {"success": False, "error": {"code": code, "message": message}},
            status=status,
        )
