# -*- coding: utf-8 -*-
"""Les trois routes du chargement d'un départ.

Deux lectures et une mutation. Il n'existe ni clôture de collecte, ni mise au
départ, ni enregistrement de départ : ces gestes engagent le dossier maître et
restent au back-office. Les absenter vaut mieux que les exposer puis les
refuser.

Aucun `sudo` ici, aucune clé d'API : le privilège vit dans le service,
derrière le rôle Ops. Le départ est désigné par sa référence métier, le colis
par une identité opaque — jamais par un identifiant de base.
"""

import json

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError

from .ops_base import DallyOpsController

ROUTE = "ops/loading/consolidations"


class DallyOpsLoadingController(DallyOpsController):

    @http.route(
        "/api/v1/ops/loading/consolidations",
        type="http", auth="user", readonly=True,
        methods=["GET"], csrf=False, save_session=False,
    )
    def ops_loading_list(self, **kwargs):
        """Les départs que le quai peut préparer ou constater."""
        return self._servir_chargement(
            lambda service: service.list_consolidations(), ROUTE)

    @http.route(
        "/api/v1/ops/loading/consolidations/<string:reference>",
        type="http", auth="user", readonly=True,
        methods=["GET"], csrf=False, save_session=False,
    )
    def ops_loading_detail(self, reference, **kwargs):
        """Ce qui est attendu sur ce départ, et ce qui est déjà chargé."""
        return self._servir_chargement(
            lambda service: service.get_loading(reference), ROUTE)

    @http.route(
        "/api/v1/ops/loading/consolidations/<string:reference>",
        type="http", auth="user",
        methods=["POST"], csrf=False, save_session=False,
    )
    def ops_loading_apply(self, reference, **kwargs):
        """Charge ou retire un colis. Rien d'autre ne bouge."""
        try:
            corps = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return self._erreur("invalid_request", _("Corps de requête illisible."), 400)
        if not isinstance(corps, dict):
            return self._erreur("invalid_request", _("Corps de requête illisible."), 400)
        return self._servir_chargement(
            lambda service: service.apply_loading(reference, corps), ROUTE)

    def _servir_chargement(self, operation, route):
        """Le nom porte le préfixe de la fonctionnalité, et ce n'est pas
        cosmétique : Odoo fusionne tous les contrôleurs qui partagent une base
        en une seule classe. Un `_servir` de plus, avec une autre signature,
        écraserait celui des dépenses — ce qui est arrivé une fois."""
        if not self._a_un_role_ops():
            return self._refus_ops(route)
        try:
            data = operation(request.env["dally.ops.loading.service"])
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
