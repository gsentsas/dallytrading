# -*- coding: utf-8 -*-
"""Public intake for trade opportunities.

## What this endpoint accepts, and what it refuses

It accepts an enquiry: who is asking, what kind of operation, what they need, where
it comes from and where it goes. It refuses — with a 422 naming the field — anything
internal: a cost, a margin, a supplier score, a commission, a negotiation note, an
approval status.

The refusal is deliberate rather than a silent drop. A caller sending
``internal_margin`` is either mistaken about the contract or probing it; answering 201
would tell them nothing in the first case and reward them in the second.

## Why an allowlist and not a denylist

``FLAT_FIELDS`` is the whole contract. A field added to ``dally.trade.opportunity``
tomorrow is not writable from here unless someone adds it to this tuple, which means
the safe direction is the default one. ``FORBIDDEN_FIELDS`` exists on top of it purely
so a probe gets a clear 422 instead of a generic "unknown field" — the allowlist is
what actually protects the model.

## Least privilege

The endpoint runs as ``user_dally_api_trade``, which is in no commercial group at all.
It cannot read a cost, a margin or an internal note, because the ORM will not load
fields whose ``groups=`` it does not hold — and a record rule limits it to the records
it created itself. ``sudo()`` appears nowhere in this path: it would bypass both.
"""

import logging

from odoo import _, http

from .main import DallyApiController, DallyApiError

_logger = logging.getLogger(__name__)

#: Top-level keys read from the payload. The whole public contract.
FLAT_FIELDS = (
    "request_uuid",
    "operation_type",
    "subject",
    "description",
    "requirements",
    "service_code",
    "origin_country",
    "destination_country",
    "source_url",
    "referrer_url",
)

#: Nested objects, and how they flatten. Declared as data so the mapping is readable
#: in one place rather than buried in branching code.
NESTED_FIELDS = {
    "contact": {
        "name": "contact_name",
        "company": "company",
        "email": "email",
        "phone": "phone",
        "whatsapp": "whatsapp",
        "country": "contact_country",
    },
}

#: Field names that must be refused outright, with the field named back.
#:
#: Redundant with the allowlist by construction. It exists so that a caller who sends
#: `internal_margin` learns the contract refuses it, rather than watching it vanish.
FORBIDDEN_FIELDS = (
    "internal_cost",
    "purchase_margin",
    "internal_margin",
    "supplier_score",
    "internal_commission",
    "negotiation_notes",
    "approval_status",
    "approval_reason",
    "purchase_unit_price",
    "purchase_subtotal",
    "purchase_currency",
    "gross_margin",
    "net_margin",
    "margin_rate",
    "cost_total",
    "commission_total",
    "supplier",
    "supplier_id",
    "internal_notes",
    "state",
    "responsible_id",
    "company_id",
)

MAX_LENGTHS = {
    "request_uuid": 64,
    "operation_type": 40,
    "subject": 200,
    "description": 10000,
    "requirements": 10000,
    "service_code": 50,
    "contact_name": 200,
    "company": 200,
    "email": 254,
    "phone": 40,
    "whatsapp": 40,
    "contact_country": 2,
    "origin_country": 2,
    "destination_country": 2,
    "source_url": 500,
    "referrer_url": 500,
}

#: Accepted operation types, mirrored from the module rather than imported.
#:
#: dally_api does not depend on dally_trade — the endpoint degrades to a clear 503 if
#: the module is absent — so the tuple is duplicated here and asserted equal by a test.
#: A duplicate a test guards is safer than an import that makes the API unloadable
#: without the trade module installed.
ACCEPTED_OPERATION_TYPES = (
    "purchase_resale",
    "brokerage",
    "commission",
    "distribution",
    "import_export",
    "commercial_representation",
)


class DallyTradeController(DallyApiController):

    @http.route(
        "/api/v1/trade/opportunities",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def create_trade_opportunity(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/trade/opportunities",
            # Reuses the scope already declared in dally.api.key. A second spelling
            # (`trade:write`) would mean two names for one permission, and a key
            # granted one would silently fail the other.
            required_scope="trading:write",
            handler=self._create_trade_opportunity,
        )

    def _create_trade_opportunity(self, env, payload, api_key):
        if "dally.trade.opportunity" not in env:
            # Honest failure rather than a 500: the endpoint is routed but the module
            # that backs it is not installed.
            raise DallyApiError(
                503, "module_unavailable",
                _("The trade module is not available on this instance."),
            )

        self._reject_internal_fields(payload)
        clean = self._flatten(payload)

        self._require(clean, "subject")
        self._require_email_or_phone(clean)
        self._validate_operation_type(clean)
        self._validate_countries(env, clean)
        if clean.get("request_uuid"):
            self._validate_uuid(clean["request_uuid"])

        deal = env["dally.trade.opportunity"].dally_create_from_website(clean)

        # Only what the site needs back. No database id, no counterparty, no price:
        # the caller learns their reference and that it was received.
        return {
            "reference": deal.reference,
            "operationType": deal.operation_type,
            "status": "received",
            "_record": deal,
        }, 201

    # ─── Payload handling ────────────────────────────────────────────

    @classmethod
    def _reject_internal_fields(cls, payload):
        """Refuse an internal field by name, at any nesting level.

        Checked before flattening, so a field smuggled inside `contact` is caught too.
        """
        def _walk(node, path=""):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in FORBIDDEN_FIELDS:
                        raise DallyApiError(
                            422, "forbidden_field",
                            _(
                                "Field '%s' is internal and cannot be set through "
                                "this endpoint.",
                                f"{path}{key}",
                            ),
                        )
                    _walk(value, f"{path}{key}.")
            elif isinstance(node, list):
                for item in node:
                    _walk(item, path)

        _walk(payload)

    @classmethod
    def _flatten(cls, payload):
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

        return cls._coerce(flat)

    @staticmethod
    def _coerce(flat):
        """Trim strings and enforce length caps."""
        clean = {}
        for name, value in flat.items():
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
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
        return clean

    @staticmethod
    def _validate_operation_type(clean):
        """Refuse an unknown type rather than defaulting to achat-revente.

        Defaulting would file a courtage as a purchase-and-resale, and every rule
        downstream — whether a purchase order is allowed, whether there is a margin to
        compute — would then be the wrong one.
        """
        value = clean.get("operation_type")
        if not value:
            return
        if value not in ACCEPTED_OPERATION_TYPES:
            raise DallyApiError(
                422, "invalid_operation_type",
                _(
                    "Unknown operation type '%(value)s'. Accepted: %(accepted)s.",
                    value=value,
                    accepted=", ".join(ACCEPTED_OPERATION_TYPES),
                ),
            )

    @staticmethod
    def _validate_countries(env, clean):
        """Country codes must exist. No default is substituted.

        Guessing a country would attribute an enquiry to a market it never came from,
        and that attribution ends up in reporting.
        """
        Country = env["res.country"]
        for field in ("contact_country", "origin_country", "destination_country"):
            code = (clean.get(field) or "").strip().upper()
            if not code:
                continue
            # No sudo(): res.country is readable by every internal user, and reaching
            # for sudo here would set the precedent that this path may bypass the
            # record rules and field groups that protect everything else.
            if not Country.search([("code", "=", code)], limit=1):
                raise DallyApiError(
                    422, "unknown_country",
                    _("Unknown country code '%(code)s' for field '%(field)s'.",
                      code=code, field=field),
                )
            clean[field] = code
