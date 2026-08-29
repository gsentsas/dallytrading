# -*- coding: utf-8 -*-
"""Les remises de caisse entre acteurs.

Quatre routes, aucun `sudo`, aucune clé d'API. Le privilège vit dans le
service ; le contrôleur lit la requête, appelle, met en forme.

La route d'accusé de réception n'accepte qu'un identifiant de demande. Elle ne
prend ni montant, ni acteur, ni date : confirmer une réception ne corrige pas
une remise, et un corps plus riche laisserait croire le contraire.
"""

import json

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError

from .ops_base import DallyOpsController


class DallyOpsTransfersController(DallyOpsController):

    @http.route(
        "/api/v1/ops/cash-transfer-options",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_cash_transfer_options(self, **kwargs):
        """L'expéditeur, les destinataires, les devises et les modes."""
        return self._servir(
            lambda: request.env["dally.ops.cash.transfer.service"].list_options(),
            "ops/cash-transfer-options",
        )

    @http.route(
        "/api/v1/ops/cash-transfers",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_cash_transfers_list(self, **kwargs):
        """Les remises qui concernent l'opérateur — reçues comme envoyées."""
        return self._servir(
            lambda: request.env["dally.ops.cash.transfer.service"].list_transfers(),
            "ops/cash-transfers",
        )

    @http.route(
        "/api/v1/ops/cash-transfers",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_cash_transfer_record(self, **kwargs):
        """Enregistre une remise, en attente de son destinataire."""
        try:
            corps = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return self._erreur("invalid_request", _("Corps de requête illisible."), 400)
        return self._servir(
            lambda: request.env["dally.ops.cash.transfer.service"].record_transfer(corps),
            "ops/cash-transfers",
        )

    @http.route(
        "/api/v1/ops/cash-transfers/<string:reference>/acknowledge",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_cash_transfer_acknowledge(self, reference, **kwargs):
        """Le destinataire confirme avoir reçu les fonds."""
        try:
            corps = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return self._erreur("invalid_request", _("Corps de requête illisible."), 400)
        if not isinstance(corps, dict) or set(corps) != {"request_uuid"}:
            return self._erreur(
                "invalid_request", _("Demande de confirmation invalide."), 400)
        return self._servir(
            lambda: request.env["dally.ops.cash.transfer.service"].acknowledge(
                reference, corps.get("request_uuid")),
            "ops/cash-transfers/acknowledge",
        )

    def _servir(self, operation, route):
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
            {"success": False, "error": {"code": code, "message": message}},
            status=status,
        )
