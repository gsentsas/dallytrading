# -*- coding: utf-8 -*-
"""Customer proposals — what DallyTrading offers, not what a supplier quoted.

## The whole point of this model

A supplier offer and a customer proposal are different documents with different
readers. Sending the first to the second's reader would disclose purchase prices,
supplier identities and margin.

So the proposal is composed, not copied. It carries a selling price, a shipping
estimate, a service fee and terms — figures DallyTrading stands behind. The offer it
was derived from is linked for internal traceability, and that link is restricted.

## The margin fields

``cost_basis`` and ``margin`` exist because a manager must be able to see whether a
proposal is profitable before sending it. They carry ``groups=``, so the ORM removes
them for anyone outside sourcing management and finance — and they are absent from
every public payload. A commercial user can present a proposal without learning what
it cost.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PROPOSAL_STATES = [
    ("draft", "Draft"),
    ("ready", "Ready"),
    ("sent", "Sent"),
    ("accepted", "Accepted"),
    ("rejected", "Rejected"),
    ("expired", "Expired"),
    ("cancelled", "Cancelled"),
]

#: Transitions allowed on a proposal, declared as data so the whole lifecycle is
#: readable in one place and assertable by a test.
PROPOSAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("ready", "cancelled"),
    "ready": ("sent", "draft", "cancelled"),
    "sent": ("accepted", "rejected", "expired", "cancelled"),
    "accepted": ("cancelled",),
    "rejected": ("draft", "cancelled"),
    "expired": ("draft", "cancelled"),
    "cancelled": (),
}

#: There is deliberately NO default margin rate.
#:
#: A hidden Python constant is not a commercial policy. Applying an arbitrary uplift
#: automatically would mean DallyTrading quotes a price nobody decided, and the first
#: time it is wrong the customer holds the company to it. A proposal therefore starts
#: with **no selling price**, and the price must be entered and validated explicitly.
#:
#: If DallyTrading later wants a default, it belongs in configuration — administrable,
#: documented, and possibly per operation type — not here.


class DallySourcingProposal(models.Model):
    _name = "dally.sourcing.proposal"
    _description = "DallyTrading Sourcing Customer Proposal"
    _inherit = ["dally.reference.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    #: DT-SRP-YYYY-NNNNNN — its own series, because a proposal is a document the
    #: customer quotes back, distinct from the request that produced it.
    _dally_sequence_code = "dally.sourcing.proposal"

    request_id = fields.Many2one(
        comodel_name="dally.sourcing.request",
        string="Sourcing Request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="request_id.company_id", store=True, index=True, readonly=True,
    )
    customer_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        index=True,
        tracking=True,
    )
    active = fields.Boolean(default=True)

    # ─── What is offered ─────────────────────────────────────────────
    product_name = fields.Char(string="Product", required=True)
    product_description = fields.Text(string="Description")

    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    quantity = fields.Float(string="Quantity", digits=(16, 3), required=True, default=1.0)
    uom_id = fields.Many2one(comodel_name="uom.uom", string="Unit of Measure")

    selling_unit_price = fields.Monetary(
        string="Unit Price", currency_field="currency_id", required=True, tracking=True,
    )
    subtotal = fields.Monetary(
        string="Subtotal", currency_field="currency_id",
        compute="_compute_amounts", store=True,
    )
    estimated_shipping = fields.Monetary(
        string="Estimated Shipping", currency_field="currency_id",
    )
    service_fee = fields.Monetary(
        string="Service Fee", currency_field="currency_id",
        help="DallyTrading's fee for the sourcing work, shown to the customer as a "
             "line of its own rather than hidden inside the unit price.",
    )
    other_customer_charges = fields.Monetary(
        string="Other Charges", currency_field="currency_id",
    )
    tax_amount = fields.Monetary(string="Tax", currency_field="currency_id")
    total_amount = fields.Monetary(
        string="Total", currency_field="currency_id",
        compute="_compute_amounts", store=True, tracking=True,
    )

    estimated_delivery = fields.Date(string="Estimated Delivery")
    validity_date = fields.Date(
        string="Valid Until",
        help="After this date the proposal must be reconfirmed: supplier prices and "
             "freight rates move.",
    )
    is_expired = fields.Boolean(string="Expired", compute="_compute_is_expired")

    commercial_terms = fields.Text(
        string="Commercial Terms",
        help="Payment terms, delivery conditions, what is and is not included. Shown "
             "to the customer verbatim.",
    )

    state = fields.Selection(
        selection=PROPOSAL_STATES,
        string="Status",
        default="draft",
        required=True,
        index=True,
        tracking=True,
        copy=False,
    )

    # ─── Explicit price validation ───────────────────────────────────
    #
    # A proposal cannot become `ready` or `sent` until someone has looked at the
    # commercial price and said so. Without this, a draft created from an offer could
    # travel to a customer carrying a price that was computed rather than decided.
    # Deliberately NOT restricted by ``groups=``, unlike cost_basis and margin.
    #
    # Whether a price has been approved is workflow information, not commercial
    # confidentiality — a sourcing user needs to read it to understand why the
    # proposal will not send, and the ORM would otherwise raise an access error on
    # a field they must be able to see. The restriction that matters is *who may set
    # it*, enforced in ``action_validate_price`` below rather than by a field group.
        # Restreint au personnel interne. Un utilisateur portail lit ses propres
        # dossiers ; ce champ, lui, expose l'état d'approbation interne du prix et
        # ne doit jamais lui être chargé par l'ORM, même sur un record qui lui
        # appartient.
    price_validated = fields.Boolean(
        string="Price Validated",
        copy=False,
        tracking=True,
        readonly=True,
        help="Required before the proposal can be marked ready or sent. Set by a "
             "sourcing manager or finance through the Validate Price action: it "
             "records that a human decided this price, rather than a formula "
             "producing it.",
        groups="dally_core.group_dally_readonly",
    )
        # Restreint au personnel interne. Un utilisateur portail lit ses propres
        # dossiers ; ce champ, lui, expose l'identité de l'approbateur et ne doit
        # jamais lui être chargé par l'ORM, même sur un record qui lui appartient.
    price_validated_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Price Validated By",
        readonly=True,
        copy=False,
        groups="dally_core.group_dally_readonly",
    )
        # Restreint au personnel interne. Un utilisateur portail lit ses propres
        # dossiers ; ce champ, lui, expose la chronologie d'approbation interne et
        # ne doit jamais lui être chargé par l'ORM, même sur un record qui lui
        # appartient.
    price_validated_on = fields.Datetime(
        string="Price Validated On",
        readonly=True,
        copy=False,
        groups="dally_core.group_dally_readonly",
    )
    sent_date = fields.Datetime(string="Sent On", readonly=True, copy=False)
    decision_date = fields.Datetime(string="Decided On", readonly=True, copy=False)

    sale_order_id = fields.Many2one(
        comodel_name="sale.order", string="Sales Order", copy=False, index=True,
    )

    # ─── Internal: restricted at ORM level ───────────────────────────
    source_offer_id = fields.Many2one(
        comodel_name="dally.sourcing.offer",
        string="Source Offer",
        copy=False,
        groups="dally_core.group_dally_sourcing",
        help="The supplier offer this proposal was derived from. Restricted: which "
             "supplier was chosen is commercial information.",
    )
    cost_basis = fields.Monetary(
        string="Cost Basis",
        currency_field="currency_id",
        groups="dally_sourcing.group_dally_sourcing_manager,dally_core.group_dally_finance",
        help="Landed cost this proposal was built on. Never exposed publicly.",
    )
    margin = fields.Monetary(
        string="Margin",
        currency_field="currency_id",
        compute="_compute_margin",
        store=True,
        groups="dally_sourcing.group_dally_sourcing_manager,dally_core.group_dally_finance",
    )
    margin_rate = fields.Float(
        string="Margin %",
        digits=(5, 2),
        compute="_compute_margin",
        store=True,
        groups="dally_sourcing.group_dally_sourcing_manager,dally_core.group_dally_finance",
    )
    internal_notes = fields.Text(
        string="Internal Notes",
        groups="dally_core.group_dally_readonly",
    )

    _dally_sourcing_proposal_quantity_positive = models.Constraint(
        'CHECK(quantity > 0)',
        'The quantity must be greater than zero.',
    )
    _dally_sourcing_proposal_price_positive = models.Constraint(
        'CHECK(selling_unit_price >= 0)',
        'The unit price cannot be negative.',
    )
    _dally_sourcing_proposal_charges_positive = models.Constraint(
        'CHECK(estimated_shipping >= 0 AND service_fee >= 0 AND other_customer_charges >= 0 AND tax_amount >= 0)',
        'Charges cannot be negative.',
    )

    # ─── Computes ────────────────────────────────────────────────────

    @api.depends("quantity", "selling_unit_price", "estimated_shipping",
                 "service_fee", "other_customer_charges", "tax_amount")
    def _compute_amounts(self):
        for proposal in self:
            proposal.subtotal = proposal.quantity * proposal.selling_unit_price
            proposal.total_amount = (
                proposal.subtotal
                + proposal.estimated_shipping
                + proposal.service_fee
                + proposal.other_customer_charges
                + proposal.tax_amount
            )

    @api.depends("total_amount", "tax_amount", "cost_basis")
    def _compute_margin(self):
        for proposal in self:
            # Tax is excluded: it is collected, not earned. Including it would
            # overstate every margin by the VAT rate.
            revenue = proposal.total_amount - proposal.tax_amount
            proposal.margin = revenue - proposal.cost_basis
            proposal.margin_rate = (
                (proposal.margin / revenue) * 100 if revenue else 0.0
            )

    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for proposal in self:
            proposal.is_expired = bool(
                proposal.validity_date
                and proposal.validity_date < today
                and proposal.state in ("ready", "sent")
            )

    def write(self, vals):
        """Editing the commercial price withdraws its validation.

        Otherwise a proposal validated at one price could be sent at another — the
        approval would attach to a number nobody approved.
        """
        price_fields = {
            "selling_unit_price", "quantity", "estimated_shipping", "service_fee",
            "other_customer_charges", "tax_amount", "currency_id",
        }
        if price_fields & set(vals) and "price_validated" not in vals:
            changing = self.filtered(
                lambda proposal: proposal.price_validated
                and proposal.state in ("draft", "ready")
            )
            if changing:
                super(DallySourcingProposal, changing).write({
                    "price_validated": False,
                    "price_validated_by_id": False,
                    "price_validated_on": False,
                })
                for proposal in changing:
                    proposal.message_post(
                        body=_("Price changed — validation withdrawn, revalidate before sending.")
                    )
        return super().write(vals)

    # ─── Constraints ─────────────────────────────────────────────────

    @api.constrains("validity_date", "estimated_delivery")
    def _check_dates(self):
        for proposal in self:
            if (
                proposal.validity_date
                and proposal.estimated_delivery
                and proposal.estimated_delivery < proposal.validity_date
            ):
                # Not fatal in reality, but almost always a data-entry slip: a
                # delivery date before the quote even expires.
                raise ValidationError(
                    _(
                        "The estimated delivery date is earlier than the validity "
                        "date. Check the dates on proposal %s.",
                        proposal.reference,
                    )
                )

    @api.constrains("source_offer_id", "request_id")
    def _check_offer_belongs_to_request(self):
        for proposal in self:
            if (
                proposal.source_offer_id
                and proposal.source_offer_id.request_id != proposal.request_id
            ):
                raise ValidationError(
                    _("The source offer belongs to a different sourcing request.")
                )

    # ─── Drafting from an offer ──────────────────────────────────────

    @api.model
    def _dally_draft_from_offer(self, offer):
        """Draft a proposal from a supplier offer.

        The one bridge across the confidentiality boundary. Note what is **not**
        copied: unit cost, shipping cost, insurance, customs estimate, scores,
        supplier notes, supplier identity. No selling price is derived either: the
        draft carries none, and a manager must set and validate one. The only figure
        that crosses is the cost basis — itself group-restricted — so that whoever
        sets the price can see what it has to cover.
        """
        offer.ensure_one()
        request = offer.request_id

        proposal = self.create({
            "request_id": request.id,
            "customer_id": request.customer_id.id or False,
            "product_name": request.product_name or offer.reference or _("Product"),
            "product_description": request.product_description or False,
            # The offer's currency, so the derived price is not silently converted at
            # an unstated rate. Changing currency is a deliberate edit.
            "currency_id": offer.currency_id.id,
            "quantity": offer.quantity,
            "uom_id": offer.uom_id.id or request.uom_id.id or False,
            # No selling price. It is a commercial decision, and a computed one would
            # be quoted by accident. The cost basis is carried so the manager setting
            # the price can see what it has to cover.
            "selling_unit_price": 0.0,
            "cost_basis": offer.total_landed_cost,
            "source_offer_id": offer.id,
            "estimated_delivery": False,
            "state": "draft",
        })

        request.message_post(
            body=_(
                "Proposal %(reference)s drafted from the selected offer, with no "
                "selling price. Landed cost to cover: %(cost)s %(currency)s. Set the "
                "price, the service fee and the terms, then validate the price.",
                reference=proposal.reference,
                cost=round(offer.total_landed_cost, 2),
                currency=offer.currency_id.name,
            )
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": proposal.id,
            "view_mode": "form",
        }

    # ─── Workflow ────────────────────────────────────────────────────

    def _dally_set_state(self, new_state):
        """Move to a state, refusing transitions the lifecycle does not allow."""
        labels = dict(PROPOSAL_STATES)
        if new_state not in labels:
            raise UserError(_("Unknown status '%s'.", new_state))

        for proposal in self:
            if proposal.state == new_state:
                continue
            allowed = PROPOSAL_TRANSITIONS.get(proposal.state, ())
            if new_state not in allowed:
                raise UserError(
                    _(
                        "Cannot move proposal %(reference)s from “%(current)s” to "
                        "“%(target)s”. Allowed from here: %(allowed)s.",
                        reference=proposal.reference,
                        current=labels[proposal.state],
                        target=labels[new_state],
                        allowed=", ".join(labels[state] for state in allowed)
                        or _("nothing — this proposal is closed"),
                    )
                )
            proposal.state = new_state
        return True

    def action_mark_ready(self):
        """Mark as ready to send, checking it says something.

        A proposal with no price is not a proposal, and §10 requires that one cannot
        be sent without sufficient commercial data. This is where that begins.
        """
        for proposal in self:
            if proposal.total_amount <= 0:
                raise UserError(
                    _(
                        "Proposal %s has no amount. Set a unit price before marking "
                        "it ready.",
                        proposal.reference,
                    )
                )
            if not proposal.validity_date:
                raise UserError(
                    _(
                        "Proposal %s has no validity date. Supplier prices and "
                        "freight rates move, so a quote without an expiry commits "
                        "DallyTrading indefinitely.",
                        proposal.reference,
                    )
                )
            if not proposal.price_validated:
                raise UserError(
                    _(
                        "The price on proposal %s has not been validated. A sourcing "
                        "manager or finance must confirm it before it can be sent: a "
                        "price that was computed rather than decided is one the "
                        "customer will hold DallyTrading to.",
                        proposal.reference,
                    )
                )
        return self._dally_set_state("ready")

    #: Who may decide a commercial price. A user who cannot see the cost basis is not
    #: in a position to judge whether the price covers it.
    _dally_price_validation_groups = (
        "dally_sourcing.group_dally_sourcing_manager",
        "dally_core.group_dally_finance",
        "dally_core.group_dally_manager",
    )

    def _dally_check_price_validation_rights(self):
        """Refuse price validation to anyone who cannot see what the price must cover.

        Enforced here rather than by a field group: the field itself must stay
        readable, so that a sourcing user can see why a proposal will not send.
        """
        if any(self.env.user.has_group(group)
               for group in self._dally_price_validation_groups):
            return
        raise UserError(
            _(
                "Only sourcing management or finance can validate a commercial "
                "price. Judging whether a price covers its cost requires seeing the "
                "cost, which is restricted."
            )
        )

    def action_validate_price(self):
        """Record that a human decided this price."""
        self._dally_check_price_validation_rights()
        for proposal in self:
            if proposal.total_amount <= 0:
                raise UserError(
                    _(
                        "Proposal %s has no amount to validate. Set a unit price "
                        "first.",
                        proposal.reference,
                    )
                )
            proposal.write({
                "price_validated": True,
                "price_validated_by_id": self.env.user.id,
                "price_validated_on": fields.Datetime.now(),
            })
            proposal.message_post(
                body=_(
                    "Price validated: %(amount)s %(currency)s.",
                    amount=proposal.total_amount,
                    currency=proposal.currency_id.name,
                )
            )
        return True

    def action_revoke_price_validation(self):
        """Withdraw the validation, so an edited price must be re-approved."""
        self._dally_check_price_validation_rights()
        for proposal in self:
            proposal.write({
                "price_validated": False,
                "price_validated_by_id": False,
                "price_validated_on": False,
            })
            proposal.message_post(body=_("Price validation withdrawn."))
        return True

    def action_send(self):
        """Record that the proposal was sent.

        E-mail delivery is not wired yet (SMTP is an administrator task), so this
        records the fact rather than pretending to send. When the mail template is
        added, it hooks in here — no call site changes.
        """
        for proposal in self:
            if not proposal.customer_id and not proposal.request_id.contact_email:
                raise UserError(
                    _(
                        "Proposal %s has no customer or email address to send to.",
                        proposal.reference,
                    )
                )
        self._dally_set_state("sent")
        self.write({"sent_date": fields.Datetime.now()})
        for proposal in self:
            proposal.request_id.message_post(
                body=_("Proposal %s marked as sent.", proposal.reference)
            )
        return True

    def action_accept(self):
        self._dally_set_state("accepted")
        self.write({"decision_date": fields.Datetime.now()})
        for proposal in self:
            proposal.request_id.message_post(
                body=_(
                    "Proposal %(reference)s accepted by the customer: %(amount)s %(currency)s.",
                    reference=proposal.reference,
                    amount=proposal.total_amount,
                    currency=proposal.currency_id.name,
                )
            )
        return True

    def action_reject(self):
        self._dally_set_state("rejected")
        self.write({"decision_date": fields.Datetime.now()})
        return True

    def action_mark_expired(self):
        return self._dally_set_state("expired")

    def action_cancel(self):
        return self._dally_set_state("cancelled")

    def action_back_to_draft(self):
        return self._dally_set_state("draft")

    # ─── Public projection ───────────────────────────────────────────

    def _dally_public_payload(self):
        """What the customer may be shown about their proposal.

        An explicit allowlist. Absent by construction: cost basis, margin, source
        offer, supplier identity, internal notes, and any database id.
        """
        self.ensure_one()
        labels = dict(PROPOSAL_STATES)
        return {
            "reference": self.reference,
            "requestReference": self.request_id.reference,
            "status": self.state,
            "statusLabel": labels.get(self.state, self.state),
            "productName": self.product_name,
            "quantity": self.quantity,
            "unit": self.uom_id.name or None,
            "currency": self.currency_id.name,
            "unitPrice": self.selling_unit_price,
            "subtotal": self.subtotal,
            "estimatedShipping": self.estimated_shipping,
            "serviceFee": self.service_fee,
            "otherCharges": self.other_customer_charges,
            "tax": self.tax_amount,
            "total": self.total_amount,
            "estimatedDelivery": (
                self.estimated_delivery.isoformat() if self.estimated_delivery else None
            ),
            "validUntil": (
                self.validity_date.isoformat() if self.validity_date else None
            ),
            "commercialTerms": self.commercial_terms or None,
        }
