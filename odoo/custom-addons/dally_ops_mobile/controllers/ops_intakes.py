# -*- coding: utf-8 -*-
"""Routes de réception Dally Ops, sans privilège dans le contrôleur."""

import json

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError

from .ops_base import DallyOpsController


class DallyOpsIntakesController(DallyOpsController):

    @http.route(
        "/api/v1/ops/intakes",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_intakes_create(self, **kwargs):
        if not self._a_un_role_ops():
            return self._refus_ops("ops/intakes")
        try:
            corps = json.loads(
                request.httprequest.get_data() or b"{}",
            )
        except ValueError:
            return self._erreur(
                "invalid_request",
                _("Corps de requête illisible."),
                400,
            )
        try:
            resultat = request.env[
                "dally.ops.intake.service"
            ].create_intake(corps)
        except DallyOpsError as erreur:
            return self._erreur(
                erreur.code, str(erreur), erreur.status,
            )
        except AccessError:
            return self._refus_ops("ops/intakes")
        return self._json({
            "success": True,
            "data": resultat,
        })

    @http.route(
        "/api/v1/ops/tariff-families",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_tariff_families(self, **kwargs):
        if not self._a_un_role_ops():
            return self._refus_ops("ops/tariff-families")
        try:
            familles = request.env[
                "dally.ops.intake.service"
            ].list_tariff_families()
        except AccessError:
            return self._refus_ops("ops/tariff-families")
        return self._json({
            "success": True,
            "data": {"tariff_families": familles},
        })

    # ------------------------------------------------------------------
    # Le dossier et ses articles
    # ------------------------------------------------------------------

    @http.route(
        "/api/v1/ops/intakes/<string:reference>",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_intake_detail(self, reference, **kwargs):
        """Le dossier désigné par sa référence métier.

        Le navigateur ne transmet ni identifiant Odoo ni société : la référence
        suffit, et le service impose le reste du domaine.
        """
        return self._servir(
            lambda: request.env["dally.ops.intake.line.service"].get_intake(reference),
            "ops/intakes/detail",
        )

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/lines",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_intake_line_add(self, reference, **kwargs):
        """Ajoute un article au dossier. Le numéro du dossier ne bouge pas."""
        corps = self._corps()
        if corps is None:
            return self._erreur("invalid_request", _("Corps de requête illisible."), 400)
        return self._servir(
            lambda: request.env["dally.ops.intake.line.service"].add_line(reference, corps),
            "ops/intakes/lines",
        )

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/lines/<string:line_uuid>",
        type="http",
        auth="user",
        methods=["PUT"],
        csrf=False,
        save_session=False,
    )
    def ops_intake_line_update(self, reference, line_uuid, **kwargs):
        """Corrige un article.

        `PUT` et non `PATCH` : le corps décrit l'article entier, pas un delta.
        La référence de l'article vient du chemin ; le corps ne peut pas la
        contredire.
        """
        corps = self._corps()
        if corps is None:
            return self._erreur("invalid_request", _("Corps de requête illisible."), 400)
        return self._servir(
            lambda: request.env["dally.ops.intake.line.service"].update_line(
                reference, line_uuid, corps),
            "ops/intakes/lines/update",
        )

    # ------------------------------------------------------------------
    # Plomberie commune
    # ------------------------------------------------------------------

    @staticmethod
    def _corps():
        try:
            return json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return None

    def _servir(self, operation, route):
        """Authentifie, exécute, traduit les refus. Aucun `sudo` ici."""
        if not self._a_un_role_ops():
            return self._refus_ops(route)
        try:
            return self._json({"success": True, "data": operation()})
        except DallyOpsError as erreur:
            return self._erreur(erreur.code, str(erreur), erreur.status)
        except AccessError:
            return self._refus_ops(route)

    @classmethod
    def _erreur(cls, code, message, status):
        return cls._json(
            {
                "success": False,
                "error": {"code": code, "message": message},
            },
            status=status,
        )
