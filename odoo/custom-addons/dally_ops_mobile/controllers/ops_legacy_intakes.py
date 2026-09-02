# -*- coding: utf-8 -*-
"""L'unique route d'un dossier repris : la lire.

Une seule méthode, `GET`. Il n'existe ni `POST`, ni `PUT`, ni `PATCH`, ni
`DELETE` — non pas désactivés, mais absents. Un verbe déclaré puis refusé
laisserait penser qu'il suffirait de lever le refus ; ici il n'y a rien à
lever.

Aucun `sudo` et aucune clé d'API : le privilège vit dans le service, derrière
le rôle Ops. Le dossier est désigné par sa référence globale, jamais par un
identifiant interne.
"""

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError

from .ops_base import DallyOpsController


class DallyOpsLegacyIntakesController(DallyOpsController):

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/legacy-detail",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_legacy_intake_detail(self, reference, **kwargs):
        """La fiche en lecture seule d'un dossier que Dally Ops n'a pas créé."""
        route = "ops/intakes/legacy-detail"
        if not self._a_un_role_ops():
            return self._refus_ops(route)
        try:
            data = request.env[
                "dally.ops.legacy.intake.service"].get_legacy_intake(reference)
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
