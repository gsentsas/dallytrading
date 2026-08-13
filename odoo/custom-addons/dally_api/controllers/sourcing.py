# -*- coding: utf-8 -*-
"""POST /api/v1/sourcing/requests — public sourcing requests.

Creates a ``dally.sourcing.request`` and nothing else. No partner, no CRM
opportunity, no supplier, no purchase order, no shipment: each of those is a human
decision taken during qualification. Creating a CRM opportunity for every raw request
received from the internet would fill the pipeline with entries nobody triaged.

## Scope

Reuses the existing ``sourcing:write`` scope rather than inventing
``sourcing:create``. The project's convention is ``<area>:write`` — ``leads:write``,
``quotes:write`` — and a second spelling for the same area would be the kind of
inconsistency that leads to a key being granted the wrong one.

## No read endpoint yet

``GET /api/v1/sourcing/requests/<reference>`` is deliberately **not** implemented.
There is no client portal yet, so nothing consumes it, and a public read surface with
no consumer is attack surface for nothing. The model already exposes
``_dally_public_payload`` for when the portal arrives.

## What can never leave

Supplier offers, candidate suppliers, landed costs, scores, margins and internal notes
are on separate models the API user has no access to at all. That is enforced by ACLs,
not by this controller remembering to omit them.
"""

import logging

from odoo import _, http

from .main import DallyApiController, DallyApiError

_logger = logging.getLogger(__name__)

#: Top-level keys read from the payload. Nested objects are handled separately.
#: An allowlist, so a caller cannot set arbitrary model fields such as state,
#: responsible_id or internal_notes (§40).
FLAT_FIELDS = (
    "request_uuid",
    "service_code",
    "quantity",
    "uom",
    "budget",
    "target_unit_price",
    "currency",
    "preferred_origin_country",
    "destination_country",
    "requested_deadline",
    "required_delivery_date",
    "notes",
    "source_url",
    "referrer_url",
)

#: Nested objects and how they flatten. Declared as data so the mapping is readable
#: in one place rather than buried in branching code.
NESTED_FIELDS = {
    "customer": {
        "name": "customer_name",
        "first_name": "first_name",
        "last_name": "last_name",
        "company": "company_name",
        "email": "email",
        "phone": "phone",
        "whatsapp": "whatsapp",
    },
    "product": {
        "name": "product_name",
        "description": "product_description",
        "specifications": "specifications",
        "reference": "product_reference",
        "url": "product_url",
    },
}

MAX_LENGTHS = {
    "service_code": 50,
    "customer_name": 200, "first_name": 100, "last_name": 100,
    "company_name": 200, "email": 254, "phone": 40, "whatsapp": 40,
    "product_name": 200, "product_description": 10000, "specifications": 10000,
    "product_reference": 100, "product_url": 500,
    "uom": 50, "currency": 3,
    "preferred_origin_country": 2, "destination_country": 2,
    "notes": 10000, "source_url": 500, "referrer_url": 500,
    "requested_deadline": 10, "required_delivery_date": 10,
}

#: Numeric limits. A ten-million-unit order or a billion-euro budget from a public
#: form is a typo or a probe, not a request.
NUMERIC_LIMITS = {
    "quantity": 1_000_000_000.0,
    "budget": 1_000_000_000.0,
    "target_unit_price": 100_000_000.0,
}


class DallySourcingController(DallyApiController):

    @http.route(
        "/api/v1/sourcing/requests",
        type="http",
        auth="none",
        readonly=False,
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def create_sourcing_request(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/sourcing/requests",
            required_scope="sourcing:write",
            handler=self._create_sourcing_request,
        )

    def _create_sourcing_request(self, env, payload, api_key):
        clean = self._flatten_sourcing(payload)

        self._require(clean, "product_name")
        self._require_contact(clean)
        self._validate_email_sourcing(clean.get("email"))
        self._validate_dates(clean)

        service = self._resolve_service(env, clean)
        clean["service_code"] = service.code

        self._validate_currency(env, clean)
        self._validate_countries_sourcing(env, clean)

        request = env["dally.sourcing.request"].dally_create_from_website(clean)

        # Only what the site needs back. No database id, no indication of whether an
        # existing contact was matched — that is internal commercial information
        # (§42, §44).
        data = {
            "reference": request.reference,
            "service": request.service_id.code or None,
            "status": "received",
            "_record": request,
        }
        return data, 201

    # ─── Payload handling ────────────────────────────────────────────

    @classmethod
    def _flatten_sourcing(cls, payload):
        """Flatten the nested contract, keeping only allowlisted keys."""
        flat = {}

        for name in FLAT_FIELDS:
            if name in payload:
                flat[name] = payload[name]

        for group, mapping in NESTED_FIELDS.items():
            nested = payload.get(group)
            if nested is None:
                continue
            if not isinstance(nested, dict):
                raise DallyApiError(
                    422, "invalid_field_type",
                    _("Field '%s' must be an object.", group),
                )
            for source, target in mapping.items():
                if source in nested:
                    flat[target] = nested[source]

        # UTM travels as a nested object straight through to the model, which
        # resolves the strings to utm records.
        utm = payload.get("utm")
        if utm is not None:
            if not isinstance(utm, dict):
                raise DallyApiError(
                    422, "invalid_field_type", _("Field 'utm' must be an object."),
                )
            flat["utm"] = {
                key: value for key, value in utm.items()
                if key in ("source", "medium", "campaign")
                and isinstance(value, str)
            }

        return cls._coerce_sourcing(flat)

    @staticmethod
    def _coerce_sourcing(flat):
        """Trim strings, enforce caps, and validate numbers."""
        clean = {}
        for name, value in flat.items():
            if name == "utm":
                clean[name] = value
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
                        422, ("invalid_quantity" if name == "quantity"
                              else "invalid_field_value"),
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

        # Quantity must be strictly positive: a request for zero units is not a
        # request, and the database constraint would reject it as a 500 rather than a
        # usable message.
        if "quantity" in clean and clean["quantity"] <= 0:
            raise DallyApiError(
                422, "invalid_quantity",
                _("The quantity must be greater than zero."),
            )

        for key in ("currency",):
            if clean.get(key):
                clean[key] = clean[key].upper()
        for key in ("preferred_origin_country", "destination_country"):
            if clean.get(key):
                clean[key] = clean[key].upper()

        return clean

    # ─── Validation ──────────────────────────────────────────────────

    @staticmethod
    def _require_contact(clean):
        """A request nobody can answer is not a lead."""
        if not (clean.get("email") or "").strip() and not (clean.get("phone") or "").strip():
            raise DallyApiError(
                422, "no_contact_channel",
                _("Provide at least an email address or a phone number."),
            )
        has_name = any(
            (clean.get(key) or "").strip()
            for key in ("customer_name", "last_name", "company_name")
        )
        if not has_name:
            raise DallyApiError(
                422, "missing_fields",
                _("Provide a name or a company name."),
            )

    @staticmethod
    def _resolve_service(env, clean):
        """Resolve the service, defaulting to the sourcing activity.

        Defaulting rather than requiring: this endpoint *is* the sourcing endpoint, so
        a caller omitting the code means sourcing. An explicit code that does not
        exist is still rejected.
        """
        ServiceType = env["dally.service.type"]
        code = (clean.get("service_code") or "").strip() or "sourcing"

        service = ServiceType._get_by_code(code)
        if not service:
            raise DallyApiError(
                422, "unknown_service", _("Unknown service '%s'.", code),
            )
        if not service.active or not service.published:
            raise DallyApiError(
                422, "service_unavailable",
                _("The service '%s' is not currently offered.", code),
            )
        return service

    @staticmethod
    def _validate_currency(env, clean):
        code = (clean.get("currency") or "").strip()
        if not code:
            return
        currency = env["res.currency"].with_context(active_test=False).search(
            [("name", "=", code)], limit=1,
        )
        if not currency:
            raise DallyApiError(
                422, "unknown_currency",
                _("Unknown currency '%s'.", code),
            )

    @staticmethod
    def _validate_countries_sourcing(env, clean):
        Country = env["res.country"]
        for key in ("preferred_origin_country", "destination_country"):
            code = (clean.get(key) or "").strip()
            if not code:
                continue
            if not Country.search([("code", "=", code)], limit=1):
                raise DallyApiError(
                    422, "unknown_country",
                    _("Unknown country code '%(code)s' for '%(field)s'.",
                      code=code, field=key),
                )

    @staticmethod
    def _validate_dates(clean):
        """Accept ISO dates only, and require them to be coherent.

        Parsed here rather than left to the ORM: an unparseable date reaching
        ``create`` surfaces as a 500, where a caller can act on a 422.
        """
        from datetime import date

        parsed = {}
        for key in ("requested_deadline", "required_delivery_date"):
            raw = (clean.get(key) or "").strip()
            if not raw:
                continue
            try:
                parsed[key] = date.fromisoformat(raw)
            except ValueError:
                raise DallyApiError(
                    422, "invalid_date",
                    _("Field '%s' must be a date in YYYY-MM-DD format.", key),
                )

        deadline = parsed.get("requested_deadline")
        delivery = parsed.get("required_delivery_date")
        if deadline and delivery and delivery < deadline:
            raise DallyApiError(
                422, "invalid_date_range",
                _(
                    "The required delivery date cannot precede the date you asked "
                    "for an answer."
                ),
            )

    @staticmethod
    def _validate_email_sourcing(email):
        """Structural check only.

        Full RFC validation rejects addresses that work in practice. Deliverability is
        proven by the confirmation e-mail arriving, not by a regex.
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
