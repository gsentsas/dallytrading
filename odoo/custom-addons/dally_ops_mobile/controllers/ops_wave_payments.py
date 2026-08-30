# -*- coding: utf-8 -*-
"""Les encaissements Wave d'un dossier.

Trois routes, aucun `sudo`, aucune clé d'API. Le dossier est désigné par sa
référence publique — son `Axxx` — et jamais par un identifiant interne.

Le corps n'accepte ni moyen de paiement ni bénéficiaire : ces deux valeurs
sont des règles serveur, et les laisser voyager ferait croire au navigateur
qu'il les décide.
"""

import json

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError

from .ops_base import DallyOpsController


class DallyOpsWavePaymentsController(DallyOpsController):

    @http.route(
        "/api/v1/ops/shipments/<string:reference>/wave-context",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_wave_context(self, reference, **kwargs):
        """Le dossier, son client, le bénéficiaire imposé et les devises."""
        return self._servir_wave(
            lambda: request.env[
                "dally.ops.wave.payment.service"].payment_context(reference),
            "ops/shipments/wave-context",
        )

    @http.route(
        "/api/v1/ops/shipments/<string:reference>/payments",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_wave_payments_list(self, reference, **kwargs):
        """Ce qui a déjà été encaissé sur ce dossier."""
        return self._servir_wave(
            lambda: request.env[
                "dally.ops.wave.payment.service"].list_payments(reference),
            "ops/shipments/payments",
        )

    @http.route(
        "/api/v1/ops/shipments/<string:reference>/payments",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_wave_payment_record(self, reference, **kwargs):
        """Enregistre un encaissement Wave sur ce dossier."""
        try:
            corps = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return self._erreur("invalid_request", _("Corps de requête illisible."), 400)
        return self._servir_wave(
            lambda: request.env[
                "dally.ops.wave.payment.service"].record_wave_payment(
                    reference, corps),
            "ops/shipments/payments",
        )

    def _servir_wave(self, operation, route):
        """Le squelette commun aux trois routes Wave.

        ## Pourquoi ce nom, et pas `_servir`

        Odoo fusionne les contrôleurs qui partagent une même classe de base :
        deux méthodes homonymes sur `DallyOpsController` n'en font qu'une, et
        c'est la dernière chargée qui l'emporte — pour **tous** les
        contrôleurs, pas seulement le sien.

        Mesuré : nommer cette méthode `_servir` avec une convention d'appel
        différente de celle des dépenses et des transferts a rendu leurs
        routes inutilisables, en HTTP 500, alors que leurs tests de service
        restaient verts. Les encaissements de l'étape 9 avaient déjà tiré la
        leçon en choisissant `_servir_paiement` ; celui-ci suit la même règle.
        """
        if not self._a_un_role_ops():
            return self._refus_ops(route)
        try:
            return self._json({"success": True, "data": operation()})
        except DallyOpsError as erreur:
            return self._erreur(erreur.code, str(erreur), erreur.status)
        except AccessError:
            return self._refus_ops(route)

    # `_erreur` porte volontairement la même signature que chez les
    # contrôleurs voisins : la fusion d'Odoo la rend interchangeable, et une
    # divergence de contrat y serait tout aussi dangereuse qu'elle l'a été
    # pour `_servir`.
    @classmethod
    def _erreur(cls, code, message, status):
        return cls._json(
            {"success": False, "error": {"code": code, "message": message}},
            status=status,
        )
