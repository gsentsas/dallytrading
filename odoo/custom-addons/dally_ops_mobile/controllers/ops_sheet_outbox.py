# -*- coding: utf-8 -*-
"""La surface que le connecteur Google Sheets interroge.

## Pourquoi c'est le classeur qui tire, et pas Odoo qui pousse

Toute l'autorisation Google vit dans le projet Apps Script lié au classeur :
ses portées sont déclarées dans `appsscript.json`, et les clés d'API Odoo dans
ses Script Properties. Odoo, lui, ne possède **aucun identifiant Google** — et
en fabriquer un pour cette étape reviendrait à créer un secret de production
là où il n'y en avait pas.

Surtout, savoir écrire dans ce classeur n'est pas une petite affaire : mise en
page canonique à 63 colonnes, colonnes techniques d'identité, intention de
replanification à ne pas écraser, neutralisation des formules, migrations
héritées. Cette connaissance vit dans `Code.gs` et `Cash.gs`. La reproduire
côté Odoo créerait une seconde convention — exactement ce qu'il ne faut pas.

Le transport est donc initié par Apps Script. Cela ne déplace pas l'autorité :
Odoo décide de ce qui est vrai, le connecteur se contente d'aller le chercher.

## Deux routes, et un privilège étroit

Lire la file, accuser réception. Le scope `freight:sheet` ne permet ni de créer
un dossier, ni d'émettre une facture, ni de toucher à la caisse.
"""

from odoo import _, http

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError

#: Le groupe technique déjà porté par les identités de synchronisation.
BILLING_GROUP = "dally_freight_billing.group_dally_freight_billing_api"

SHEET_SCOPE = "freight:sheet"

#: Les seules clés acceptées dans un accusé de projection.
CHAMPS_ACK = frozenset({"request_uuid", "results"})
CHAMPS_RESULTAT = frozenset({"outbox_id", "ok", "error", "permanent"})


class DallyOpsSheetOutboxController(DallyApiController):

    @http.route(
        "/api/v1/freight/sheet-outbox", type="http", auth="none", readonly=False,
        methods=["GET"], csrf=False, save_session=False,
    )
    def sheet_outbox_batch(self, **kwargs):
        """Le prochain lot de projections, réservé pour ce transport."""
        return self._handle(
            endpoint="/api/v1/freight/sheet-outbox",
            required_scope=SHEET_SCOPE,
            handler=self._batch,
            allow_bodyless_get=True,
        )

    @http.route(
        "/api/v1/freight/sheet-outbox/ack", type="http", auth="none", readonly=False,
        methods=["POST"], csrf=False, save_session=False,
    )
    def sheet_outbox_ack(self, **kwargs):
        """Le verdict du transport, ligne par ligne."""
        return self._handle(
            endpoint="/api/v1/freight/sheet-outbox/ack",
            required_scope=SHEET_SCOPE,
            handler=self._ack,
        )

    # ------------------------------------------------------------------

    def _check_group(self, env):
        if not env.user.has_group(BILLING_GROUP):
            raise DallyApiError(
                403, "forbidden",
                _("This API user is not allowed to read the sheet projection queue."),
            )

    def _batch(self, env, payload, api_key):
        self._check_group(env)
        limite = self._limite(env)
        Boite = env["dally.ops.sheet.outbox"]
        # Les transports morts en route rendent leur ligne avant qu'on serve le
        # lot : sans cela, une seule coupure d'Apps Script gèlerait la file.
        Boite.release_stale()
        projections = Boite.claim_batch(env.company, limite)
        return {
            "company": env.company.name,
            "count": len(projections),
            "projections": projections,
        }, 200

    @staticmethod
    def _limite(env):
        parametre = env["ir.config_parameter"].sudo().get_param(
            "dally_ops.sheet_outbox_batch", default="")
        try:
            return int(parametre)
        except (TypeError, ValueError):
            return 0

    def _ack(self, env, payload, api_key):
        self._check_group(env)
        inconnus = set(payload) - CHAMPS_ACK
        if inconnus:
            raise DallyApiError(
                422, "unknown_field",
                _("Unsupported field in acknowledgement: %s") % ", ".join(sorted(inconnus)),
            )
        resultats = payload.get("results")
        if not isinstance(resultats, list):
            raise DallyApiError(
                422, "invalid_results", _("`results` must be a list."))
        for resultat in resultats:
            if not isinstance(resultat, dict):
                raise DallyApiError(
                    422, "invalid_results", _("Each result must be an object."))
            inconnus = set(resultat) - CHAMPS_RESULTAT
            if inconnus:
                raise DallyApiError(
                    422, "unknown_field",
                    _("Unsupported field in result: %s") % ", ".join(sorted(inconnus)),
                )
        compte = env["dally.ops.sheet.outbox"].acknowledge(env.company, resultats)
        return compte, 200
