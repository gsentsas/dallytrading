# -*- coding: utf-8 -*-
"""Website requests as native CRM leads.

Everything a public form submits lands in ``crm.lead``. No parallel "website
request" model: pipelines, activities, reporting and the chatter already exist
and work (§70).
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

#: Maximum length accepted for the free-text message. Anything longer is almost
#: certainly a paste accident or spam; the API rejects it before it reaches here.
DESCRIPTION_MAX_LENGTH = 20000


class CrmLead(models.Model):
    _inherit = "crm.lead"

    dally_reference = fields.Char(
        string="DallyTrading Reference",
        readonly=True,
        copy=False,
        index=True,
        help="Reference shared with the customer (DT-YYYY-NNNNNN). Shown on the "
             "website confirmation screen and quoted in e-mails.",
    )
    dally_service_type_id = fields.Many2one(
        comodel_name="dally.service.type",
        string="Requested Service",
        ondelete="restrict",
        index=True,
        help="Service selected by the customer on the public form.",
    )
    dally_service_category = fields.Selection(
        related="dally_service_type_id.category",
        string="Service Category",
        store=True,
        index=True,
        help="Stored copy, so reporting by category stays fast and keeps working "
             "even if a service type is later re-categorised.",
    )
    dally_whatsapp = fields.Char(
        string="WhatsApp",
        help="WhatsApp number given by the customer.",
    )

    # ─── Attribution ─────────────────────────────────────────────────
    # Odoo already normalises campaign data into source_id / medium_id /
    # campaign_id. The raw strings are kept alongside because normalisation is
    # lossy: it silently maps unknown values, and an attribution dispute needs
    # the exact values the browser sent.
    dally_source_url = fields.Char(
        string="Source URL",
        help="Page the request was submitted from, as received.",
    )
    dally_utm_source = fields.Char(string="UTM Source (raw)")
    dally_utm_medium = fields.Char(string="UTM Medium (raw)")
    dally_utm_campaign = fields.Char(string="UTM Campaign (raw)")

    # ─── Idempotency (§41) ───────────────────────────────────────────
    dally_request_uuid = fields.Char(
        string="Request UUID",
        copy=False,
        index=True,
        help="Client-generated identifier for the submission. A unique "
             "constraint on this column is what makes lead creation idempotent: "
             "a double-click or a network retry cannot produce two leads.",
    )

    _dally_request_uuid_uniq = models.Constraint(
        'UNIQUE(dally_request_uuid)',
        'A request with this identifier already exists. The submission was already recorded.',
    )

    # ─── Creation ────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        """Assign a DallyTrading reference to leads that come from our channels.

        Only leads carrying a service or a request UUID get one: manually created
        leads and leads from other sources keep the plain Odoo behaviour, so the
        reference series is not consumed by internal prospecting.
        """
        for vals in vals_list:
            needs_reference = (
                not vals.get("dally_reference")
                and (vals.get("dally_service_type_id") or vals.get("dally_request_uuid"))
            )
            if needs_reference:
                vals["dally_reference"] = self.env["ir.sequence"].next_by_code(
                    "dally.reference"
                )
        return super().create(vals_list)

    def action_dally_assign_reference(self):
        """Give an existing lead a reference, for leads created before the module."""
        for lead in self:
            if not lead.dally_reference:
                lead.dally_reference = self.env["ir.sequence"].next_by_code(
                    "dally.reference"
                )
        return True

    # ─── Intake from the public website ──────────────────────────────

    @api.model
    def _dally_prepare_lead_values(self, payload):
        """Translate a validated public payload into ``crm.lead`` values.

        Kept in the model rather than in the API controller so that the mapping
        is unit-testable without going through HTTP, and reusable by any other
        channel (an import, a WhatsApp bot) without duplicating business rules.

        ``payload`` is expected to be already validated and type-correct — the
        API layer owns validation. What this method owns is the mapping and the
        resolution of business objects (service, country, partner).
        """
        service = self.env["dally.service.type"]._get_by_code(payload.get("service_code"))
        if payload.get("service_code") and not service:
            raise UserError(
                _("Unknown service code '%s'.", payload["service_code"])
            )

        country = self.env["res.country"]
        country_code = (payload.get("country_code") or "").strip().upper()
        if country_code:
            country = country.search([("code", "=", country_code)], limit=1)

        contact_name = " ".join(
            part for part in (payload.get("first_name"), payload.get("last_name")) if part
        ).strip()

        company_name = (payload.get("company_name") or "").strip()

        # Build the lead subject. It is what appears in the pipeline kanban, so
        # it must identify the request at a glance.
        subject_bits = [service.name or _("Request")]
        if company_name:
            subject_bits.append(company_name)
        elif contact_name:
            subject_bits.append(contact_name)

        description = (payload.get("message") or "").strip()
        if len(description) > DESCRIPTION_MAX_LENGTH:
            description = description[:DESCRIPTION_MAX_LENGTH]

        values = {
            "name": " — ".join(subject_bits),
            "type": "lead",
            "contact_name": contact_name or False,
            "partner_name": company_name or False,
            "email_from": (payload.get("email") or "").strip() or False,
            "phone": (payload.get("phone") or "").strip() or False,
            "dally_whatsapp": (payload.get("whatsapp") or "").strip() or False,
            "city": (payload.get("city") or "").strip() or False,
            "country_id": country.id or False,
            "description": description or False,
            "dally_service_type_id": service.id or False,
            "dally_source_url": payload.get("source_url") or False,
            "dally_utm_source": payload.get("utm_source") or False,
            "dally_utm_medium": payload.get("utm_medium") or False,
            "dally_utm_campaign": payload.get("utm_campaign") or False,
            "dally_request_uuid": payload.get("request_uuid") or False,
        }

        # Attribute the lead to the website source, so native CRM reporting by
        # source works without extra configuration (§27).
        source = self.env.ref("dally_crm.utm_source_dallytrading_website",
                              raise_if_not_found=False)
        if source:
            values["source_id"] = source.id

        medium = self.env.ref("dally_crm.utm_medium_website_form",
                              raise_if_not_found=False)
        if medium:
            values["medium_id"] = medium.id

        # Link to an existing contact when we can identify one. Deliberately a
        # link, never an edit: existing partner data is left untouched (§28).
        partner = self.env["res.partner"]._dally_find_existing(
            email=values["email_from"],
            phone=values["phone"],
            whatsapp=values["dally_whatsapp"],
            company_name=company_name,
        )
        if partner:
            values["partner_id"] = partner.id

        return values

    @api.model
    def dally_create_from_website(self, payload):
        """Create a lead from a validated public payload, idempotently.

        Returns the lead, whether it was created now or by an earlier identical
        submission. Callers can rely on getting a usable record either way.
        """
        request_uuid = payload.get("request_uuid")

        if request_uuid:
            existing = self.search([("dally_request_uuid", "=", request_uuid)], limit=1)
            if existing:
                # Replay of a submission we already recorded. Returning the
                # original record is what makes the endpoint safe to retry.
                return existing

        values = self._dally_prepare_lead_values(payload)
        lead = self.create(values)

        # Log the raw attribution in the chatter: it survives field changes and
        # gives support the exact context of the submission.
        lead._dally_log_intake(payload)
        return lead

    def _dally_log_intake(self, payload):
        """Record how the request arrived, in the chatter (§57)."""
        self.ensure_one()
        lines = [_("Request received from the website.")]
        if self.dally_reference:
            lines.append(_("Reference: %s", self.dally_reference))
        if payload.get("source_url"):
            lines.append(_("Page: %s", payload["source_url"]))
        utm = [
            payload.get("utm_source"),
            payload.get("utm_medium"),
            payload.get("utm_campaign"),
        ]
        if any(utm):
            lines.append(_("UTM: %s", " / ".join(part or "—" for part in utm)))
        if payload.get("request_uuid"):
            lines.append(_("Request id: %s", payload["request_uuid"]))

        self.message_post(body="<br/>".join(lines))
