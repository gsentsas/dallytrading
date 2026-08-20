# -*- coding: utf-8 -*-
"""Lecture publique des méthodes de remise configurées.

La route ne rend que des projections explicites et passe par le scope
``shop:read``. Les identifiants techniques, coûts internes et champs de société ne
franchissent jamais la frontière.
"""

from odoo import http

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError


class DallyShopDeliveryController(DallyApiController):

    @http.route(
        "/api/v1/shop/delivery-methods",
        type="http",
        auth="none",
        readonly=False,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def delivery_methods(self, **kwargs):
        try:
            api_key, env = self._authenticate("shop:read")
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        methods = env["dally.shop.delivery.method"]._dally_shop_public_methods()
        api_key._register_use()

        return self._json_response(
            {"success": True, "data": {"methods": methods}},
            status=200,
            cache_control="public, max-age=120",
        )
