# -*- coding: utf-8 -*-
"""Read-only consolidation endpoint for Freight Sync."""
from odoo import http, _
from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError

class DallyOpenConsolidationsController(DallyApiController):
    @http.route("/api/v1/freight/consolidations/open", type="http", auth="none", readonly=True, methods=["GET"], csrf=False, save_session=False)
    def open_consolidations(self, **kwargs):
        return self._handle(endpoint="/api/v1/freight/consolidations/open", required_scope="freight:write", handler=self._open_consolidations, allow_bodyless_get=True)

    def _open_consolidations(self, env, payload, api_key):
        if not env.user.has_group("dally_freight_billing.group_dally_freight_sync_api"):
            raise DallyApiError(403, "forbidden", _("Identité Freight Sync non autorisée."))
        records = env["dally.freight.consolidation"].search([
            ("company_id", "=", env.company.id), ("state", "=", "collecting")
        ], order="collection_close_on, name")
        return {"consolidations": [{
            "id": c.id, "name": c.name, "transport_mode": c.transport_mode,
            "direction": c.direction, "origin": c.origin_location or c.origin_city,
            "destination": c.destination_location or c.destination_city,
            "origin_country_code": c.origin_country_id.code or "",
            "origin_city": c.origin_city or "", "origin_location": c.origin_location or "",
            "destination_country_code": c.destination_country_id.code or "",
            "destination_city": c.destination_city or "", "destination_location": c.destination_location or "",
            "state": c.state, "collection_close_on": str(c.collection_close_on or ""),
        } for c in records]}, 200
