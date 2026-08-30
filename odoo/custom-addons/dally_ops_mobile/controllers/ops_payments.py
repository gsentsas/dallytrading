# -*- coding: utf-8 -*-
"""Les encaissements du terrain.

Deux routes, aucun `sudo`, aucune clé d'API. La route Freight équivalente sert
le connecteur tableur et n'est pas appelée d'ici : elle s'authentifie par clé
et rend des identifiants Odoo.
"""

import json

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError

from .ops_base import DallyOpsController


class DallyOpsPaymentsController(DallyOpsController):

    @http.route(
        "/api/v1/ops/payment-channels",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_payment_channels(self, **kwargs):
        """Les canaux configurés — un code, un nom, une devise."""
        return self._servir_paiement(
            lambda: {"channels": request.env[
                "dally.ops.payment.service"].list_payment_channels()},
            "ops/payment-channels",
        )

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/payments",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_payment_record(self, reference, **kwargs):
        """Enregistre un encaissement sur un dossier.

        Un échec de comptabilisation n'est pas un échec d'encaissement :
        l'argent reçu est conservé et la réponse reste un succès, le verdict
        comptable se lisant dans `accounting_status`.
        """
        try:
            corps = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return self._erreur("invalid_request", _("Corps de requête illisible."), 400)
        return self._servir_paiement(
            lambda: request.env["dally.ops.payment.service"].record_payment(
                reference, corps),
            "ops/payments",
        )

    def _servir_paiement(self, operation, route):
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
