# -*- coding: utf-8 -*-
"""Sourcing requests — the client's original ask, and the case built around it.

## What this model is, and is not

It is the **client's request**, preserved as submitted. Qualification, supplier
research and negotiation all happen around it without rewriting it: the customer's
own words, quantity and budget stay readable months later, which is what lets a
salesperson check whether what was delivered is what was asked for.

It is **not** a trading engine. Sourcing answers "find me this product or this
supplier". Direct participation in buying and reselling belongs to ``dally_trade``,
and keeping that line means neither module becomes a vague catch-all.

## Where the confidentiality boundary runs

Supplier offers, internal costs and margins live on ``dally.sourcing.offer`` and are
never part of a public payload. What a customer sees is a
``dally.sourcing.proposal``, which DallyTrading composes deliberately. The two are
separate models precisely so that "show the customer the offer" cannot happen by
accident.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

#: Workflow states, in business order.
#:
#: Sixteen looks like a lot, but each one answers a question an operator actually
#: asks ("has anyone replied yet?", "have we compared them?"). Collapsing them would
#: mean tracking the same information in a note field, where it cannot be filtered.
SOURCING_STATES = [
    ("new", "New"),
    ("to_qualify", "To Qualify"),
    ("researching", "Researching Suppliers"),
    ("suppliers_identified", "Suppliers Identified"),
    ("offers_received", "Offers Received"),
    ("comparing", "Comparing Offers"),
    ("proposal_ready", "Proposal Ready"),
    ("proposal_sent", "Proposal Sent"),
    ("negotiating", "Negotiating"),
    ("accepted", "Accepted"),
    ("purchasing", "Purchasing"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
    ("on_hold", "On Hold"),
    ("rejected", "Rejected"),
    ("cancelled", "Cancelled"),
]

#: States from which nothing further happens without an explicit reopen.
TERMINAL_STATES = ("completed", "rejected", "cancelled")

#: States a request may be put on hold from, and returned to.
HOLDABLE_STATES = (
    "to_qualify", "researching", "suppliers_identified", "offers_received",
    "comparing", "proposal_ready", "proposal_sent", "negotiating", "accepted",
    "purchasing", "in_progress",
)

#: Allowed transitions.
#:
#: Declared as data rather than scattered through the action methods, so the whole
#: workflow can be read in one place — and asserted by a test. Without this, a
#: request could jump from `new` straight to `completed`, which is how a file gets
#: closed with no supplier, no offer and no purchase order behind it.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new": ("to_qualify", "rejected", "cancelled"),
    "to_qualify": ("researching", "on_hold", "rejected", "cancelled"),
    "researching": ("suppliers_identified", "on_hold", "rejected", "cancelled"),
    "suppliers_identified": (
        "offers_received", "researching", "on_hold", "rejected", "cancelled",
    ),
    "offers_received": (
        "comparing", "suppliers_identified", "on_hold", "rejected", "cancelled",
    ),
    "comparing": (
        "proposal_ready", "offers_received", "on_hold", "rejected", "cancelled",
    ),
    "proposal_ready": (
        "proposal_sent", "comparing", "on_hold", "rejected", "cancelled",
    ),
    "proposal_sent": (
        "negotiating", "accepted", "rejected", "on_hold", "cancelled",
    ),
    "negotiating": (
        "accepted", "rejected", "proposal_ready", "on_hold", "cancelled",
    ),
    "accepted": ("purchasing", "on_hold", "cancelled"),
    "purchasing": ("in_progress", "on_hold", "cancelled"),
    "in_progress": ("completed", "on_hold", "cancelled"),
    # Terminal. Reopening is a deliberate act, not a transition.
    "completed": (),
    "rejected": (),
    "cancelled": (),
    # on_hold returns to where it came from; the target is validated separately.
    "on_hold": HOLDABLE_STATES + ("rejected", "cancelled"),
}

TEXT_LIMITS = {
    "product_name": 200,
    "product_description": 10000,
    "specifications": 10000,
    "customer_notes": 10000,
}


class DallySourcingRequest(models.Model):
    _name = "dally.sourcing.request"
    _description = "DallyTrading Sourcing Request"
    _inherit = ["dally.reference.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    #: Feeds the mixin from dally_core. Produces DT-SRC-YYYY-NNNNNN.
    _dally_sequence_code = "dally.sourcing.request"

    # ─── Identification ──────────────────────────────────────────────
    # `reference` comes from dally.reference.mixin: unique, readonly, not copied.

    request_uuid = fields.Char(
        string="Request UUID",
        copy=False,
        index=True,
        help="Client-generated idempotency key. The unique constraint on this "
             "column is what prevents a double submission from creating two "
             "requests.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)

    # ─── Customer ────────────────────────────────────────────────────
    customer_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        index=True,
        tracking=True,
        help="Existing contact this request was matched to, or the one created "
             "from it during qualification. Left empty on intake: creating a "
             "contact per public submission fills the address book with prospects "
             "who never reply.",
    )
    # Captured as submitted, so the request stays readable even before a partner
    # exists — and so qualification never overwrites what the customer wrote.
    contact_name = fields.Char(string="Contact Name", tracking=True)
    company_name = fields.Char(string="Company Name")
    contact_email = fields.Char(string="Email", index=True)
    contact_phone = fields.Char(string="Phone", index=True)
    contact_whatsapp = fields.Char(string="WhatsApp")

    crm_lead_id = fields.Many2one(
        comodel_name="crm.lead",
        string="CRM Opportunity",
        index=True,
        copy=False,
        help="Created during qualification, not on intake: not every request "
             "received from the internet deserves a pipeline entry.",
    )

    responsible_id = fields.Many2one(
        comodel_name="res.users",
        string="Responsible",
        index=True,
        tracking=True,
        domain=[("share", "=", False)],
        help="Left empty on intake on purpose: assignment is a management "
             "decision, and an unassigned queue is visible whereas a wrongly "
             "assigned request is not.",
    )
    team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Sales Team",
        index=True,
    )

    service_id = fields.Many2one(
        comodel_name="dally.service.type",
        string="Service",
        ondelete="restrict",
        index=True,
        help="The activity this request belongs to, from the dally_core catalogue.",
    )

    # ─── What is being sourced ───────────────────────────────────────
    product_name = fields.Char(string="Product", required=True, tracking=True)
    product_description = fields.Text(string="Description")
    specifications = fields.Text(
        string="Specifications",
        help="Technical requirements, standards, packaging, certifications.",
    )
    product_reference = fields.Char(
        string="Reference / Model",
        help="Manufacturer reference or model, when the customer knows it.",
    )
    product_url = fields.Char(
        string="Product Link",
        help="A link the customer supplied. Never fetched by the server: doing so "
             "would turn this field into a server-side request forgery vector.",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Catalogue Product",
        index=True,
        help="The Odoo product this request resolves to. Empty on intake — a customer "
             "describes a need, not a catalogue reference.\n\n"
             "Required before a purchase or sales order can be raised: an order line "
             "needs a real product, and inventing one automatically would fill the "
             "catalogue with near-duplicates nobody curated. Select an existing "
             "product, or create it once the operation is real.",
    )

    quantity = fields.Float(
        string="Quantity", digits=(16, 3), required=True, default=1.0, tracking=True,
    )
    uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unit of Measure",
        help="Native Odoo unit. Not a free-text field, so quantities remain "
             "comparable across offers.",
    )

    # ─── Budget ──────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
        help="The customer's currency. Never assumed: an offer may arrive in "
             "another one and be converted for comparison.",
    )
    target_unit_price = fields.Monetary(
        string="Target Unit Price",
        currency_field="currency_id",
        tracking=True,
    )
    target_total_budget = fields.Monetary(
        string="Total Budget",
        currency_field="currency_id",
        tracking=True,
        help="An order of magnitude is enough. It determines which suppliers are "
             "worth approaching, so it matters as much as the product itself.",
    )

    # ─── Route ───────────────────────────────────────────────────────
    preferred_origin_country_id = fields.Many2one(
        comodel_name="res.country", string="Preferred Origin", index=True,
    )
    destination_country_id = fields.Many2one(
        comodel_name="res.country", string="Destination", index=True,
    )

    # ─── Dates ───────────────────────────────────────────────────────
    requested_deadline = fields.Date(
        string="Requested By",
        tracking=True,
        help="When the customer would like an answer.",
    )
    required_delivery_date = fields.Date(
        string="Required Delivery",
        tracking=True,
        help="When the goods must be on site.",
    )
    is_overdue = fields.Boolean(
        string="Overdue",
        compute="_compute_is_overdue",
        search="_search_is_overdue",
        help="Past its requested date and still open.",
    )

    # ─── Workflow ────────────────────────────────────────────────────
    state = fields.Selection(
        selection=SOURCING_STATES,
        string="Status",
        default="new",
        required=True,
        index=True,
        tracking=True,
        copy=False,
    )
    state_before_hold = fields.Selection(
        selection=SOURCING_STATES,
        string="State Before Hold",
        readonly=True,
        copy=False,
        help="Remembered so resuming returns to where the work actually stopped, "
             "rather than to an arbitrary step.",
    )
    state_changed_on = fields.Datetime(
        string="Status Changed", readonly=True, copy=False,
    )

    # ─── Attribution ─────────────────────────────────────────────────
    source = fields.Char(
        string="Source",
        help="Where the request came from, e.g. Website / Sourcing.",
    )
    source_url = fields.Char(string="Source URL")
    referrer_url = fields.Char(string="Referrer")
    utm_source_id = fields.Many2one(comodel_name="utm.source", string="UTM Source")
    utm_medium_id = fields.Many2one(comodel_name="utm.medium", string="UTM Medium")
    utm_campaign_id = fields.Many2one(
        comodel_name="utm.campaign", string="UTM Campaign",
    )

    # ─── Notes ───────────────────────────────────────────────────────
    customer_notes = fields.Text(
        string="Customer Notes",
        help="What the customer wrote. Read-only in spirit: it is their words.",
    )
    internal_notes = fields.Text(
        string="Internal Notes",
        groups="dally_core.group_dally_readonly",
        help="Never exposed by any public endpoint. The ORM removes this field "
             "for users outside the group, including the sourcing API user.",
    )

    # ─── Related records ─────────────────────────────────────────────
    supplier_ids = fields.One2many(
        comodel_name="dally.sourcing.supplier",
        inverse_name="request_id",
        string="Candidate Suppliers",
    )
    offer_ids = fields.One2many(
        comodel_name="dally.sourcing.offer",
        inverse_name="request_id",
        string="Supplier Offers",
    )
    proposal_ids = fields.One2many(
        comodel_name="dally.sourcing.proposal",
        inverse_name="request_id",
        string="Customer Proposals",
    )
    purchase_order_ids = fields.One2many(
        comodel_name="purchase.order",
        inverse_name="dally_sourcing_request_id",
        string="Purchase Orders",
    )
    sale_order_ids = fields.One2many(
        comodel_name="sale.order",
        inverse_name="dally_sourcing_request_id",
        string="Sales Orders",
    )

    supplier_count = fields.Integer(compute="_compute_counts", string="Suppliers")
    offer_count = fields.Integer(compute="_compute_counts", string="Offers")
    proposal_count = fields.Integer(compute="_compute_counts", string="Proposals")
    purchase_order_count = fields.Integer(
        compute="_compute_counts", string="Purchase Orders",
    )
    sale_order_count = fields.Integer(compute="_compute_counts", string="Sales Orders")

    selected_offer_id = fields.Many2one(
        comodel_name="dally.sourcing.offer",
        string="Selected Offer",
        compute="_compute_selected_offer",
        store=True,
        groups="dally_core.group_dally_sourcing",
        help="The offer marked as selected. Restricted: which supplier was chosen "
             "and at what price is commercial information.",
    )

    _dally_sourcing_request_uuid_uniq = models.Constraint(
        'UNIQUE(request_uuid)',
        'This sourcing request has already been recorded.',
    )
    _dally_sourcing_quantity_positive = models.Constraint(
        'CHECK(quantity > 0)',
        'The quantity must be greater than zero.',
    )
    _dally_sourcing_budget_positive = models.Constraint(
        'CHECK(target_total_budget >= 0)',
        'The budget cannot be negative.',
    )
    _dally_sourcing_unit_price_positive = models.Constraint(
        'CHECK(target_unit_price >= 0)',
        'The target unit price cannot be negative.',
    )

    # ─── Computes ────────────────────────────────────────────────────

    @api.depends("supplier_ids", "offer_ids", "proposal_ids",
                 "purchase_order_ids", "sale_order_ids")
    def _compute_counts(self):
        for request in self:
            request.supplier_count = len(request.supplier_ids)
            request.offer_count = len(request.offer_ids)
            request.proposal_count = len(request.proposal_ids)
            request.purchase_order_count = len(request.purchase_order_ids)
            request.sale_order_count = len(request.sale_order_ids)

    @api.depends("offer_ids", "offer_ids.selected")
    def _compute_selected_offer(self):
        for request in self:
            request.selected_offer_id = request.offer_ids.filtered("selected")[:1]

    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for request in self:
            request.is_overdue = bool(
                request.requested_deadline
                and request.state not in TERMINAL_STATES
                and request.requested_deadline < today
            )

    def _search_is_overdue(self, operator, value):
        """Make `is_overdue` filterable.

        A computed non-stored field is not searchable without this, and "what is
        late" is the first question an operator asks in the morning.
        """
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(_("Unsupported search on 'Overdue'."))

        today = fields.Date.context_today(self)
        looking_for_overdue = (operator == "=") == value
        if looking_for_overdue:
            return [
                ("requested_deadline", "<", today),
                ("state", "not in", list(TERMINAL_STATES)),
            ]
        return [
            "|", "|",
            ("requested_deadline", "=", False),
            ("requested_deadline", ">=", today),
            ("state", "in", list(TERMINAL_STATES)),
        ]

    # ─── Constraints ─────────────────────────────────────────────────

    @api.constrains("requested_deadline", "required_delivery_date")
    def _check_dates(self):
        for request in self:
            if (
                request.requested_deadline
                and request.required_delivery_date
                and request.required_delivery_date < request.requested_deadline
            ):
                raise ValidationError(
                    _(
                        "The required delivery date cannot precede the date the "
                        "customer asked for an answer."
                    )
                )

    @api.constrains("contact_email", "contact_phone", "customer_id")
    def _check_contact_channel(self):
        """A request nobody can answer is not a lead."""
        for request in self:
            has_direct = bool(
                (request.contact_email or "").strip()
                or (request.contact_phone or "").strip()
            )
            if not has_direct and not request.customer_id:
                raise ValidationError(
                    _(
                        "A sourcing request needs an email address, a phone number, "
                        "or a linked customer."
                    )
                )

    # ─── Writes ──────────────────────────────────────────────────────

    def write(self, vals):
        if "state" in vals:
            vals["state_changed_on"] = fields.Datetime.now()
        return super().write(vals)

    def unlink(self):
        """Only an untouched or closed request may be deleted.

        A request with suppliers or offers behind it is a record of work done, and
        of what a supplier quoted. It is archived, not erased.
        """
        for request in self:
            if request.state not in ("new", "cancelled", "rejected"):
                raise UserError(
                    _(
                        "Request %(reference)s is in progress and cannot be deleted. "
                        "Cancel it, or archive it instead.",
                        reference=request.reference,
                    )
                )
            if request.offer_ids or request.purchase_order_ids:
                raise UserError(
                    _(
                        "Request %(reference)s has supplier offers or purchase "
                        "orders attached and cannot be deleted.",
                        reference=request.reference,
                    )
                )
        return super().unlink()

    # ─── Workflow engine ─────────────────────────────────────────────

    def _dally_set_state(self, new_state, note=None):
        """Move to a state, refusing any transition the workflow does not allow.

        Every action method goes through here. Assigning ``state`` directly
        elsewhere would bypass the check, which is precisely how a request ends up
        `completed` with no offer behind it.
        """
        valid_states = dict(SOURCING_STATES)
        if new_state not in valid_states:
            raise UserError(_("Unknown status '%s'.", new_state))

        for request in self:
            current = request.state
            if current == new_state:
                # Not an error: re-running an action is harmless and common when two
                # operators work the same queue.
                continue

            allowed = ALLOWED_TRANSITIONS.get(current, ())
            if new_state not in allowed:
                raise UserError(
                    _(
                        "Cannot move request %(reference)s from “%(current)s” to "
                        "“%(target)s”. Allowed from here: %(allowed)s.",
                        reference=request.reference,
                        current=valid_states[current],
                        target=valid_states[new_state],
                        allowed=", ".join(
                            valid_states[state] for state in allowed
                        ) or _("nothing — this request is closed"),
                    )
                )

            values = {"state": new_state}
            if new_state == "on_hold":
                values["state_before_hold"] = current
            elif current == "on_hold":
                values["state_before_hold"] = False

            request.write(values)
            request.message_post(
                body=note
                or _(
                    "Status: %(current)s → %(target)s",
                    current=valid_states[current],
                    target=valid_states[new_state],
                )
            )
        return True

    # ─── Workflow actions ────────────────────────────────────────────
    #
    # Each is a named business step rather than a state assignment, so permissions,
    # notifications and validations can be added later without touching call sites.

    def action_qualify(self):
        """Accept the request as workable."""
        for request in self:
            if not (request.product_name or "").strip():
                raise UserError(
                    _("Request %s has no product to source.", request.reference)
                )
        return self._dally_set_state("to_qualify")

    def action_start_research(self):
        return self._dally_set_state("researching")

    def action_mark_suppliers_identified(self):
        for request in self:
            if not request.supplier_ids:
                raise UserError(
                    _(
                        "Add at least one candidate supplier to request %s before "
                        "marking suppliers as identified.",
                        request.reference,
                    )
                )
        return self._dally_set_state("suppliers_identified")

    def action_mark_offers_received(self):
        for request in self:
            if not request.offer_ids:
                raise UserError(
                    _(
                        "Record at least one supplier offer on request %s first.",
                        request.reference,
                    )
                )
        return self._dally_set_state("offers_received")

    def action_start_comparison(self):
        return self._dally_set_state("comparing")

    def action_prepare_proposal(self):
        """Ready to compose the customer-facing proposal.

        Requires an offer to base it on: a proposal built on nothing is a number
        invented under pressure, and the customer will hold DallyTrading to it.
        """
        for request in self:
            if not request.offer_ids:
                raise UserError(
                    _(
                        "Request %s has no supplier offer to base a proposal on.",
                        request.reference,
                    )
                )
        return self._dally_set_state("proposal_ready")

    def action_send_proposal(self):
        """Send the proposal to the customer.

        Guarded on there being a proposal with an amount and a recipient. §10 is
        explicit that a proposal must not be sendable without sufficient commercial
        data, and this is where that is enforced.
        """
        for request in self:
            sendable = request.proposal_ids.filtered(
                lambda proposal: proposal.state in ("draft", "ready")
                and proposal.total_amount > 0
            )
            if not sendable:
                raise UserError(
                    _(
                        "Request %s has no proposal ready to send. Create a "
                        "proposal with a total amount first.",
                        request.reference,
                    )
                )
            if not request.customer_id and not (request.contact_email or "").strip():
                raise UserError(
                    _(
                        "Request %s has no customer or email address to send the "
                        "proposal to.",
                        request.reference,
                    )
                )
        return self._dally_set_state("proposal_sent")

    def action_start_negotiation(self):
        return self._dally_set_state("negotiating")

    def action_accept(self):
        """The customer accepted."""
        return self._dally_set_state("accepted")

    def action_reject(self):
        return self._dally_set_state("rejected")

    def action_put_on_hold(self):
        for request in self:
            if request.state not in HOLDABLE_STATES:
                raise UserError(
                    _(
                        "Request %(reference)s cannot be put on hold from “%(state)s”.",
                        reference=request.reference,
                        state=dict(SOURCING_STATES)[request.state],
                    )
                )
        return self._dally_set_state("on_hold")

    def action_resume(self):
        """Return to the state work stopped in."""
        for request in self:
            if request.state != "on_hold":
                raise UserError(
                    _("Request %s is not on hold.", request.reference)
                )
            target = request.state_before_hold or "to_qualify"
            request._dally_set_state(target)
        return True

    def action_start_purchasing(self):
        return self._dally_set_state("purchasing")

    def action_start_execution(self):
        return self._dally_set_state("in_progress")

    def action_complete(self):
        return self._dally_set_state("completed")

    def action_cancel(self):
        return self._dally_set_state("cancelled")

    def action_reopen(self):
        """Bring a closed request back into the pipeline.

        The explicit business action §10 requires: a cancelled request cannot drift
        back into purchasing on its own, but a human may decide to restart it.
        """
        for request in self:
            if request.state not in TERMINAL_STATES:
                raise UserError(
                    _("Request %s is not closed.", request.reference)
                )
            request.write({"state": "to_qualify", "state_before_hold": False})
            request.message_post(body=_("Request reopened for qualification."))
        return True

    # ─── CRM ─────────────────────────────────────────────────────────

    def action_create_crm_opportunity(self):
        """Create the CRM opportunity, once.

        Idempotent: an existing opportunity is returned rather than duplicated.
        Not called on intake — §20 is explicit that not every raw internet request
        deserves a pipeline entry.
        """
        self.ensure_one()
        if self.crm_lead_id:
            return self.crm_lead_id

        subject_parts = [_("Sourcing"), self.product_name or _("Request")]
        if self.company_name:
            subject_parts.append(self.company_name)
        elif self.contact_name:
            subject_parts.append(self.contact_name)

        values = {
            "name": " — ".join(part for part in subject_parts if part),
            "type": "opportunity",
            "contact_name": self.contact_name or False,
            "partner_name": self.company_name or False,
            "email_from": self.contact_email or False,
            "phone": self.contact_phone or False,
            "partner_id": self.customer_id.id or False,
            "description": self._dally_lead_description(),
            "dally_reference": self.reference,
            "dally_request_uuid": self.request_uuid or False,
            "dally_source_url": self.source_url or False,
        }
        if self.service_id:
            values["dally_service_type_id"] = self.service_id.id
        if self.contact_whatsapp:
            values["dally_whatsapp"] = self.contact_whatsapp
        if self.utm_source_id:
            values["source_id"] = self.utm_source_id.id
        if self.utm_medium_id:
            values["medium_id"] = self.utm_medium_id.id
        if self.utm_campaign_id:
            values["campaign_id"] = self.utm_campaign_id.id
        if self.responsible_id:
            values["user_id"] = self.responsible_id.id
        if self.team_id:
            values["team_id"] = self.team_id.id

        lead = self.env["crm.lead"].create(values)
        self.crm_lead_id = lead
        self.message_post(
            body=_("CRM opportunity created: %s", lead.name)
        )
        return lead

    def _dally_lead_description(self):
        """Readable summary for the opportunity body.

        Only the sections that carry a value appear: an empty "Budget" heading is
        noise a salesperson has to read past.
        """
        self.ensure_one()
        lines = [_("Sourcing request %s", self.reference)]
        if self.product_name:
            lines.append(_("Product: %s", self.product_name))
        if self.quantity:
            unit = self.uom_id.name or ""
            lines.append(_("Quantity: %(qty)s %(unit)s", qty=self.quantity, unit=unit).strip())
        if self.target_total_budget:
            lines.append(_(
                "Budget: %(amount)s %(currency)s",
                amount=self.target_total_budget,
                currency=self.currency_id.name or "",
            ))
        if self.preferred_origin_country_id:
            lines.append(_("Preferred origin: %s", self.preferred_origin_country_id.name))
        if self.destination_country_id:
            lines.append(_("Destination: %s", self.destination_country_id.name))
        if self.required_delivery_date:
            lines.append(_("Required delivery: %s", self.required_delivery_date))
        if self.specifications:
            lines.append(_("Specifications: %s", self.specifications))
        if self.customer_notes:
            lines.append(_("Customer notes: %s", self.customer_notes))
        return "\n".join(lines)

    def action_create_customer(self):
        """Create the res.partner for this request, during qualification.

        Deliberately manual, and reusing the deduplication helper from dally_crm
        rather than reimplementing it: two competing anti-duplicate rules would
        eventually disagree, and the CRM would fill with the difference.
        """
        for request in self:
            if request.customer_id:
                continue

            existing = self.env["res.partner"]._dally_find_existing(
                email=request.contact_email or None,
                phone=request.contact_phone or None,
                whatsapp=request.contact_whatsapp or None,
                company_name=request.company_name or None,
            )
            if existing:
                request.customer_id = existing
                request.message_post(
                    body=_("Linked to existing contact: %s", existing.display_name)
                )
                continue

            if not request.contact_name and not request.company_name:
                raise UserError(
                    _(
                        "Request %s has no name to create a contact from.",
                        request.reference,
                    )
                )

            partner = self.env["res.partner"].create({
                "name": request.company_name or request.contact_name,
                "is_company": bool(
                    request.company_name and not request.contact_name
                ),
                "email": request.contact_email or False,
                "phone": request.contact_phone or False,
                "dally_whatsapp": request.contact_whatsapp or False,
                "country_id": request.destination_country_id.id or False,
            })
            request.customer_id = partner
            request.message_post(body=_("Contact created: %s", partner.display_name))

            if request.crm_lead_id and not request.crm_lead_id.partner_id:
                request.crm_lead_id.partner_id = partner
        return True

    # ─── Intake ──────────────────────────────────────────────────────

    @api.model
    def dally_create_from_website(self, payload):
        """Create a request from a validated public payload, idempotently.

        Returns the request, whether created now or by an earlier identical
        submission, so the caller always gets a usable record.

        Creates **only** the request. No partner, no opportunity, no purchase
        order, no shipment: each of those is a human decision taken later.
        """
        request_uuid = (payload.get("request_uuid") or "").strip()
        if request_uuid:
            # active_test=False is essential, not defensive. A request archived
            # during triage is invisible to a plain search, so a replay would fall
            # through to create(), hit the UNIQUE constraint and surface as a 500
            # instead of returning the original reference. This is the same bug that
            # was found and fixed on quote requests.
            existing = self.with_context(active_test=False).search(
                [("request_uuid", "=", request_uuid)], limit=1
            )
            if existing:
                return existing

        values = self._dally_prepare_values(payload)
        request = self.create(values)
        request._dally_log_intake(payload)
        return request

    @api.model
    def _dally_prepare_values(self, payload):
        """Map a validated payload onto field values.

        In the model rather than the controller, so the mapping is testable without
        HTTP and reusable by any other channel without duplicating business rules.
        """
        service = self.env["dally.service.type"]._get_by_code(
            payload.get("service_code")
        )
        if payload.get("service_code") and not service:
            raise UserError(
                _("Unknown service code '%s'.", payload["service_code"])
            )

        Country = self.env["res.country"]

        def country(code):
            cleaned = (code or "").strip().upper()
            if not cleaned:
                return False
            return Country.search([("code", "=", cleaned)], limit=1).id or False

        def text(key, limit=None):
            raw = payload.get(key)
            value = raw.strip() if isinstance(raw, str) else ("" if raw is None else str(raw))
            if limit and len(value) > limit:
                value = value[:limit]
            return value or False

        def number(key, default=0.0):
            raw = payload.get(key)
            if raw in (None, "", False):
                return default
            try:
                return float(raw)
            except (TypeError, ValueError):
                return default

        currency = self.env["res.currency"]
        currency_code = (payload.get("currency") or "").strip().upper()
        if currency_code:
            currency = currency.with_context(active_test=False).search(
                [("name", "=", currency_code)], limit=1
            )
        if not currency:
            currency = self.env.company.currency_id

        uom = self.env["uom.uom"]
        uom_name = (payload.get("uom") or "").strip()
        if uom_name:
            uom = uom.search([("name", "=ilike", uom_name)], limit=1)

        contact_name = " ".join(
            part for part in (payload.get("first_name"), payload.get("last_name"))
            if part
        ).strip() or text("customer_name")

        # Match an existing contact but do not create or edit one.
        partner = self.env["res.partner"]._dally_find_existing(
            email=text("email") or None,
            phone=text("phone") or None,
            whatsapp=text("whatsapp") or None,
            company_name=text("company_name") or None,
        )

        values = {
            "request_uuid": text("request_uuid", 64),
            "service_id": service.id or False,
            "contact_name": contact_name or False,
            "company_name": text("company_name", 200),
            "contact_email": text("email", 254),
            "contact_phone": text("phone", 40),
            "contact_whatsapp": text("whatsapp", 40),
            "customer_id": partner.id or False,
            "product_name": text("product_name", TEXT_LIMITS["product_name"]) or _("Unspecified product"),
            "product_description": text("product_description", TEXT_LIMITS["product_description"]),
            "specifications": text("specifications", TEXT_LIMITS["specifications"]),
            "product_reference": text("product_reference", 100),
            "product_url": text("product_url", 500),
            "quantity": number("quantity", 1.0) or 1.0,
            "currency_id": currency.id,
            "target_unit_price": number("target_unit_price"),
            "target_total_budget": number("budget"),
            "preferred_origin_country_id": country(payload.get("preferred_origin_country")),
            "destination_country_id": country(payload.get("destination_country")),
            "customer_notes": text("notes", TEXT_LIMITS["customer_notes"]),
            "source": text("source") or "Website / Sourcing",
            "source_url": text("source_url", 500),
            "referrer_url": text("referrer_url", 500),
        }

        if uom:
            values["uom_id"] = uom.id

        for key, target in (
            ("requested_deadline", "requested_deadline"),
            ("required_delivery_date", "required_delivery_date"),
        ):
            raw = (payload.get(key) or "").strip() if isinstance(payload.get(key), str) else None
            if raw:
                values[target] = raw

        values.update(self._dally_resolve_utm(payload.get("utm") or {}))
        return values

    @api.model
    def _dally_resolve_utm(self, utm):
        """Resolve UTM strings to records, creating them when new.

        Odoo's utm models are effectively a controlled vocabulary that grows: a
        campaign nobody registered still needs to be attributable, and refusing it
        would silently discard the attribution.
        """
        if not isinstance(utm, dict):
            return {}

        values = {}
        for key, model, field in (
            ("source", "utm.source", "utm_source_id"),
            ("medium", "utm.medium", "utm_medium_id"),
            ("campaign", "utm.campaign", "utm_campaign_id"),
        ):
            name = (utm.get(key) or "").strip()
            if not name or len(name) > 100:
                continue
            record = self.env[model].search([("name", "=ilike", name)], limit=1)
            if not record:
                record = self.env[model].create({"name": name})
            values[field] = record.id
        return values

    def _dally_log_intake(self, payload):
        """Record how the request arrived, in the chatter (§57)."""
        self.ensure_one()
        lines = [_("Sourcing request received.")]
        if self.source:
            lines.append(_("Source: %s", self.source))
        if payload.get("source_url"):
            lines.append(_("Page: %s", payload["source_url"]))
        if payload.get("referrer_url"):
            lines.append(_("Referrer: %s", payload["referrer_url"]))
        utm = payload.get("utm") or {}
        if isinstance(utm, dict) and any(utm.values()):
            lines.append(_(
                "UTM: %s",
                " / ".join(
                    str(utm.get(key) or "—")
                    for key in ("source", "medium", "campaign")
                ),
            ))
        if self.customer_id:
            lines.append(_(
                "Matched to existing contact: %s", self.customer_id.display_name,
            ))
        else:
            lines.append(_("No existing contact matched."))
        self.message_post(body="<br/>".join(lines))

    # ─── Public projection ───────────────────────────────────────────

    def _dally_public_payload(self):
        """What a customer may be told about their own request.

        An explicit allowlist. Nothing about suppliers, offers, internal costs,
        scores or notes appears — and cannot start appearing when a field is added,
        because every key here is named.
        """
        self.ensure_one()
        state_labels = dict(self._fields["state"]._description_selection(self.env))
        return {
            "reference": self.reference,
            "status": self.state,
            "statusLabel": state_labels.get(self.state, self.state),
            "productName": self.product_name or None,
            "quantity": self.quantity,
            "unit": self.uom_id.name or None,
            "requestedDeadline": (
                self.requested_deadline.isoformat() if self.requested_deadline else None
            ),
            "createdOn": self.create_date.date().isoformat() if self.create_date else None,
        }

    # ─── Conversions ─────────────────────────────────────────────────

    def action_create_purchase_order(self):
        """Create the purchase order from the selected offer.

        Never automatic, and never empty. §22 lists the conditions; they are all
        enforced here, and the order is created **with its line** in one call.

        An order with no line is worse than no order: it can be confirmed, it appears
        in reporting, and nobody can tell what was supposed to be bought. So every
        piece the line needs is checked first, and the conversion is refused with an
        explicit message when something is missing.
        """
        self.ensure_one()

        if self.state not in ("accepted", "purchasing"):
            raise UserError(
                _(
                    "Request %s must be accepted before a purchase order can be "
                    "raised.",
                    self.reference,
                )
            )

        if self.purchase_order_ids:
            # Idempotent by intent: re-running the action opens what exists rather
            # than raising a second order against the same supplier.
            return self._dally_open_records(
                "purchase.order", self.purchase_order_ids.ids, _("Purchase Orders"),
            )

        offer = self.selected_offer_id
        if not offer:
            raise UserError(
                _("Select a supplier offer on request %s first.", self.reference)
            )

        # Everything the line needs, checked before anything is created.
        missing = []
        if not offer.partner_id:
            missing.append(_("a supplier contact on the selected offer"))
        if not self.product_id:
            missing.append(_("a catalogue product on the request"))
        if offer.quantity <= 0:
            missing.append(_("a quantity greater than zero on the offer"))
        if offer.unit_price <= 0:
            missing.append(_("a purchase unit price on the offer"))
        if not offer.currency_id:
            missing.append(_("a currency on the offer"))
        if not self.company_id:
            missing.append(_("a company on the request"))

        if missing:
            raise UserError(
                _(
                    "Request %(reference)s cannot produce a usable purchase order. "
                    "Missing: %(missing)s.\n\n"
                    "An order with no usable line can be confirmed and reported on "
                    "while nobody can tell what was meant to be bought, so it is not "
                    "created at all.",
                    reference=self.reference,
                    missing=", ".join(missing),
                )
            )

        description = self._dally_order_line_description()

        # Created with the line in one call. The unit of measure is deliberately left
        # to Odoo, which derives it from the product: that is its own source of truth,
        # and forcing a value here could contradict the product's purchase UoM.
        order = self.env["purchase.order"].create({
            "partner_id": offer.partner_id.id,
            "currency_id": offer.currency_id.id,
            "company_id": self.company_id.id,
            "origin": self.reference,
            "dally_sourcing_request_id": self.id,
            "order_line": [(0, 0, {
                "product_id": self.product_id.id,
                "name": description,
                "product_qty": offer.quantity,
                "price_unit": offer.unit_price,
            })],
        })

        self.message_post(
            body=_(
                "Purchase order %(order)s created from the selected offer: "
                "%(quantity)s × %(price)s %(currency)s.",
                order=order.name,
                quantity=offer.quantity,
                price=offer.unit_price,
                currency=offer.currency_id.name,
            )
        )
        if self.state == "accepted":
            self._dally_set_state("purchasing")

        return self._dally_open_records(
            "purchase.order", order.ids, _("Purchase Order"),
        )

    def action_create_sale_order(self):
        """Create the sales order from the accepted proposal.

        The proposal is what the customer agreed to, so it is the only legitimate
        basis — and it carries a validated price, which is what makes the line
        invoiceable rather than a guess.

        As on the purchase side, the order is created **with its line** or not at all.
        A sales order carrying a zero-priced line can be confirmed and invoiced, and
        the customer receives an invoice for nothing.
        """
        self.ensure_one()

        if self.state not in ("accepted", "purchasing", "in_progress"):
            raise UserError(
                _(
                    "Request %s must be accepted before a sales order can be raised.",
                    self.reference,
                )
            )

        if self.sale_order_ids:
            return self._dally_open_records(
                "sale.order", self.sale_order_ids.ids, _("Sales Orders"),
            )

        accepted = self.proposal_ids.filtered(
            lambda proposal: proposal.state == "accepted"
        )
        if not accepted:
            raise UserError(
                _(
                    "Request %s has no accepted proposal to invoice against.",
                    self.reference,
                )
            )
        proposal = accepted[0]

        missing = []
        if not self.customer_id:
            missing.append(_("a customer on the request"))
        if not self.product_id:
            missing.append(_("a catalogue product on the request"))
        if proposal.quantity <= 0:
            missing.append(_("a quantity greater than zero on the proposal"))
        if proposal.selling_unit_price <= 0:
            missing.append(_("a selling unit price on the proposal"))
        if not proposal.currency_id:
            missing.append(_("a currency on the proposal"))
        if not self.company_id:
            missing.append(_("a company on the request"))

        if missing:
            raise UserError(
                _(
                    "Request %(reference)s cannot produce a usable sales order. "
                    "Missing: %(missing)s.\n\n"
                    "A sales order with a zero-priced line can be confirmed and "
                    "invoiced, so the customer would receive an invoice for nothing. "
                    "It is therefore not created at all.",
                    reference=self.reference,
                    missing=", ".join(missing),
                )
            )

        lines = [(0, 0, {
            "product_id": self.product_id.id,
            "name": self._dally_order_line_description(),
            "product_uom_qty": proposal.quantity,
            "price_unit": proposal.selling_unit_price,
        })]

        # The service fee is a distinct line, not folded into the unit price: the
        # customer sees what they are paying for, and it can be taxed differently.
        if proposal.service_fee > 0:
            service_product = self._dally_service_fee_product()
            if service_product:
                lines.append((0, 0, {
                    "product_id": service_product.id,
                    "name": _("Sourcing service fee — %s", self.reference),
                    "product_uom_qty": 1.0,
                    "price_unit": proposal.service_fee,
                }))

        order = self.env["sale.order"].create({
            "partner_id": self.customer_id.id,
            "currency_id": proposal.currency_id.id,
            "company_id": self.company_id.id,
            "origin": self.reference,
            "dally_sourcing_request_id": self.id,
            "opportunity_id": self.crm_lead_id.id or False,
            "order_line": lines,
        })
        proposal.sale_order_id = order

        self.message_post(
            body=_(
                "Sales order %(order)s created from proposal %(proposal)s: "
                "%(quantity)s × %(price)s %(currency)s.",
                order=order.name,
                proposal=proposal.reference,
                quantity=proposal.quantity,
                price=proposal.selling_unit_price,
                currency=proposal.currency_id.name,
            )
        )
        return self._dally_open_records("sale.order", order.ids, _("Sales Order"))

    def _dally_order_line_description(self):
        """Line description: the product, plus what the customer actually asked for.

        The product name alone loses the specification, which is often the whole point
        of a sourcing request — "solar panels" and "monocrystalline 400W, 10-year
        warranty" are not the same purchase.
        """
        self.ensure_one()
        parts = [self.product_name or self.product_id.display_name or _("Product")]
        if self.product_reference:
            parts.append(_("Ref. %s", self.product_reference))
        if self.specifications:
            specification = " ".join(self.specifications.split())
            if len(specification) > 300:
                specification = specification[:300] + "…"
            parts.append(specification)
        return "\n".join(parts)

    @api.model
    def _dally_service_fee_product(self):
        """The service product used for a sourcing fee line, if configured.

        Read from a system parameter rather than created on the fly: silently adding a
        product to the catalogue is how a catalogue becomes unusable. When it is not
        configured the fee is simply not broken out, and the operator adds the line —
        which is visible, rather than a surprise.
        """
        reference = self.env["ir.config_parameter"].sudo().get_param(
            "dally_sourcing.service_fee_product_ref"
        )
        if not reference:
            return self.env["product.product"]
        product = self.env.ref(reference, raise_if_not_found=False)
        if product and product._name == "product.product":
            return product
        return self.env["product.product"]

    def _dally_open_records(self, model, ids, name):
        """Open one record in a form, or several in a list."""
        if len(ids) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": model,
                "res_id": ids[0],
                "view_mode": "form",
            }
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": model,
            "view_mode": "list,form",
            "domain": [("id", "in", ids)],
        }

    # ─── Navigation ──────────────────────────────────────────────────

    def action_view_suppliers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Candidate Suppliers"),
            "res_model": "dally.sourcing.supplier",
            "view_mode": "list,form",
            "domain": [("request_id", "=", self.id)],
            "context": {"default_request_id": self.id},
        }

    def action_view_offers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Supplier Offers"),
            "res_model": "dally.sourcing.offer",
            "view_mode": "list,form",
            "domain": [("request_id", "=", self.id)],
            "context": {"default_request_id": self.id},
        }

    def action_view_proposals(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Customer Proposals"),
            "res_model": "dally.sourcing.proposal",
            "view_mode": "list,form",
            "domain": [("request_id", "=", self.id)],
            "context": {"default_request_id": self.id},
        }
