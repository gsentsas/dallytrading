# -*- coding: utf-8 -*-
"""Ce que toutes les routes ``/api/v1/ops/`` ont en commun.

Une seule forme de réponse, un seul refus. Les en-têtes de cache et le libellé
d'un accès refusé sont des décisions de sécurité : les recopier dans chaque
contrôleur, c'est accepter qu'un jour l'un d'eux diverge.
"""

import json
import logging

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DallyOpsController(http.Controller):
    """Base des contrôleurs Ops. Ne porte elle-même aucune route."""

    @staticmethod
    def _json(charge, status=200):
        """Réponse JSON, jamais mise en cache.

        ``private, no-store`` : l'identité, les droits et les départs d'un
        opérateur ne doivent pas séjourner dans un intermédiaire, qui les
        servirait au suivant.
        """
        return request.make_response(
            json.dumps(charge),
            headers=[
                ("Content-Type", "application/json; charset=utf-8"),
                ("Cache-Control", "private, no-store, max-age=0"),
                ("X-Content-Type-Options", "nosniff"),
                ("Referrer-Policy", "no-referrer"),
            ],
            status=status,
        )

    @classmethod
    def _refus_ops(cls, route):
        """Le refus opposé à un utilisateur authentifié sans rôle Ops.

        403 et non 401 : la personne est identifiée, c'est l'autorisation qui
        manque. Le message ne nomme ni groupe, ni modèle — un refus n'a pas à
        renseigner sur la structure des droits de ceux qui, eux, y ont accès.
        """
        _logger.info("%s refuse a l'utilisateur %s : aucun role Ops.", route, request.env.uid)
        return cls._json(
            {"success": False,
             "error": {"code": "forbidden",
                       "message": _("Accès réservé aux opérateurs terrain.")}},
            status=403,
        )

    @staticmethod
    def _a_un_role_ops():
        return bool(request.env["res.users"]._dally_ops_role())
