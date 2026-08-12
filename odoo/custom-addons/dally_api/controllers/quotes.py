# -*- coding: utf-8 -*-
"""POST /api/v1/quotes — public quote requests.

Creates a ``dally.quote.request`` and its CRM opportunity. It deliberately does
**not** create a ``sale.order``, a ``res.partner`` or a ``dally.shipment``:

* a quotation carries a number that looks like a commitment, and raising one for
  every form submission — including spam — fills the sales pipeline with drafts
  nobody priced;
* a contact created per submission fills the address book with prospects who never
  answer;
* a shipment is an operational object; creating one for a prospect who will never
  buy pollutes the freight module and the operations queue.

Each of those is a human decision taken during qualification.
"""

import logging

from odoo import _, http

from .main import DallyApiController, DallyApiError

_logger = logging.getLogger(__name__)

#: Fields read from the payload. An allowlist, so a caller cannot set arbitrary
#: model fields such as user_id, state or internal_notes (§40).
QUOTE_INPUT_FIELDS = (
    "request_uuid",
    "service_code",
    "first_name",
    "last_name",
    "company_name",
    "email",
    "phone",
    "whatsapp",
    "city",
    "country_code",
    "origin_country_code",
    "origin_city",
    "destination_country_code",
    "destination_city",
    "goods_description",
    "quantity",
    "weight_kg",
    "volume_cbm",
    "packages_count",
    "vehicle_make",
    "vehicle_model",
    "vehicle_year",
    "budget",
    "message",
    "source_url",
    "referrer_url",
    "utm_source",
    "utm_medium",
    "utm_campaign",
)

#: Per-field caps. The website validates too, but the API cannot trust it: this
#: endpoint is reachable with curl.
MAX_LENGTHS = {
    "first_name": 100, "last_name": 100, "company_name": 200,
    "email": 254, "phone": 40, "whatsapp": 40, "city": 100,
    "country_code": 2, "origin_country_code": 2, "destination_country_code": 2,
    "origin_city": 100, "destination_city": 100,
    "service_code": 50, "goods_description": 5000, "quantity": 100,
    "vehicle_make": 100, "vehicle_model": 100, "vehicle_year": 10,
    "budget": 100, "message": 20000,
    "source_url": 500, "referrer_url": 500,
    "utm_source": 100, "utm_medium": 100, "utm_campaign": 100,
}

#: Numeric fields, with the largest value that is not obviously nonsense. A
#: 10-million-kilo shipment is a typo or a probe, not a request.
NUMERIC_LIMITS = {
    "weight_kg": 10_000_000.0,
    "volume_cbm": 100_000.0,
    "packages_count": 100_000.0,
}


class DallyQuotesController(DallyApiController):

    @http.route(
        "/api/v1/quotes",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def create_quote(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/quotes",
            required_scope="quotes:write",
            handler=self._create_quote,
        )

    def _create_quote(self, env, payload, api_key):
        clean = self._clean_payload(payload)

        self._require(clean, "service_code", "last_name")
        self._require_email_or_phone(clean)
        self._validate_email(clean.get("email"))

        service = env["dally.service.type"]._get_by_code(clean["service_code"])
        if not service:
            raise DallyApiError(
                422, "unknown_service",
                _("Unknown service '%s'.", clean["service_code"]),
            )
        if not service.active or not service.published:
            # An archived or unpublished service must not be requestable: nobody
            # would be able to price the result.
            raise DallyApiError(
                422, "service_unavailable",
                _("The service '%s' is not currently offered.", clean["service_code"]),
            )

        self._validate_service_requirements(service, clean)

        request = env["dally.quote.request"].dally_create_from_website(clean)

        # Only what the website needs back. No database id, and no indication of
        # whether an existing contact was matched — that is internal commercial
        # information (§42, §44).
        data = {
            "reference": request.reference,
            "service": request.service_type_id.code,
            "status": "received",
            "_record": request,
        }
        return data, 201

    # ─── Validation ──────────────────────────────────────────────────

    @staticmethod
    def _clean_payload(payload):
        """Keep allowlisted fields, trim strings, enforce caps."""
        clean = {}
        for name in QUOTE_INPUT_FIELDS:
            value = payload.get(name)
            if value is None:
                continue

            if name in NUMERIC_LIMITS:
                if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                    raise DallyApiError(
                        422, "invalid_field_type",
                        _("Field '%s' must be a number.", name),
                    )
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    raise DallyApiError(
                        422, "invalid_field_type",
                        _("Field '%s' must be a number.", name),
                    )
                if number < 0:
                    raise DallyApiError(
                        422, "invalid_field_value",
                        _("Field '%s' cannot be negative.", name),
                    )
                if number > NUMERIC_LIMITS[name]:
                    raise DallyApiError(
                        422, "field_too_large",
                        _("Field '%s' exceeds the accepted maximum.", name),
                    )
                clean[name] = number
                continue

            if not isinstance(value, (str, int, float)):
                raise DallyApiError(
                    422, "invalid_field_type",
                    _("Field '%s' must be a string.", name),
                )
            text = str(value).strip()
            limit = MAX_LENGTHS.get(name)
            if limit and len(text) > limit:
                raise DallyApiError(
                    422, "field_too_long",
                    _("Field '%(field)s' exceeds %(limit)s characters.",
                      field=name, limit=limit),
                )
            clean[name] = text

        for key in ("country_code", "origin_country_code", "destination_country_code"):
            if clean.get(key):
                clean[key] = clean[key].upper()

        return clean

    @staticmethod
    def _validate_service_requirements(service, clean):
        """Enforce, server-side, what the chosen service says it needs.

        The form already adapts its steps, but the form is not the authority: this
        endpoint is reachable directly. Without this check, a caller could submit a
        sea freight request with no origin and no destination, and an operator
        would receive something impossible to quote.

        Only origin and destination are enforced. Weight, volume and budget are
        genuinely often unknown at enquiry time — refusing a request because a
        customer does not yet know their tonnage would turn away real business.
        """
        missing = []
        if service.requires_origin and not (
            clean.get("origin_city") or clean.get("origin_country_code")
        ):
            missing.append("origin")
        if service.requires_destination and not (
            clean.get("destination_city") or clean.get("destination_country_code")
        ):
            missing.append("destination")

        if missing:
            raise DallyApiError(
                422, "missing_route",
                _(
                    "The service '%(service)s' requires: %(fields)s.",
                    service=service.code,
                    fields=", ".join(missing),
                ),
            )

    @staticmethod
    def _validate_email(email):
        """Structural check only.

        Full RFC validation rejects addresses that work in practice. Deliverability
        is proven by the confirmation e-mail arriving, not by a regex.
        """
        if not email:
            return
        if email.count("@") != 1:
            raise DallyApiError(422, "invalid_email",
                                _("The email address is not valid."))
        local, _sep, domain = email.partition("@")
        if not local or not domain or "." not in domain or domain.startswith(".") \
                or domain.endswith(".") or " " in email:
            raise DallyApiError(422, "invalid_email",
                                _("The email address is not valid."))
