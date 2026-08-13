# -*- coding: utf-8 -*-
"""GET /api/v1/services — the public service catalogue.

Odoo is the source of truth. The website holds no business list of its own: the
requirement flags returned here are what decide which steps and fields the quote
form shows.

Runs as the calling key's integration user, not ``sudo()``. The catalogue is public
information, so nothing here is sensitive — but keeping the same rule everywhere
means there is no endpoint where a reviewer has to stop and ask why this one is
different.
"""

import logging

from odoo import http

from .main import DallyApiController, DallyApiError

_logger = logging.getLogger(__name__)


class DallyServicesController(DallyApiController):

    @http.route(
        "/api/v1/services",
        type="http",
        auth="none",
        readonly=False,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def list_services(self, **kwargs):
        try:
            api_key, env = self._authenticate("services:read")
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        catalogue = env["dally.service.type"]._dally_public_catalogue()

        api_key._register_use()

        # The response is cacheable, unlike everything else in this API: it is the
        # same for every caller and changes rarely. A short max-age lets the BFF
        # and any intermediary avoid hammering Odoo, while a catalogue change still
        # propagates within minutes.
        return self._json_response(
            {"success": True, "data": {"services": catalogue}},
            status=200,
            cache_control="public, max-age=300",
        )
