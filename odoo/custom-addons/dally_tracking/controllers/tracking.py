# -*- coding: utf-8 -*-
"""GET /api/v1/tracking/<reference> — public shipment tracking.

Three properties this endpoint has to hold, in order of importance:

1. **It cannot leak.** It runs as an integration user in no DallyTrading group, so
   the ORM never loads supplier costs, margins or internal notes; a record rule
   limits it to customer-visible events; and the payload is built from an explicit
   allowlist. Three independent layers, deliberately — ``sudo()`` is *not* used,
   because sudo would defeat the first two.

2. **It does not confirm what it does not find.** An unknown reference and a
   malformed one both return 404, with the same body.

3. **It is cheap.** No request-log row is written for a read: logging every
   tracking lookup would bloat the table without adding anything, since there is
   no idempotency to preserve on a read.

### Known trade-off: references are enumerable

The specification (§44) asks for lookup by reference alone, and references are
sequential (DT-SHP-2026-000124). Anyone can therefore walk the series. That is
accepted deliberately, on two grounds:

* the payload contains nothing confidential — no customer identity, no value, no
  price. The worst case is learning that a shipment exists and where it is going;
* rate limiting at the Next.js backend and at the reverse proxy makes bulk walking
  impractical.

If DallyTrading later judges this insufficient, the hardening path is to require a
second factor alongside the reference — the customer's surname, or a token
embedded in notification links. That is a product decision, not a technical
obstacle; it is noted here rather than silently implemented, because it changes
what a customer has to type.
"""

import logging
import re

from odoo import _, http
from odoo.http import request

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError

_logger = logging.getLogger(__name__)

#: Accepted reference shape, after normalisation. Checked before querying: it
#: rejects junk without touching the database, and keeps the endpoint from being
#: used as a general-purpose search.
REFERENCE_RE = re.compile(r"^DT-SHP-\d{4}-\d{6}$")


class DallyTrackingController(DallyApiController):

    @http.route(
        "/api/v1/tracking/<string:reference>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def get_tracking(self, reference, **kwargs):
        try:
            api_key, env = self._authenticate("tracking:read")
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        Shipment = env["dally.shipment"]
        normalised = Shipment._dally_normalise_reference(reference)

        if not REFERENCE_RE.match(normalised):
            # Same response as "not found": telling a caller that the *format* was
            # wrong is harmless, but keeping one shape for both keeps the endpoint
            # from being probed for what it considers valid.
            _logger.info("Tracking lookup with malformed reference")
            return self._not_found()

        shipment = Shipment._dally_find_for_tracking(normalised)
        if not shipment:
            _logger.info("Tracking lookup miss for %s", normalised)
            return self._not_found()

        try:
            payload = shipment._dally_public_payload()
        except Exception:  # noqa: BLE001
            # Never let an internal failure surface as a stack trace on a public
            # endpoint.
            _logger.exception("Failed to build tracking payload for %s", normalised)
            return self._error(
                500, "internal_error",
                _("An internal error occurred."),
            )

        api_key._register_use()
        return self._success(payload)

    @classmethod
    def _not_found(cls):
        """One response for unknown, archived and malformed references."""
        return cls._error(
            404, "not_found",
            _("No shipment matches this reference."),
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

        Without this route, `/api/v1/tracking` would 404 as an unrouted path,
        which is fine — but being explicit documents that there is deliberately no
        endpoint that lists shipments (§40).
        """
        return self._error(
            400, "reference_required",
            _("A shipment reference is required: /api/v1/tracking/DT-SHP-YYYY-NNNNNN"),
        )
