# -*- coding: utf-8 -*-
"""GET /api/v1/tracking/<reference>?token=... — public shipment tracking.

## Why a token is required

The reference stays human-readable, because a customer quotes it on the phone and
reads it off an invoice. But readable means sequential
(``DT-SHP-2026-000123``), and sequential means walkable. Accepting a reference
alone would let anyone enumerate every shipment DallyTrading handles: not the
confidential details — those are filtered — but the existence, route and status of
each one, which is competitive information.

So the endpoint requires **reference + token**. The token is 256 bits of CSPRNG
output, compared in constant time, and travels in the links sent by e-mail and
WhatsApp. A wrong token and an unknown reference produce the same 404, so the
endpoint cannot even be used to confirm which references exist.

The Odoo database id is never used for this. It is sequential and it is not a
secret.

## Confidentiality: three independent layers, unchanged

1. **ORM field groups** — supplier costs, margins and internal notes are not
   loaded for the tracking user at all.
2. **A record rule** — that user only ever sees ``visible_to_customer`` events.
3. **An explicit payload allowlist** — every emitted key is named.

``sudo()`` is deliberately absent: it would bypass layers 1 and 2.
"""

import logging
import re

from odoo import _, http

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError

_logger = logging.getLogger(__name__)

#: Accepted reference shape after normalisation. Checked before querying: it
#: rejects junk without touching the database and keeps the endpoint from being
#: used as a general-purpose search.
REFERENCE_RE = re.compile(r"^DT-SHP-\d{4}-\d{6}$")

#: Plausible token length, to reject obvious junk before a database round trip.
#: token_urlsafe(32) yields 43 characters; the range allows for future changes.
MIN_TOKEN_LENGTH = 20
MAX_TOKEN_LENGTH = 128


class DallyTrackingController(DallyApiController):

    @http.route(
        "/api/v1/tracking/<string:reference>",
        type="http",
        auth="none",
        readonly=False,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def get_tracking(self, reference, token=None, **kwargs):
        try:
            api_key, env = self._authenticate("tracking:read")
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        Shipment = env["dally.shipment"]
        normalised = Shipment._dally_normalise_reference(reference)

        # Shape checks first: no database work for a caller who supplied neither a
        # plausible reference nor a plausible token.
        if not REFERENCE_RE.match(normalised):
            _logger.info("Tracking lookup with malformed reference")
            return self._not_found()

        if not token or not isinstance(token, str) or not (
            MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH
        ):
            _logger.info("Tracking lookup for %s without a usable token", normalised)
            return self._not_found()

        shipment = Shipment._dally_find_for_tracking(normalised, token)
        if not shipment:
            # Unknown reference, wrong token, or another company's shipment — all
            # answered identically, on purpose.
            _logger.info("Tracking lookup miss for %s", normalised)
            return self._not_found()

        try:
            payload = shipment._dally_public_payload()
        except Exception:  # noqa: BLE001
            _logger.exception("Failed to build tracking payload for %s", normalised)
            return self._error(
                500, "internal_error", _("An internal error occurred."),
            )

        api_key._register_use()
        return self._success(payload)

    @classmethod
    def _not_found(cls):
        """One response for unknown, wrong-token, malformed and foreign references."""
        return cls._error(
            404, "not_found",
            _("No shipment matches this reference and tracking code."),
        )

    @http.route(
        "/api/v1/tracking",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def tracking_without_reference(self, **kwargs):
        """Explicit refusal rather than a listing.

        Being explicit documents that there is deliberately no endpoint returning
        more than one shipment (§40).
        """
        return self._error(
            400, "reference_required",
            _("A reference and a tracking code are required: "
              "/api/v1/tracking/DT-SHP-YYYY-NNNNNN?token=..."),
        )
