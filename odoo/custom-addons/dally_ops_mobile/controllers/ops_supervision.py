# -*- coding: utf-8 -*-
"""Les deux lectures de supervision : ce qui cloche, et ce que le tableur a reçu.

Deux routes, deux services, une même règle : lecture seule, réservée au
responsable, et rien qui ne soit rédigé pour un opérateur. Aucun `last_error`,
aucune trace, aucun identifiant Odoo ne franchit cette frontière.
"""

import logging

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from .ops_base import DallyOpsController

_logger = logging.getLogger(__name__)


class DallyOpsSupervisionController(DallyOpsController):

    @http.route(
        "/api/v1/ops/anomalies", type="http", auth="user", readonly=True,
        methods=["GET"], csrf=False, save_session=False,
    )
    def ops_anomalies(self, **kwargs):
        """Ce qui demande une décision humaine, aujourd'hui, dans cette société."""
        if not self._a_un_role_ops():
            return self._refus_ops("ops/anomalies")
        try:
            donnees = request.env["dally.ops.anomaly.service"].list_anomalies()
        except AccessError:
            # Le refus est le même que pour un compte sans rôle : dire « vous
            # avez un rôle, mais pas celui-là » renseignerait sur la structure
            # des droits de ceux qui, eux, y ont accès.
            return self._refus_ops("ops/anomalies")
        return self._json({"success": True, "data": donnees})

    @http.route(
        "/api/v1/ops/sheet-sync", type="http", auth="user", readonly=True,
        methods=["GET"], csrf=False, save_session=False,
    )
    def ops_sheet_sync(self, **kwargs):
        """L'état du transport Odoo → tableur, en compteurs.

        C'est l'autre moitié de l'écran de synchronisation, et elle n'a rien à
        voir avec la première : la file de l'appareil vit dans le navigateur,
        celle-ci vit dans Odoo. Les mélanger ferait croire qu'un envoi bloqué
        sur le téléphone et une projection en échec sont le même incident.
        """
        if not self._a_un_role_ops():
            return self._refus_ops("ops/sheet-sync")
        try:
            donnees = request.env["dally.ops.sheet.outbox"].supervision_summary()
        except AccessError:
            return self._refus_ops("ops/sheet-sync")
        return self._json({"success": True, "data": donnees})
