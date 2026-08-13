# -*- coding: utf-8 -*-
"""Supplier offers — internal, and never public.

## This model is the confidential side of sourcing

Everything here is what a supplier quoted DallyTrading: unit price, shipping,
insurance, customs estimate, scores, notes. None of it belongs to the customer. The
customer receives a ``dally.sourcing.proposal``, which DallyTrading composes from
these figures plus its own service and margin.

The separation is a **model boundary, not a filter**. There is no public endpoint for
this model, it is absent from every DTO, and access is restricted at ORM level to the
sourcing and finance groups — commercial staff and read-only users have none at all.
"Show the customer the offer" therefore cannot happen by mistake; it would require
writing a new endpoint on purpose.

## On the scores

Four criteria, each 0–5, and an average. Deliberately not an algorithm claiming to
identify the best supplier: the cheapest offer from an unverified factory with a
90-day lead time is not the best, and the weighting depends on the customer, the
season and the risk appetite of whoever is accountable. The scores structure the
comparison; a human makes the decision.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SCORE_SELECTION = [
    ("0", "Not rated"),
    ("1", "1 — Poor"),
    ("2", "2 — Weak"),
    ("3", "3 — Acceptable"),
    ("4", "4 — Good"),
    ("5", "5 — Excellent"),
]


class DallySourcingOffer(models.Model):
    _name = "dally.sourcing.offer"
    _description = "DallyTrading Sourcing Supplier Offer"
    _order = "request_id, total_landed_cost, id"
    _inherit = ["mail.thread"]

    request_id = fields.Many2one(
        comodel_name="dally.sourcing.request",
        string="Sourcing Request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    supplier_id = fields.Many2one(
        comodel_name="dally.sourcing.supplier",
        string="Candidate Supplier",
        required=True,
        ondelete="cascade",
        index=True,
        domain="[('request_id', '=', request_id)]",
    )
    partner_id = fields.Many2one(
        related="supplier_id.partner_id",
        string="Supplier",
        store=True,
        index=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        related="request_id.company_id", store=True, index=True, readonly=True,
    )

    reference = fields.Char(
        string="Supplier Quote Ref",
        help="The supplier's own quotation number, for correspondence.",
    )
    received_date = fields.Date(
        string="Received On", default=fields.Date.context_today,
    )

    # ─── Commercial terms ────────────────────────────────────────────
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
        help="The supplier's currency. Never assumed: offers on the same request "
             "routinely arrive in USD, EUR and CNY, and comparing them requires "
             "keeping each in its own.",
    )
    quantity = fields.Float(string="Quantity", digits=(16, 3), required=True, default=1.0)
    uom_id = fields.Many2one(comodel_name="uom.uom", string="Unit of Measure")

    unit_price = fields.Monetary(
        string="Unit Price", currency_field="currency_id", required=True,
    )
    subtotal = fields.Monetary(
        string="Goods Subtotal",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
    )

    shipping_cost = fields.Monetary(string="Shipping", currency_field="currency_id")
    insurance_cost = fields.Monetary(string="Insurance", currency_field="currency_id")
    customs_estimate = fields.Monetary(
        string="Customs (estimate)",
        currency_field="currency_id",
        help="An estimate, and labelled as one: duty depends on classification and "
             "declared value, which are not settled at quotation time.",
    )
    other_costs = fields.Monetary(string="Other Costs", currency_field="currency_id")

    total_landed_cost = fields.Monetary(
        string="Total Landed Cost",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        help="Goods plus shipping, insurance, customs estimate and other costs. "
             "This is the figure a proposal is built from — not the unit price, "
             "which is what makes a cheap quote look cheap.",
    )
    landed_unit_cost = fields.Monetary(
        string="Landed Unit Cost",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        help="Total landed cost divided by quantity. The only figure that compares "
             "two offers meaningfully.",
    )

    # ─── Logistics terms ─────────────────────────────────────────────
    lead_time_days = fields.Integer(string="Lead Time (days)")
    minimum_order_quantity = fields.Float(string="MOQ", digits=(16, 3))
    incoterm_id = fields.Many2one(
        comodel_name="account.incoterms",
        string="Incoterm",
        help="Native Odoo incoterm. Not a parallel hardcoded list: one source of "
             "truth, as for the service catalogue.",
    )
    validity_date = fields.Date(string="Valid Until")
    is_expired = fields.Boolean(
        string="Expired", compute="_compute_is_expired", search="_search_is_expired",
    )

    sample_available = fields.Boolean(string="Sample Available")
    sample_cost = fields.Monetary(string="Sample Cost", currency_field="currency_id")

    # ─── Assessment ──────────────────────────────────────────────────
    quality_score = fields.Selection(SCORE_SELECTION, string="Quality", default="0")
    price_score = fields.Selection(SCORE_SELECTION, string="Price", default="0")
    lead_time_score = fields.Selection(SCORE_SELECTION, string="Lead Time", default="0")
    reliability_score = fields.Selection(
        SCORE_SELECTION, string="Reliability", default="0",
    )
    overall_score = fields.Float(
        string="Overall",
        digits=(3, 2),
        compute="_compute_overall_score",
        store=True,
        help="Average of the criteria actually rated. A guide for the comparison, "
             "not a verdict: the decision stays human.",
    )

    selected = fields.Boolean(
        string="Selected",
        copy=False,
        help="The offer DallyTrading decided to buy on. Only one per request.",
    )

    internal_notes = fields.Text(
        string="Internal Notes",
        help="Negotiation context, doubts, anything learned about the supplier. "
             "Never leaves this model.",
    )

    _dally_sourcing_offer_quantity_positive = models.Constraint(
        'CHECK(quantity > 0)',
        'The offered quantity must be greater than zero.',
    )
    _dally_sourcing_offer_unit_price_positive = models.Constraint(
        'CHECK(unit_price >= 0)',
        'The unit price cannot be negative.',
    )
    _dally_sourcing_offer_costs_positive = models.Constraint(
        'CHECK(shipping_cost >= 0 AND insurance_cost >= 0 AND customs_estimate >= 0 AND other_costs >= 0 AND sample_cost >= 0)',
        'Costs cannot be negative.',
    )
    _dally_sourcing_offer_moq_positive = models.Constraint(
        'CHECK(minimum_order_quantity >= 0)',
        'The minimum order quantity cannot be negative.',
    )
    _dally_sourcing_offer_lead_time_positive = models.Constraint(
        'CHECK(lead_time_days >= 0)',
        'The lead time cannot be negative.',
    )

    # ─── Computes ────────────────────────────────────────────────────

    @api.depends("quantity", "unit_price", "shipping_cost", "insurance_cost",
                 "customs_estimate", "other_costs")
    def _compute_amounts(self):
        for offer in self:
            offer.subtotal = offer.quantity * offer.unit_price
            offer.total_landed_cost = (
                offer.subtotal
                + offer.shipping_cost
                + offer.insurance_cost
                + offer.customs_estimate
                + offer.other_costs
            )
            offer.landed_unit_cost = (
                offer.total_landed_cost / offer.quantity if offer.quantity else 0.0
            )

    @api.depends("quality_score", "price_score", "lead_time_score",
                 "reliability_score")
    def _compute_overall_score(self):
        for offer in self:
            rated = [
                int(value)
                for value in (
                    offer.quality_score, offer.price_score,
                    offer.lead_time_score, offer.reliability_score,
                )
                if value and value != "0"
            ]
            # Averaging only the rated criteria: counting an unrated one as zero
            # would make a partly assessed offer look worse than a bad one.
            offer.overall_score = sum(rated) / len(rated) if rated else 0.0

    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for offer in self:
            offer.is_expired = bool(
                offer.validity_date and offer.validity_date < today
            )

    def _search_is_expired(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(_("Unsupported search on 'Expired'."))
        today = fields.Date.context_today(self)
        looking_for_expired = (operator == "=") == value
        if looking_for_expired:
            return [("validity_date", "<", today)]
        return ["|", ("validity_date", "=", False), ("validity_date", ">=", today)]

    # ─── Constraints ─────────────────────────────────────────────────

    @api.constrains("supplier_id", "request_id")
    def _check_supplier_belongs_to_request(self):
        """An offer must come from a candidate on the same request.

        Without this, an offer could reference a supplier from another customer's
        search, which would put one client's supplier and price into another's file.
        """
        for offer in self:
            if offer.supplier_id.request_id != offer.request_id:
                raise ValidationError(
                    _(
                        "The selected supplier belongs to a different sourcing "
                        "request."
                    )
                )

    @api.constrains("quantity", "minimum_order_quantity")
    def _check_moq(self):
        for offer in self:
            if (
                offer.minimum_order_quantity
                and offer.quantity < offer.minimum_order_quantity
            ):
                raise ValidationError(
                    _(
                        "The offered quantity (%(quantity)s) is below the supplier's "
                        "minimum order quantity (%(moq)s).",
                        quantity=offer.quantity,
                        moq=offer.minimum_order_quantity,
                    )
                )

    @api.constrains("selected")
    def _check_single_selection(self):
        """One selected offer per request.

        Two selected offers would make ``action_create_purchase_order`` ambiguous —
        and it would silently pick one.
        """
        for offer in self.filtered("selected"):
            others = self.search([
                ("request_id", "=", offer.request_id.id),
                ("selected", "=", True),
                ("id", "!=", offer.id),
            ])
            if others:
                raise ValidationError(
                    _(
                        "Request %s already has a selected offer. Deselect it first.",
                        offer.request_id.reference,
                    )
                )

    @api.constrains("sample_available", "sample_cost")
    def _check_sample(self):
        for offer in self:
            if offer.sample_cost and not offer.sample_available:
                raise ValidationError(
                    _("A sample cost was entered but no sample is marked available.")
                )

    # ─── Actions ─────────────────────────────────────────────────────

    def action_select(self):
        """Choose this offer, deselecting any other on the same request.

        Done in one place so selection is always exclusive, rather than relying on an
        operator remembering to untick the previous one.
        """
        for offer in self:
            if offer.is_expired:
                raise UserError(
                    _(
                        "Offer from %(supplier)s expired on %(date)s. Ask the "
                        "supplier to reconfirm before selecting it.",
                        supplier=offer.partner_id.display_name,
                        date=offer.validity_date,
                    )
                )

            siblings = self.search([
                ("request_id", "=", offer.request_id.id),
                ("selected", "=", True),
                ("id", "!=", offer.id),
            ])
            if siblings:
                siblings.write({"selected": False})

            offer.selected = True
            offer.supplier_id.status = "selected"
            offer.request_id.message_post(
                body=_(
                    "Offer selected: %(supplier)s, landed unit cost %(cost)s %(currency)s.",
                    supplier=offer.partner_id.display_name,
                    cost=round(offer.landed_unit_cost, 2),
                    currency=offer.currency_id.name,
                )
            )
        return True

    def action_deselect(self):
        for offer in self:
            offer.selected = False
            if offer.supplier_id.status == "selected":
                offer.supplier_id.status = "shortlisted"
        return True

    def action_create_proposal(self):
        """Draft a customer proposal from this offer.

        The bridge across the confidentiality boundary, and the only one. Costs are
        used to *derive* a selling price, and none of them is copied into the
        proposal: the customer sees what DallyTrading charges, not what it paid.
        """
        self.ensure_one()
        return self.env["dally.sourcing.proposal"]._dally_draft_from_offer(self)
