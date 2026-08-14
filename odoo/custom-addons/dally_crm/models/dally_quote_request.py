# -*- coding: utf-8 -*-
"""Quote requests — the qualifiable commercial request.

## Why this model exists rather than going straight to sale.order

A public form submission is not a quotation. Turning every one into a
``sale.order`` would fill the sales pipeline with incomplete drafts and spam, and
every one of them would carry a number that looks like a commitment.

The flow is therefore::

    website form → dally.quote.request → crm.lead (opportunity)
                 → qualification → sale.order → confirmation → dally.shipment

Each step is a deliberate human decision. Nothing downstream is created
automatically: in particular **no shipment is created by a quote request**. A
freight file is an operational object, and it comes into existence when the deal
is real, not when someone fills a form (§ separation lead/shipment).

## Why not simply extend crm.lead

``crm.lead`` is the *pipeline* object: its stage, its salesperson and its
description all move as the deal progresses. The request is the opposite — it is
the verbatim record of what the customer asked for, on the day they asked. Keeping
them apart means qualifying a lead never rewrites the customer's original words,
and gives the structured freight data a home without adding fifteen columns to a
native model.

The two are linked by ``lead_id`` and share the same public reference, so support
can find either from the other.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

#: Qualification states. Deliberately short: this object exists to be triaged,
#: not to run a second pipeline alongside the CRM's own stages.
REQUEST_STATES = [
    ("new", "New"),
    ("qualified", "Qualified"),
    ("quoted", "Quoted"),
    ("won", "Won"),
    ("lost", "Lost"),
    ("spam", "Spam"),
]

MESSAGE_MAX_LENGTH = 20000


class DallyQuoteRequest(models.Model):
    _name = "dally.quote.request"
    _description = "DallyTrading Quote Request"
    _inherit = ["dally.reference.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    #: Shares the generic DT-YYYY-NNNNNN series with website leads: from the
    #: customer's point of view there is one request number, whatever object
    #: DallyTrading stores it in.
    _dally_sequence_code = "dally.reference"

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)

    # ─── What was asked ──────────────────────────────────────────────
    service_type_id = fields.Many2one(
        comodel_name="dally.service.type",
        string="Service",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    service_code = fields.Char(
        related="service_type_id.code",
        string="Service Code",
        store=True,
        index=True,
        readonly=True,
        help="Stored so reporting and API lookups do not need a join.",
    )

    # ─── Who asked ───────────────────────────────────────────────────
    contact_name = fields.Char(string="Contact Name", tracking=True)
    company_name = fields.Char(string="Company Name")
    email = fields.Char(string="Email", index=True)
    phone = fields.Char(string="Phone", index=True)
    whatsapp = fields.Char(string="WhatsApp")
    city = fields.Char(string="City")
    country_id = fields.Many2one(comodel_name="res.country", string="Country")

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Contact",
        index=True,
        tracking=True,
        help="Existing contact this request was matched to, or the one created "
             "from it during qualification.",
    )

    # ─── Route ───────────────────────────────────────────────────────
    origin_country_id = fields.Many2one(
        comodel_name="res.country", string="Origin Country"
    )
    origin_city = fields.Char(string="Origin City")
    destination_country_id = fields.Many2one(
        comodel_name="res.country", string="Destination Country"
    )
    destination_city = fields.Char(string="Destination City")

    # ─── Cargo ───────────────────────────────────────────────────────
    goods_description = fields.Text(string="Goods")
    quantity = fields.Char(
        string="Quantity",
        help="Free text on purpose: customers answer '3 pallets', '2 tonnes' or "
             "'500 units'. Forcing a number here loses the unit, which is the "
             "part a salesperson actually needs.",
    )
    weight_kg = fields.Float(string="Weight (kg)", digits=(12, 3))
    volume_cbm = fields.Float(string="Volume (CBM)", digits=(12, 4))
    packages_count = fields.Integer(string="Packages")

    # Vehicle shipments describe what is shipped differently.
    vehicle_make = fields.Char(string="Vehicle Make")
    vehicle_model = fields.Char(string="Vehicle Model")
    vehicle_year = fields.Char(string="Vehicle Year")

    budget = fields.Char(
        string="Budget / Target Price",
        help="Free text, and deliberately not a Monetary: customers write "
             "'around 2M FCFA' or '3000 EUR per tonne'. A currency field would "
             "force a precision they have not decided on yet.",
    )

    message = fields.Text(string="Message")

    # ─── Attribution ─────────────────────────────────────────────────
    source_url = fields.Char(string="Source URL")
    referrer_url = fields.Char(
        string="Referrer",
        help="Where the visitor came from, as sent by the browser.",
    )
    utm_source = fields.Char(string="UTM Source")
    utm_medium = fields.Char(string="UTM Medium")
    utm_campaign = fields.Char(string="UTM Campaign")

    # ─── Idempotency ─────────────────────────────────────────────────
    request_uuid = fields.Char(
        string="Request UUID",
        required=True,
        copy=False,
        index=True,
        help="Client-generated identifier. The unique constraint on this column "
             "is what makes submission idempotent: a double-click or a network "
             "retry cannot create two requests.",
    )

    # ─── Qualification ───────────────────────────────────────────────
    state = fields.Selection(
        selection=REQUEST_STATES,
        string="Status",
        default="new",
        required=True,
        index=True,
        tracking=True,
        copy=False,
    )
        # Restreint au personnel interne. Un utilisateur portail lit ses propres
        # dossiers ; ce champ, lui, expose l'identité d'un salarié et ne doit
        # jamais lui être chargé par l'ORM, même sur un record qui lui appartient.
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Salesperson",
        index=True,
        tracking=True,
        domain=[("share", "=", False)],
        help="Left empty on intake, on purpose: assignment is a management "
             "decision, and an unassigned queue is visible whereas a wrongly "
             "assigned request is not.",
        groups="dally_core.group_dally_readonly",
    )

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Opportunity",
        index=True,
        copy=False,
        help="CRM opportunity created from this request.",
    )
    sale_order_ids = fields.One2many(
        comodel_name="sale.order",
        inverse_name="dally_quote_request_id",
        string="Quotations",
    )
    sale_order_count = fields.Integer(
        string="Quotations", compute="_compute_sale_order_count"
    )

    internal_notes = fields.Text(
        string="Internal Notes",
        groups="dally_core.group_dally_readonly",
        help="Never exposed by any public endpoint.",
    )

    _dally_quote_request_uuid_uniq = models.Constraint(
        'UNIQUE(request_uuid)',
        'This request has already been recorded.',
    )

    @api.depends("sale_order_ids")
    def _compute_sale_order_count(self):
        for request in self:
            request.sale_order_count = len(request.sale_order_ids)

    @api.constrains("email", "phone")
    def _check_contact_channel(self):
        """A request nobody can answer is not a lead."""
        for request in self:
            if not (request.email or "").strip() and not (request.phone or "").strip():
                raise ValidationError(
                    _("A request needs at least an email address or a phone number.")
                )

    # ─── Intake ──────────────────────────────────────────────────────

    @api.model
    def dally_create_from_website(self, payload):
        """Create a request from a validated public payload, idempotently.

        Returns the request, whether created now or by an earlier identical
        submission, so the caller always gets a usable record.

        Deliberately creates **only** the request and its CRM opportunity. No
        partner is created, no quotation, no shipment — those follow human
        qualification.
        """
        request_uuid = (payload.get("request_uuid") or "").strip()
        if request_uuid:
            # active_test=False is essential, not defensive. A request marked as
            # spam is archived, and an archived record is invisible to a plain
            # search — so a replay would fall through to create(), hit the UNIQUE
            # constraint on request_uuid and surface as a 500. Searching archived
            # records too means a replay of a spam submission is answered exactly
            # like any other replay.
            existing = self.with_context(active_test=False).search(
                [("request_uuid", "=", request_uuid)], limit=1
            )
            if existing:
                return existing

        values = self._dally_prepare_values(payload)
        request = self.create(values)
        request._dally_create_lead()
        request._dally_log_intake(payload)
        return request

    @api.model
    def _dally_prepare_values(self, payload):
        """Map a validated payload onto field values.

        Kept in the model rather than the controller so the mapping is testable
        without HTTP, and reusable by any other channel — an import, a WhatsApp
        bot — without duplicating business rules.
        """
        service = self.env["dally.service.type"]._get_by_code(
            payload.get("service_code")
        )
        if not service:
            raise UserError(
                _("Unknown service code '%s'.", payload.get("service_code") or "")
            )

        Country = self.env["res.country"]

        def country(code):
            cleaned = (code or "").strip().upper()
            if not cleaned:
                return False
            found = Country.search([("code", "=", cleaned)], limit=1)
            return found.id or False

        def text(key, limit=None):
            value = (payload.get(key) or "")
            value = value.strip() if isinstance(value, str) else str(value)
            if limit and len(value) > limit:
                value = value[:limit]
            return value or False

        def number(key):
            raw = payload.get(key)
            if raw in (None, "", False):
                return 0.0
            try:
                return float(raw)
            except (TypeError, ValueError):
                return 0.0

        contact_name = " ".join(
            part for part in (payload.get("first_name"), payload.get("last_name"))
            if part
        ).strip()

        # Match an existing contact but do not create one, and never edit one.
        partner = self.env["res.partner"]._dally_find_existing(
            email=text("email") or None,
            phone=text("phone") or None,
            whatsapp=text("whatsapp") or None,
            company_name=text("company_name") or None,
        )

        return {
            "service_type_id": service.id,
            "contact_name": contact_name or False,
            "company_name": text("company_name", 200),
            "email": text("email", 254),
            "phone": text("phone", 40),
            "whatsapp": text("whatsapp", 40),
            "city": text("city", 100),
            "country_id": country(payload.get("country_code")),
            "partner_id": partner.id or False,
            "origin_country_id": country(payload.get("origin_country_code")),
            "origin_city": text("origin_city", 100),
            "destination_country_id": country(payload.get("destination_country_code")),
            "destination_city": text("destination_city", 100),
            "goods_description": text("goods_description", 5000),
            "quantity": text("quantity", 100),
            "weight_kg": number("weight_kg"),
            "volume_cbm": number("volume_cbm"),
            "packages_count": int(number("packages_count")),
            "vehicle_make": text("vehicle_make", 100),
            "vehicle_model": text("vehicle_model", 100),
            "vehicle_year": text("vehicle_year", 10),
            "budget": text("budget", 100),
            "message": text("message", MESSAGE_MAX_LENGTH),
            "source_url": text("source_url", 500),
            "referrer_url": text("referrer_url", 500),
            "utm_source": text("utm_source", 100),
            "utm_medium": text("utm_medium", 100),
            "utm_campaign": text("utm_campaign", 100),
            "request_uuid": text("request_uuid", 64),
        }

    def _dally_create_lead(self):
        """Create the CRM opportunity for this request.

        The lead carries the *same* public reference, so no second number is
        drawn: a customer holds one reference, whatever object it is stored in.
        """
        self.ensure_one()
        if self.lead_id:
            return self.lead_id

        Lead = self.env["crm.lead"]
        subject_parts = [self.service_type_id.name or _("Request")]
        if self.company_name:
            subject_parts.append(self.company_name)
        elif self.contact_name:
            subject_parts.append(self.contact_name)

        values = {
            "name": " — ".join(subject_parts),
            # An opportunity rather than a lead: it comes with a stated need and
            # a service, which is what qualification works on.
            "type": "opportunity",
            "contact_name": self.contact_name or False,
            "partner_name": self.company_name or False,
            "email_from": self.email or False,
            "phone": self.phone or False,
            "dally_whatsapp": self.whatsapp or False,
            "city": self.city or False,
            "country_id": self.country_id.id or False,
            "partner_id": self.partner_id.id or False,
            "description": self._dally_lead_description(),
            "dally_service_type_id": self.service_type_id.id,
            "dally_reference": self.reference,
            "dally_request_uuid": self.request_uuid,
            "dally_source_url": self.source_url or False,
            "dally_utm_source": self.utm_source or False,
            "dally_utm_medium": self.utm_medium or False,
            "dally_utm_campaign": self.utm_campaign or False,
        }

        source = self.env.ref(
            "dally_crm.utm_source_dallytrading_website", raise_if_not_found=False
        )
        if source:
            values["source_id"] = source.id
        medium = self.env.ref(
            "dally_crm.utm_medium_website_form", raise_if_not_found=False
        )
        if medium:
            values["medium_id"] = medium.id

        lead = Lead.with_context(
            dally_preserve_partner_contact=True
        ).create(values)
        self.lead_id = lead
        return lead

    def _dally_lead_description(self):
        """Readable summary of the request, for the opportunity body.

        Only the sections the service actually asked for appear: an empty
        "Vehicle" heading on a sourcing request is noise a salesperson has to
        read past.
        """
        self.ensure_one()
        lines = [_("Request %s", self.reference)]

        if self.origin_city or self.origin_country_id:
            lines.append(_("Origin: %s", ", ".join(
                part for part in (self.origin_city, self.origin_country_id.name)
                if part
            )))
        if self.destination_city or self.destination_country_id:
            lines.append(_("Destination: %s", ", ".join(
                part for part in (self.destination_city, self.destination_country_id.name)
                if part
            )))
        if self.goods_description:
            lines.append(_("Goods: %s", self.goods_description))
        if self.quantity:
            lines.append(_("Quantity: %s", self.quantity))
        if self.weight_kg:
            lines.append(_("Weight: %s kg", self.weight_kg))
        if self.volume_cbm:
            lines.append(_("Volume: %s CBM", self.volume_cbm))
        if self.packages_count:
            lines.append(_("Packages: %s", self.packages_count))
        if self.vehicle_make or self.vehicle_model:
            lines.append(_("Vehicle: %s", " ".join(
                part for part in (self.vehicle_make, self.vehicle_model,
                                  self.vehicle_year) if part
            )))
        if self.budget:
            lines.append(_("Budget: %s", self.budget))
        if self.message:
            lines.append(_("Message: %s", self.message))

        return "\n".join(lines)

    def _dally_log_intake(self, payload):
        """Record how the request arrived, in the chatter (§57)."""
        self.ensure_one()
        lines = [_("Request received from the website.")]
        if payload.get("source_url"):
            lines.append(_("Page: %s", payload["source_url"]))
        if payload.get("referrer_url"):
            lines.append(_("Referrer: %s", payload["referrer_url"]))
        utm = [payload.get("utm_source"), payload.get("utm_medium"),
               payload.get("utm_campaign")]
        if any(utm):
            lines.append(_("UTM: %s", " / ".join(part or "—" for part in utm)))
        if self.partner_id:
            lines.append(_("Matched to existing contact: %s", self.partner_id.display_name))
        else:
            lines.append(_("No existing contact matched."))
        self.message_post(body="<br/>".join(lines))

    # ─── Qualification actions ───────────────────────────────────────

    def action_create_partner(self):
        """Create the res.partner for this request, during qualification.

        Deliberately manual. Creating a contact for every submission fills the
        address book with spam and with prospects who never answer; a human
        decides that this one is real.
        """
        for request in self:
            if request.partner_id:
                continue
            if not request.contact_name and not request.company_name:
                raise UserError(
                    _("Request %s has no name to create a contact from.",
                      request.reference)
                )

            is_company = bool(request.company_name and not request.contact_name)
            partner = self.env["res.partner"].create({
                "name": request.company_name or request.contact_name,
                "is_company": is_company,
                "email": request.email or False,
                "phone": request.phone or False,
                "dally_whatsapp": request.whatsapp or False,
                "city": request.city or False,
                "country_id": request.country_id.id or False,
            })
            request.partner_id = partner
            if request.lead_id and not request.lead_id.partner_id:
                request.lead_id.partner_id = partner
        return True

    def action_mark_qualified(self):
        self.write({"state": "qualified"})
        return True

    def action_mark_spam(self):
        """Mark as spam and archive, without deleting.

        Keeping the record means the same submission cannot come back through
        idempotency, and the request log stays auditable.
        """
        self.write({"state": "spam", "active": False})
        return True

    def action_create_quotation(self):
        """Create a draft sale.order from this request.

        This is the point where a commercial document comes into existence, and it
        is a human action — never a side effect of the form. Lines are left empty
        on purpose: pricing freight requires the operator to choose services and
        rates, and a pre-filled guess would be quoted by mistake.
        """
        self.ensure_one()
        if not self.partner_id:
            raise UserError(
                _(
                    "Create or link a contact before raising a quotation: a "
                    "sale.order needs a customer."
                )
            )

        order = self.env["sale.order"].create({
            "partner_id": self.partner_id.id,
            "origin": self.reference,
            "dally_quote_request_id": self.id,
            "opportunity_id": self.lead_id.id or False,
        })
        self.state = "quoted"

        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": order.id,
            "view_mode": "form",
        }

    def action_view_lead(self):
        self.ensure_one()
        if not self.lead_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "crm.lead",
            "res_id": self.lead_id.id,
            "view_mode": "form",
        }

    def action_view_quotations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Quotations"),
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("dally_quote_request_id", "=", self.id)],
        }
