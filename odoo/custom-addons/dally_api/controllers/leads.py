# -*- coding: utf-8 -*-
"""POST /api/v1/leads — intake of public quote and contact requests."""

from odoo import _, http

from .main import DallyApiController, DallyApiError

#: Fields read from the payload. Anything else is ignored rather than passed
#: through: an allowlist means a caller cannot set arbitrary lead fields such as
#: user_id, stage_id or expected_revenue.
LEAD_INPUT_FIELDS = (
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
    "message",
    "source_url",
    "utm_source",
    "utm_medium",
    "utm_campaign",
)

#: Per-field length caps. The website validates too, but the API cannot trust it:
#: it is reachable independently of the browser.
MAX_LENGTHS = {
    "first_name": 100,
    "last_name": 100,
    "company_name": 200,
    "email": 254,
    "phone": 40,
    "whatsapp": 40,
    "city": 100,
    "country_code": 2,
    "service_code": 50,
    "source_url": 500,
    "utm_source": 100,
    "utm_medium": 100,
    "utm_campaign": 100,
    "message": 20000,
}


class DallyLeadsController(DallyApiController):

    @http.route(
        "/api/v1/leads",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        # No session cookie for API calls: they are stateless and a cookie would
        # only add an attack surface.
        save_session=False,
    )
    def create_lead(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/leads",
            required_scope="leads:write",
            handler=self._create_lead,
        )

    def _create_lead(self, env, payload, api_key):
        clean = self._clean_lead_payload(payload)

        self._require(clean, "service_code", "last_name")
        self._require_email_or_phone(clean)
        self._validate_email_leads(clean.get("email"))

        lead = env["crm.lead"].dally_create_from_website(clean)

        # Only what the website legitimately needs back. The lead id is
        # deliberately not exposed: a sequential database id must never become an
        # authorisation handle (§42).
        data = {
            "reference": lead.dally_reference,
            "service": lead.dally_service_type_id.code or None,
            "status": "received",
            "_record": lead,
        }
        return data, 201

    @staticmethod
    def _clean_lead_payload(payload):
        """Keep allowlisted fields, trim strings, enforce length caps."""
        clean = {}
        for name in LEAD_INPUT_FIELDS:
            value = payload.get(name)
            if value is None:
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

        if clean.get("country_code"):
            clean["country_code"] = clean["country_code"].upper()
        return clean

    @staticmethod
    def _validate_email_leads(email):
        """Structural check only.

        Full RFC validation rejects addresses that work in practice. Deliverability
        is proven by sending the confirmation e-mail, not by a regex.
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


class DallyHealthController(DallyApiController):
    """Health endpoint for monitoring (§15).

    Authenticated: an unauthenticated endpoint that confirms Odoo is alive and
    which database answers is free reconnaissance. Monitoring holds a key with
    no write scope.
    """

    @http.route(
        "/api/v1/health",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def health(self, **kwargs):
        try:
            api_key, env = self._authenticate("customers:read")
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        # A trivial query proves the database is actually reachable, which a bare
        # "ok" would not.
        env.cr.execute("SELECT 1")
        return self._success({
            "status": "ok",
            "database": env.cr.dbname,
            "key": api_key.name,
        })
