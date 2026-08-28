# -*- coding: utf-8 -*-
"""Read-only current CRM assignments for the Google Sheets connector."""

import re

from odoo import _, http
from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError
from odoo.http import request


SYNC_GROUP = "dally_freight_billing.group_dally_freight_sync_api"
MAX_SHIPMENT_IDS = 200


class DallySheetBindingsController(DallyApiController):

    @http.route(
        "/api/v1/freight/sheet-bindings",
        type="http",
        auth="none",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def sheet_bindings(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/freight/sheet-bindings",
            required_scope="freight:write",
            handler=self._sheet_bindings,
            allow_bodyless_get=True,
        )

    @staticmethod
    def _shipment_ids():
        raw = request.httprequest.args.get("shipment_ids")
        if raw is None:
            raise DallyApiError(422, "invalid_shipment_ids", _("shipment_ids is required."))
        parts = [part.strip() for part in raw.split(",")]
        if not parts or any(not re.fullmatch(r"[1-9][0-9]*", part) for part in parts):
            raise DallyApiError(422, "invalid_shipment_ids", _("shipment_ids must contain positive integers."))
        ids = list(dict.fromkeys(int(part) for part in parts))
        if len(ids) > MAX_SHIPMENT_IDS:
            raise DallyApiError(422, "too_many_shipment_ids", _("At most %s shipment IDs are allowed.", MAX_SHIPMENT_IDS))
        return ids

    def _sheet_bindings(self, env, payload, api_key):
        if not env.user.has_group(SYNC_GROUP):
            raise DallyApiError(403, "forbidden", _("Identité Freight Sync non autorisée."))
        ids = self._shipment_ids()
        Shipment = env["dally.shipment"].with_context(active_test=False)
        records = Shipment.search([
            ("company_id", "=", env.company.id),
            ("id", "in", ids),
        ])
        result = []
        for shipment in records:
            planned = shipment.planned_consolidation_id
            requires_replan = bool(
                planned
                and planned.state != "collecting"
                and not shipment.consolidation_line_ids.filtered(
                    lambda line: line.consolidation_id == planned
                )
            )
            result.append({
                "shipment_id": shipment.id,
                "sync_source_key": shipment.sync_source_key or False,
                "external_reference": shipment.external_reference or False,
                "collection_local_ref": shipment.collection_local_ref or False,
                "intake_consolidation_ref": shipment.intake_consolidation_id.name if shipment.intake_consolidation_id else False,
                "planned_consolidation_ref": planned.name if planned else False,
                "requires_replan": requires_replan,
                "state": shipment.state,
            })
        by_id = {row["shipment_id"]: row for row in result}
        return {"bindings": [by_id[shipment_id] for shipment_id in ids if shipment_id in by_id]}, 200
