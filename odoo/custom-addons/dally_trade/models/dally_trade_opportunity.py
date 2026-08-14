# -*- coding: utf-8 -*-
"""Trade opportunities — DallyTrading's own commercial transactions.

## What this model is

A **commercial transaction DallyTrading participates in**. Six shapes, declared in
:mod:`dally_trade_rules`: achat-revente, courtage, commission, distribution,
import-export, représentation commerciale. What they share is a counterparty structure,
a purchase side, a sale side, costs, and a margin someone is accountable for.

## What it is not

- **Not a sourcing request.** Sourcing answers "find me this product or this supplier"
  on a client's behalf. Trade is DallyTrading buying, selling, brokering or
  representing on its own account. A trade may *originate* from a sourcing request —
  ``sourcing_request_id`` — but it never requires one, and most will not have one.
- **Not a disguised ``purchase.order`` or ``sale.order``.** Those are accounting
  documents with one counterparty and one currency. A trade deal has two
  counterparties, two currencies, costs on both sides and a margin that only exists
  when you look at both. It converts *into* orders once the commercial decision is
  made; it is not one.
- **Not a stock engine.** Inventory, invoicing and payments stay in Odoo's native
  flows. Duplicating them would create two answers to "what do we own".

## The confidentiality boundary

Purchase prices, cost lines, margins, negotiation notes and approval history are
internal. They carry ``groups=``, so the ORM never loads them for anyone outside trade
management and finance — being hidden in a view is not protection, and ``sudo()`` in a
public path would bypass both the groups and the record rules. The public payload is an
explicit allowlist, so a field added later is absent by default rather than exposed by
default.

## Multi-currency: nothing is subtracted naively

A purchase in CNY and a sale in EUR do not subtract. The margin fields are only
computed when either every amount is already in the analysis currency, or an explicit
conversion has been declared: a currency, a date, and an identifiable rate. Otherwise
``margin_computable`` is False and ``margin_blocker`` says why. A number produced by
silently mixing currencies is worse than no number, because it looks like an answer.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .dally_trade_rules import (
    OPERATION_TYPES,
    REVENUE_TRADE_MARGIN,
    operation_rule,
    operation_rules,
)

#: The workflow, in business order.
#:
#: Sixteen states, each answering a question an operator actually asks: "has anyone
#: priced this?", "is it waiting on me?", "has the customer signed?", "are we still
#: owed money?". Collapsing them would push the same information into a note field,
#: where it cannot be filtered or reported on.
TRADE_STATES = [
    ("draft", "Brouillon"),
    ("qualifying", "Qualification"),
    ("structuring", "Structuration"),
    ("pricing", "Chiffrage"),
    ("approval_pending", "Approbation requise"),
    ("approved", "Approuvé"),
    ("proposal_sent", "Proposition envoyée"),
    ("negotiating", "Négociation"),
    ("contracted", "Contractualisé"),
    ("purchasing", "Achat en cours"),
    ("executing", "Exécution"),
    ("settling", "Règlement"),
    ("closed", "Clôturé"),
    ("on_hold", "En pause"),
    ("cancelled", "Annulé"),
    ("lost", "Perdu"),
]

#: Nothing further happens from these without an explicit reopen.
TERMINAL_STATES = ("closed", "cancelled", "lost")

#: States a deal may be paused from, and resumed to.
HOLDABLE_STATES = (
    "qualifying", "structuring", "pricing", "approval_pending", "approved",
    "proposal_sent", "negotiating", "contracted", "purchasing", "executing",
    "settling",
)

#: Allowed transitions, declared as data.
#:
#: Without this a deal could jump from `draft` to `closed` — a file closed with no
#: counterparty, no price, no approval and no order behind it, and nobody notices
#: until someone asks what was actually traded.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("qualifying", "cancelled"),
    "qualifying": ("structuring", "on_hold", "cancelled", "lost"),
    "structuring": ("pricing", "qualifying", "on_hold", "cancelled", "lost"),
    "pricing": (
        "approval_pending", "approved", "structuring", "on_hold", "cancelled", "lost",
    ),
    "approval_pending": ("approved", "pricing", "on_hold", "cancelled", "lost"),
    "approved": ("proposal_sent", "pricing", "on_hold", "cancelled", "lost"),
    "proposal_sent": ("negotiating", "contracted", "on_hold", "cancelled", "lost"),
    "negotiating": (
        "contracted", "proposal_sent", "pricing", "on_hold", "cancelled", "lost",
    ),
    "contracted": ("purchasing", "executing", "on_hold", "cancelled"),
    "purchasing": ("executing", "on_hold", "cancelled"),
    "executing": ("settling", "on_hold", "cancelled"),
    "settling": ("closed", "on_hold", "cancelled"),
    # Terminal. Reopening is a deliberate act, not a transition.
    "closed": (),
    "cancelled": (),
    "lost": (),
    "on_hold": HOLDABLE_STATES + ("cancelled", "lost"),
}

#: Where the conversion rate came from, when currencies differ.
RATE_SOURCES = [
    ("odoo_rate", "Taux Odoo à la date de conversion"),
    ("manual", "Taux saisi explicitement"),
]

#: Field groups used throughout for internal commercial data.
#:
#: One constant, so the boundary cannot drift field by field — the failure mode where
#: eleven fields are restricted and the twelfth is not.
INTERNAL_GROUPS = "dally_trade.group_dally_trade_manager,dally_core.group_dally_finance"

TEXT_LIMITS = {
    "name": 200,
    "description": 10000,
    "customer_requirements": 10000,
}


class DallyTradeOpportunity(models.Model):
    _name = "dally.trade.opportunity"
    _description = "DallyTrading Trade Opportunity"
    _inherit = ["dally.reference.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "priority desc, expected_close_date asc, id desc"

    #: DT-TRD-YYYY-NNNNNN, produced by the mixin from dally_core.
    _dally_sequence_code = "dally.trade.opportunity"

    # ─── Identification ──────────────────────────────────────────────
    # `reference` comes from dally.reference.mixin: unique, readonly, not copied.

    name = fields.Char(
        string="Objet",
        required=True,
        tracking=True,
        help="What is being traded, in the operator's own words. Kept as written: it "
             "is what makes a deal recognisable in a list months later.",
    )
    description = fields.Text(string="Description")

    request_uuid = fields.Char(
        string="Request UUID",
        copy=False,
        index=True,
        help="Client-generated idempotency key for public intake. The unique "
             "constraint on this column is what prevents a double submission from "
             "creating two deals.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Société",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)

    operation_type = fields.Selection(
        selection=OPERATION_TYPES,
        string="Type d'opération",
        required=True,
        index=True,
        tracking=True,
        default="purchase_resale",
        help="Determines which sides of the deal exist and where revenue comes from. "
             "The rules per type are declared in one place, not scattered.",
    )
    operation_type_help = fields.Char(
        string="Ce que ce type implique",
        compute="_compute_operation_type_help",
        help="Read from the rule set, so the form explains the type it is showing.",
    )

    state = fields.Selection(
        selection=TRADE_STATES,
        string="État",
        default="draft",
        required=True,
        index=True,
        tracking=True,
        copy=False,
    )
    state_before_hold = fields.Selection(
        selection=TRADE_STATES,
        string="État avant pause",
        readonly=True,
        copy=False,
    )

    priority = fields.Selection(
        selection=[("0", "Normale"), ("1", "Haute"), ("2", "Urgente")],
        string="Priorité",
        default="0",
        index=True,
    )
    expected_close_date = fields.Date(string="Clôture attendue", tracking=True)
    actual_close_date = fields.Date(string="Clôture réelle", readonly=True, copy=False)

    responsible_id = fields.Many2one(
        comodel_name="res.users",
        string="Responsable",
        index=True,
        tracking=True,
        domain=[("share", "=", False)],
        help="Left empty on public intake: assignment is a management decision, and "
             "an unassigned queue is visible whereas a wrongly assigned deal is not.",
    )
    # Restreint au personnel interne : expose l'organisation commerciale interne, jamais
    # chargeable par un utilisateur portail.
    team_id = fields.Many2one(comodel_name="crm.team", string="Équipe", index=True, groups="dally_core.group_dally_readonly")

    # ─── Parties ─────────────────────────────────────────────────────
    #
    # Three Many2one fields to res.partner, not a dally.trade.party model. The six
    # operation types never involve more than a bounded set of roles, and an
    # intermediate model would add a join, a form and an ACL for no behaviour. If a
    # deal ever needs N participants of the same role with per-deal attributes, that
    # is the moment to introduce one.
    customer_id = fields.Many2one(
        comodel_name="res.partner",
        string="Client / acheteur",
        index=True,
        tracking=True,
    )
    supplier_id = fields.Many2one(
        comodel_name="res.partner",
        string="Fournisseur / vendeur",
        index=True,
        tracking=True,
        groups="dally_core.group_dally_sourcing," + INTERNAL_GROUPS,
        help="Who DallyTrading buys from, or who is being introduced. Restricted: "
             "which counterparty was found is commercial information.",
    )
    principal_id = fields.Many2one(
        comodel_name="res.partner",
        string="Mandant",
        index=True,
        tracking=True,
        help="The party DallyTrading acts for, on a commission or representation "
             "mandate.",
    )

    # Captured as submitted, so a public enquiry stays readable before any partner
    # exists — and so qualification never overwrites what the enquirer wrote.
    contact_name = fields.Char(string="Nom du contact", tracking=True)
    contact_company = fields.Char(string="Société du contact")
    contact_email = fields.Char(string="E-mail", index=True)
    contact_phone = fields.Char(string="Téléphone", index=True)
    contact_whatsapp = fields.Char(string="WhatsApp")
    contact_country_id = fields.Many2one(
        comodel_name="res.country", string="Pays du contact",
    )

    # ─── What the customer asked for ─────────────────────────────────
    customer_requirements = fields.Text(string="Besoin exprimé")
    service_id = fields.Many2one(
        comodel_name="dally.service.type",
        string="Activité",
        ondelete="restrict",
        index=True,
        help="The activity this deal belongs to, from the dally_core catalogue.",
    )
    origin_country_id = fields.Many2one(
        comodel_name="res.country", string="Pays d'origine",
    )
    destination_country_id = fields.Many2one(
        comodel_name="res.country", string="Pays de destination",
    )

    # ─── Items ───────────────────────────────────────────────────────
    line_ids = fields.One2many(
        comodel_name="dally.trade.line",
        inverse_name="opportunity_id",
        string="Lignes",
    )
    line_count = fields.Integer(compute="_compute_line_count", string="Nb de lignes")

    # ─── Currencies ──────────────────────────────────────────────────
    #
    # Three currencies, deliberately separate. A deal bought in CNY and sold in EUR is
    # normal, and collapsing them onto one field would force a conversion nobody
    # asked for.
    purchase_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Devise d'achat",
        default=lambda self: self.env.company.currency_id,
        tracking=True,
        groups=INTERNAL_GROUPS,
    )
    sale_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Devise de vente",
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    analysis_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Devise d'analyse",
        default=lambda self: self.env.company.currency_id,
        groups=INTERNAL_GROUPS,
        help="The currency the margin is expressed in. Reporting is only comparable "
             "when it is the same across deals, so it defaults to the company "
             "currency.",
    )

    # Explicit conversion, required as soon as currencies differ.
    conversion_currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Devise de conversion",
        groups=INTERNAL_GROUPS,
        help="Set together with a date and a rate source when the purchase, sale and "
             "analysis currencies are not all the same. Without it the margin is not "
             "computed: a figure produced by mixing currencies looks like an answer "
             "and is not one.",
    )
    conversion_date = fields.Date(
        string="Date de conversion",
        groups=INTERNAL_GROUPS,
        help="Which day's rate applies. A rate without a date cannot be audited.",
    )
    conversion_rate_source = fields.Selection(
        selection=RATE_SOURCES,
        string="Source du taux",
        groups=INTERNAL_GROUPS,
    )
    purchase_conversion_rate = fields.Float(
        string="Taux achat → analyse",
        digits=(16, 6),
        groups=INTERNAL_GROUPS,
        help="Used only when the rate source is manual. One unit of the purchase "
             "currency expressed in the analysis currency.",
    )
    sale_conversion_rate = fields.Float(
        string="Taux vente → analyse",
        digits=(16, 6),
        groups=INTERNAL_GROUPS,
    )

    # ─── Purchase side (internal) ────────────────────────────────────
    purchase_incoterm_id = fields.Many2one(
        comodel_name="account.incoterms",
        string="Incoterm achat",
        groups=INTERNAL_GROUPS,
    )
    purchase_payment_terms = fields.Char(
        string="Conditions de paiement achat", groups=INTERNAL_GROUPS,
    )
    purchase_subtotal = fields.Monetary(
        string="Total achat",
        currency_field="purchase_currency_id",
        compute="_compute_side_totals",
        store=True,
        groups=INTERNAL_GROUPS,
    )
    purchase_order_ids = fields.One2many(
        comodel_name="purchase.order",
        inverse_name="dally_trade_opportunity_id",
        string="Commandes d'achat",
        copy=False,
        groups=INTERNAL_GROUPS,
    )
    purchase_order_count = fields.Integer(
        compute="_compute_order_counts", groups=INTERNAL_GROUPS,
    )

    # ─── Sale side ───────────────────────────────────────────────────
    sale_incoterm_id = fields.Many2one(
        comodel_name="account.incoterms", string="Incoterm vente",
    )
    sale_payment_terms = fields.Char(string="Conditions de paiement vente")
    sale_subtotal = fields.Monetary(
        string="Total vente",
        currency_field="sale_currency_id",
        compute="_compute_side_totals",
        store=True,
        tracking=True,
    )
    sale_order_ids = fields.One2many(
        comodel_name="sale.order",
        inverse_name="dally_trade_opportunity_id",
        string="Commandes de vente",
        copy=False,
    )
    sale_order_count = fields.Integer(compute="_compute_order_counts")

    # ─── Costs and commissions ───────────────────────────────────────
    cost_ids = fields.One2many(
        comodel_name="dally.trade.cost",
        inverse_name="opportunity_id",
        string="Coûts",
        groups=INTERNAL_GROUPS,
    )
    cost_total_analysis = fields.Monetary(
        string="Total des coûts",
        currency_field="analysis_currency_id",
        compute="_compute_margin",
        store=True,
        groups=INTERNAL_GROUPS,
    )
    commission_ids = fields.One2many(
        comodel_name="dally.trade.commission",
        inverse_name="opportunity_id",
        string="Commissions",
        groups=INTERNAL_GROUPS,
    )
    commission_total_analysis = fields.Monetary(
        string="Total des commissions",
        currency_field="analysis_currency_id",
        compute="_compute_margin",
        store=True,
        groups=INTERNAL_GROUPS,
    )

    # ─── Margin (internal) ──────────────────────────────────────────
    margin_computable = fields.Boolean(
        string="Marge calculable",
        compute="_compute_margin",
        store=True,
        groups=INTERNAL_GROUPS,
    )
    margin_blocker = fields.Char(
        string="Pourquoi la marge n'est pas calculée",
        compute="_compute_margin",
        store=True,
        groups=INTERNAL_GROUPS,
        help="Empty when the margin is computed. Otherwise the exact reason, so the "
             "operator knows what to supply rather than seeing a blank figure.",
    )
    gross_margin = fields.Monetary(
        string="Marge brute",
        currency_field="analysis_currency_id",
        compute="_compute_margin",
        store=True,
        groups=INTERNAL_GROUPS,
        help="Sale minus purchase, in the analysis currency. Excludes costs and "
             "commissions.",
    )
    net_margin = fields.Monetary(
        string="Marge nette",
        currency_field="analysis_currency_id",
        compute="_compute_margin",
        store=True,
        groups=INTERNAL_GROUPS,
        help="Gross margin minus costs and commissions. The only figure that says "
             "whether the deal makes money.",
    )
    margin_rate = fields.Float(
        string="Taux de marge",
        digits=(16, 6),
        compute="_compute_margin",
        store=True,
        groups=INTERNAL_GROUPS,
        help="Net margin over sale revenue. There is no target here: a margin policy "
             "is a commercial decision, not a constant in the code.",
    )
    revenue_analysis = fields.Monetary(
        string="Produit",
        currency_field="analysis_currency_id",
        compute="_compute_margin",
        store=True,
        groups=INTERNAL_GROUPS,
        help="What DallyTrading earns on this deal, in the analysis currency: sale "
             "revenue for a trade margin, commission revenue otherwise.",
    )

    negotiation_notes = fields.Text(
        string="Notes de négociation",
        groups=INTERNAL_GROUPS,
        help="What was conceded, what was refused, and who said it. Internal.",
    )
    internal_notes = fields.Text(
        string="Notes internes", groups="dally_core.group_dally_readonly",
    )

    # ─── Approval ────────────────────────────────────────────────────
    approval_required = fields.Boolean(
        string="Approbation requise",
        compute="_compute_approval_required",
        store=True,
        groups=INTERNAL_GROUPS,
    )
    approval_reason = fields.Char(
        string="Motif de l'approbation",
        compute="_compute_approval_required",
        store=True,
        groups=INTERNAL_GROUPS,
    )
    approval_status = fields.Selection(
        selection=[
            ("not_required", "Non requise"),
            ("pending", "En attente"),
            ("approved", "Approuvée"),
            ("refused", "Refusée"),
        ],
        string="Statut d'approbation",
        default="not_required",
        readonly=True,
        copy=False,
        tracking=True,
        groups=INTERNAL_GROUPS,
    )
    approved_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Approuvé par",
        readonly=True,
        copy=False,
        groups=INTERNAL_GROUPS,
    )
    approved_on = fields.Datetime(
        string="Approuvé le", readonly=True, copy=False, groups=INTERNAL_GROUPS,
    )
    approval_notes = fields.Text(
        string="Commentaire d'approbation", copy=False, groups=INTERNAL_GROUPS,
    )

    # ─── Links to the rest of the system ─────────────────────────────
    crm_lead_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Opportunité CRM",
        index=True,
        copy=False,
        help="Optional. Created during qualification, not on intake: not every "
             "enquiry received from the internet deserves a pipeline entry.",
    )
    sourcing_request_id = fields.Many2one(
        comodel_name="dally.sourcing.request",
        string="Demande de sourcing d'origine",
        index=True,
        copy=False,
        groups="dally_core.group_dally_sourcing," + INTERNAL_GROUPS,
        help="Optional, and usually empty. A trade deal may originate from a sourcing "
             "request, but it never requires one: DallyTrading trades on its own "
             "account far more often than it converts a client's sourcing.",
    )
    shipment_ids = fields.One2many(
        comodel_name="dally.shipment",
        inverse_name="dally_trade_opportunity_id",
        string="Expéditions",
        copy=False,
        help="Freight stays in dally_freight. A shipment is created from here when "
             "the deal becomes logistical, and everything about carriage, packages "
             "and tracking lives there.",
    )
    shipment_count = fields.Integer(compute="_compute_shipment_count")

    # ─── Constraints ─────────────────────────────────────────────────

    _dally_trade_request_uuid_unique = models.Constraint(
        'UNIQUE(request_uuid)',
        'A trade opportunity already exists for this request UUID.',
    )

    # ─── Computes ────────────────────────────────────────────────────

    @api.depends("operation_type")
    def _compute_operation_type_help(self):
        for deal in self:
            deal.operation_type_help = (
                operation_rule(deal.operation_type, "description") or ""
            )

    @api.depends("line_ids")
    def _compute_line_count(self):
        for deal in self:
            deal.line_count = len(deal.line_ids)

    @api.depends("purchase_order_ids", "sale_order_ids")
    def _compute_order_counts(self):
        for deal in self:
            deal.purchase_order_count = len(deal.purchase_order_ids)
            deal.sale_order_count = len(deal.sale_order_ids)

    @api.depends("shipment_ids")
    def _compute_shipment_count(self):
        for deal in self:
            deal.shipment_count = len(deal.shipment_ids)

    @api.depends(
        "line_ids.purchase_subtotal", "line_ids.sale_subtotal", "operation_type",
    )
    def _compute_side_totals(self):
        """Sum the lines, per side.

        Lines carry their own currency-free subtotals in the deal's purchase and sale
        currencies, so this is a plain sum — no conversion happens here, and none is
        hidden.
        """
        for deal in self:
            deal.purchase_subtotal = sum(deal.line_ids.mapped("purchase_subtotal"))
            deal.sale_subtotal = sum(deal.line_ids.mapped("sale_subtotal"))

    def _dally_conversion_rate(self, from_currency, manual_rate):
        """Return the rate from ``from_currency`` to the analysis currency, or None.

        Returns ``None`` rather than 1.0 when the rate cannot be established. A
        fallback of 1.0 would silently treat 100 CNY as 100 EUR, which is the exact
        failure this whole mechanism exists to prevent.
        """
        self.ensure_one()
        target = self.analysis_currency_id
        if not target or not from_currency:
            return None
        if from_currency == target:
            return 1.0
        if self.conversion_rate_source == "manual":
            return manual_rate if manual_rate > 0 else None
        if self.conversion_rate_source == "odoo_rate" and self.conversion_date:
            # _convert is Odoo's own engine, and it raises rather than guessing when
            # no rate exists for the date.
            try:
                return from_currency._convert(
                    1.0, target, self.company_id, self.conversion_date,
                    round=False,
                )
            except (UserError, ValueError):
                return None
        return None

    @api.depends(
        "operation_type", "purchase_subtotal", "sale_subtotal",
        "purchase_currency_id", "sale_currency_id", "analysis_currency_id",
        "conversion_currency_id", "conversion_date", "conversion_rate_source",
        "purchase_conversion_rate", "sale_conversion_rate",
        "cost_ids.amount", "cost_ids.currency_id",
        "commission_ids.computed_amount", "commission_ids.currency_id",
        "commission_ids.direction",
    )
    def _compute_margin(self):
        """Compute the margin, or refuse to and say why.

        The refusal is the point. Every branch that cannot produce a trustworthy
        figure sets ``margin_computable = False`` and a specific ``margin_blocker``,
        leaving the amounts at zero. A silently wrong margin is acted on; a blank one
        with a reason gets fixed.
        """
        for deal in self:
            deal.margin_computable = False
            deal.margin_blocker = ""
            deal.gross_margin = 0.0
            deal.net_margin = 0.0
            deal.margin_rate = 0.0
            deal.revenue_analysis = 0.0
            deal.cost_total_analysis = 0.0
            deal.commission_total_analysis = 0.0

            if not deal.operation_type:
                deal.margin_blocker = _("Le type d'opération n'est pas renseigné.")
                continue
            if not deal.analysis_currency_id:
                deal.margin_blocker = _("La devise d'analyse n'est pas renseignée.")
                continue

            rules = operation_rules(deal.operation_type)
            is_trade_margin = rules["revenue_model"] == REVENUE_TRADE_MARGIN

            # Which currencies have to reach the analysis currency for this type.
            needed = {deal.sale_currency_id} if deal.sale_currency_id else set()
            if is_trade_margin and deal.purchase_currency_id:
                needed.add(deal.purchase_currency_id)
            needed |= set(deal.cost_ids.mapped("currency_id"))
            needed |= set(deal.commission_ids.mapped("currency_id"))
            needed.discard(deal.analysis_currency_id)

            if needed and not (
                deal.conversion_currency_id
                and deal.conversion_date
                and deal.conversion_rate_source
            ):
                deal.margin_blocker = _(
                    "Devises différentes (%(currencies)s) sans conversion déclarée. "
                    "Renseignez la devise de conversion, la date et la source du taux.",
                    currencies=", ".join(
                        sorted(currency.name for currency in needed)
                    ),
                )
                continue
            if needed and deal.conversion_currency_id != deal.analysis_currency_id:
                deal.margin_blocker = _(
                    "La devise de conversion (%(conversion)s) doit être la devise "
                    "d'analyse (%(analysis)s).",
                    conversion=deal.conversion_currency_id.name,
                    analysis=deal.analysis_currency_id.name,
                )
                continue

            sale_rate = deal._dally_conversion_rate(
                deal.sale_currency_id, deal.sale_conversion_rate,
            )
            if deal.sale_currency_id and sale_rate is None:
                deal.margin_blocker = _(
                    "Aucun taux identifiable pour convertir %(currency)s en "
                    "%(analysis)s.",
                    currency=deal.sale_currency_id.name,
                    analysis=deal.analysis_currency_id.name,
                )
                continue

            purchase_analysis = 0.0
            if is_trade_margin:
                purchase_rate = deal._dally_conversion_rate(
                    deal.purchase_currency_id, deal.purchase_conversion_rate,
                )
                if deal.purchase_currency_id and purchase_rate is None:
                    deal.margin_blocker = _(
                        "Aucun taux identifiable pour convertir %(currency)s en "
                        "%(analysis)s.",
                        currency=deal.purchase_currency_id.name,
                        analysis=deal.analysis_currency_id.name,
                    )
                    continue
                purchase_analysis = deal.purchase_subtotal * (purchase_rate or 0.0)

            sale_analysis = deal.sale_subtotal * (sale_rate or 0.0)

            costs = 0.0
            blocked = False
            for cost in deal.cost_ids:
                rate = deal._dally_conversion_rate(
                    cost.currency_id, cost.conversion_rate,
                )
                if rate is None:
                    deal.margin_blocker = _(
                        "Le coût « %(name)s » est en %(currency)s sans taux "
                        "identifiable.",
                        name=cost.name or _("sans nom"),
                        currency=cost.currency_id.name or _("devise absente"),
                    )
                    blocked = True
                    break
                costs += cost.amount * rate
            if blocked:
                continue

            commissions_payable = 0.0
            commissions_receivable = 0.0
            for commission in deal.commission_ids:
                rate = deal._dally_conversion_rate(
                    commission.currency_id, commission.conversion_rate,
                )
                if rate is None:
                    deal.margin_blocker = _(
                        "La commission « %(name)s » est en %(currency)s sans taux "
                        "identifiable.",
                        name=commission.name or _("sans nom"),
                        currency=commission.currency_id.name or _("devise absente"),
                    )
                    blocked = True
                    break
                converted = commission.computed_amount * rate
                if commission.direction == "payable":
                    commissions_payable += converted
                else:
                    commissions_receivable += converted
            if blocked:
                continue

            # Revenue depends on the type, and this is the only place it does.
            if is_trade_margin:
                deal.revenue_analysis = sale_analysis
                deal.gross_margin = sale_analysis - purchase_analysis
            else:
                # No purchase price to subtract: DallyTrading never owned the goods.
                deal.revenue_analysis = commissions_receivable + sale_analysis
                deal.gross_margin = deal.revenue_analysis

            deal.cost_total_analysis = costs
            deal.commission_total_analysis = commissions_payable
            deal.net_margin = deal.gross_margin - costs - commissions_payable
            deal.margin_rate = (
                deal.net_margin / deal.revenue_analysis
                if deal.revenue_analysis
                else 0.0
            )
            deal.margin_computable = True

    def _dally_approval_thresholds(self):
        """Read the approval thresholds from configuration.

        Deliberately not constants. A threshold is a policy that changes with the
        company's size, its cash position and its appetite for risk, and one written
        into Python is one nobody can change without a deployment. Absent
        configuration means no threshold, not an invented one.
        """
        parameters = self.env["ir.config_parameter"].sudo()

        def _float(key):
            raw = (parameters.get_param(key) or "").strip()
            if not raw:
                return None
            try:
                value = float(raw)
            except ValueError:
                return None
            return value if value > 0 else None

        return {
            "revenue": _float("dally_trade.approval_revenue_threshold"),
            "margin_rate": _float("dally_trade.approval_min_margin_rate"),
        }

    @api.depends(
        "operation_type", "revenue_analysis", "margin_rate", "margin_computable",
        "net_margin",
    )
    def _compute_approval_required(self):
        """Decide whether this deal needs a manager's signature.

        Three triggers, in order of severity: a negative margin, a margin below a
        configured floor, and revenue above a configured ceiling. All three are
        configuration-driven except the negative margin, which needs no policy — a
        deal that loses money should never be committed without someone deciding to.
        """
        for deal in self:
            thresholds = deal._dally_approval_thresholds()
            reason = ""

            if deal.margin_computable and deal.net_margin < 0:
                reason = _(
                    "Marge nette négative (%(margin)s %(currency)s).",
                    margin=round(deal.net_margin, 2),
                    currency=deal.analysis_currency_id.name or "",
                )
            elif (
                deal.margin_computable
                and thresholds["margin_rate"] is not None
                and deal.revenue_analysis
                and deal.margin_rate < thresholds["margin_rate"]
            ):
                reason = _(
                    "Taux de marge (%(rate)s) inférieur au seuil configuré "
                    "(%(threshold)s).",
                    rate=round(deal.margin_rate, 4),
                    threshold=thresholds["margin_rate"],
                )
            elif (
                thresholds["revenue"] is not None
                and deal.revenue_analysis >= thresholds["revenue"]
            ):
                reason = _(
                    "Produit (%(revenue)s %(currency)s) au-dessus du seuil configuré "
                    "(%(threshold)s).",
                    revenue=round(deal.revenue_analysis, 2),
                    currency=deal.analysis_currency_id.name or "",
                    threshold=thresholds["revenue"],
                )

            deal.approval_required = bool(reason)
            deal.approval_reason = reason

    # ─── Validation ──────────────────────────────────────────────────

    @api.constrains("operation_type", "line_ids")
    def _check_lines_match_operation_type(self):
        """A line may only price a side the operation type actually has.

        A courtage line with a purchase price means someone recorded a purchase
        DallyTrading never made. Checked here rather than on the line so the message
        can name the deal and its type.
        """
        for deal in self:
            if not deal.operation_type:
                continue
            rules = operation_rules(deal.operation_type)
            label = dict(OPERATION_TYPES)[deal.operation_type]
            if not rules["has_purchase_side"]:
                offending = deal.line_ids.filtered(
                    lambda line: line.purchase_unit_price
                )
                if offending:
                    raise ValidationError(
                        _(
                            "Une opération de type « %(type)s » ne comporte pas de "
                            "volet achat : DallyTrading n'acquiert pas la "
                            "marchandise. Retirez le prix d'achat des lignes "
                            "%(lines)s, ou changez le type d'opération.",
                            type=label,
                            lines=", ".join(
                                line.description or _("sans description")
                                for line in offending
                            ),
                        )
                    )

    @api.constrains("operation_type", "supplier_id", "customer_id", "principal_id",
                    "state")
    def _check_required_parties(self):
        """Parties required by the type, checked from `structuring` onwards.

        Not on creation: a public enquiry cannot know who the supplier will be, and
        requiring it at intake would make the form unfillable.
        """
        early = ("draft", "qualifying")
        for deal in self:
            if not deal.operation_type or deal.state in early:
                continue
            if deal.state in ("cancelled", "lost"):
                continue
            rules = operation_rules(deal.operation_type)
            label = dict(OPERATION_TYPES)[deal.operation_type]
            missing = []
            if rules["requires_supplier"] and not deal.supplier_id:
                missing.append(_("un fournisseur / vendeur"))
            if rules["requires_customer"] and not deal.customer_id:
                missing.append(_("un client / acheteur"))
            if rules["requires_principal"] and not deal.principal_id:
                missing.append(_("un mandant"))
            if missing:
                raise ValidationError(
                    _(
                        "L'opération %(reference)s de type « %(type)s » exige "
                        "%(missing)s.",
                        reference=deal.reference,
                        type=label,
                        missing=", ".join(missing),
                    )
                )

    @api.constrains("conversion_currency_id", "conversion_date",
                    "conversion_rate_source", "purchase_conversion_rate",
                    "sale_conversion_rate")
    def _check_conversion_is_complete(self):
        """A declared conversion must be complete, or it is not a conversion."""
        for deal in self:
            declared = any((
                deal.conversion_currency_id,
                deal.conversion_date,
                deal.conversion_rate_source,
            ))
            if not declared:
                continue
            if not (deal.conversion_currency_id and deal.conversion_date
                    and deal.conversion_rate_source):
                raise ValidationError(
                    _(
                        "Une conversion doit indiquer les trois : devise de "
                        "conversion, date et source du taux. Un taux sans date n'est "
                        "pas auditable."
                    )
                )
            if deal.conversion_rate_source == "manual":
                if (deal.sale_currency_id
                        and deal.sale_currency_id != deal.analysis_currency_id
                        and deal.sale_conversion_rate <= 0):
                    raise ValidationError(
                        _("Le taux vente → analyse doit être renseigné et positif.")
                    )
                if (deal.purchase_currency_id
                        and deal.purchase_currency_id != deal.analysis_currency_id
                        and deal.purchase_conversion_rate <= 0):
                    raise ValidationError(
                        _("Le taux achat → analyse doit être renseigné et positif.")
                    )

    @api.constrains("name", "description", "customer_requirements")
    def _check_text_lengths(self):
        """Bound the free-text fields that public intake can write.

        Without this a submission could store megabytes per record.
        """
        for deal in self:
            for field_name, limit in TEXT_LIMITS.items():
                value = deal[field_name] or ""
                if len(value) > limit:
                    raise ValidationError(
                        _(
                            "Le champ « %(field)s » dépasse %(limit)s caractères.",
                            field=deal._fields[field_name].string,
                            limit=limit,
                        )
                    )

    # ─── Workflow ────────────────────────────────────────────────────

    def _dally_set_state(self, new_state):
        """Move to ``new_state``, refusing transitions the map does not allow."""
        labels = dict(TRADE_STATES)
        for deal in self:
            if deal.state == new_state:
                continue
            allowed = ALLOWED_TRANSITIONS.get(deal.state, ())
            if new_state not in allowed:
                raise UserError(
                    _(
                        "Impossible de passer l'opération %(reference)s de "
                        "« %(current)s » à « %(target)s ». Transitions possibles "
                        "depuis cet état : %(allowed)s.",
                        reference=deal.reference,
                        current=labels[deal.state],
                        target=labels[new_state],
                        allowed=", ".join(labels[state] for state in allowed)
                        or _("aucune — cette opération est clôturée"),
                    )
                )
            deal.state = new_state
        return True

    def action_qualify(self):
        """Someone has looked at the enquiry and it is worth working on."""
        return self._dally_set_state("qualifying")

    def action_structure(self):
        """Fix the shape of the deal: type, parties, sides."""
        for deal in self:
            if not deal.operation_type:
                raise UserError(
                    _(
                        "L'opération %s n'a pas de type. C'est lui qui détermine "
                        "quels volets existent.",
                        deal.reference,
                    )
                )
        return self._dally_set_state("structuring")

    def action_start_pricing(self):
        """Ready to price. Requires something to price."""
        for deal in self:
            if not deal.line_ids:
                raise UserError(
                    _(
                        "L'opération %s n'a aucune ligne à chiffrer. Chiffrer un "
                        "dossier vide produit un prix inventé.",
                        deal.reference,
                    )
                )
        return self._dally_set_state("pricing")

    def action_request_approval(self):
        """Send the deal for a manager's decision."""
        for deal in self:
            if not deal.line_ids:
                raise UserError(
                    _("L'opération %s n'a rien à approuver.", deal.reference)
                )
        self._dally_set_state("approval_pending")
        self.write({"approval_status": "pending"})
        for deal in self:
            deal.message_post(
                body=_(
                    "Approbation demandée. Motif : %s",
                    deal.approval_reason or _("demande explicite"),
                )
            )
        return True

    def action_approve(self):
        """Approve the deal. Trade management and general management only.

        The restriction is checked in Python, not left to the button's ``groups=``: a
        view attribute is a UI convenience, and this is the control that stops a deal
        below its margin floor from being committed.
        """
        self._dally_check_approval_rights()
        for deal in self:
            if not deal.margin_computable:
                raise UserError(
                    _(
                        "L'opération %(reference)s ne peut pas être approuvée car sa "
                        "marge n'est pas calculable : %(blocker)s\n\n"
                        "Approuver un dossier dont on ne peut pas établir la marge "
                        "revient à approuver un chiffre inconnu.",
                        reference=deal.reference,
                        blocker=deal.margin_blocker,
                    )
                )
        self._dally_set_state("approved")
        self.write({
            "approval_status": "approved",
            "approved_by_id": self.env.user.id,
            "approved_on": fields.Datetime.now(),
        })
        for deal in self:
            deal.message_post(body=_("Opération approuvée."))
        return True

    def action_refuse_approval(self):
        """Refuse, and send the deal back to pricing rather than killing it."""
        self._dally_check_approval_rights()
        self._dally_set_state("pricing")
        self.write({
            "approval_status": "refused",
            "approved_by_id": False,
            "approved_on": False,
        })
        for deal in self:
            deal.message_post(
                body=_(
                    "Approbation refusée. %s",
                    deal.approval_notes or _("Aucun commentaire."),
                )
            )
        return True

    #: Who may approve a sensitive deal.
    _dally_approval_groups = (
        "dally_trade.group_dally_trade_manager",
        "dally_core.group_dally_manager",
    )

    def _dally_check_approval_rights(self):
        if any(self.env.user.has_group(group)
               for group in self._dally_approval_groups):
            return
        raise UserError(
            _(
                "Seule la direction commerciale trade ou la direction générale peut "
                "approuver une opération. Juger un dossier suppose de voir ses coûts "
                "et sa marge, qui sont restreints."
            )
        )

    def action_send_proposal(self):
        """The commercial proposal has gone out.

        Guarded on approval: a deal that needed a signature must not reach a customer
        without one. This is the single most consequential guard in the workflow —
        everything after it is a commitment.
        """
        for deal in self:
            if deal.approval_required and deal.approval_status != "approved":
                raise UserError(
                    _(
                        "L'opération %(reference)s exige une approbation avant "
                        "d'être proposée. Motif : %(reason)s",
                        reference=deal.reference,
                        reason=deal.approval_reason,
                    )
                )
            if not deal.sale_subtotal and not deal.commission_ids:
                raise UserError(
                    _(
                        "L'opération %s n'a ni montant de vente ni commission : il "
                        "n'y a rien à proposer.",
                        deal.reference,
                    )
                )
            if not deal.customer_id and not (deal.contact_email or "").strip():
                raise UserError(
                    _(
                        "L'opération %s n'a ni client ni adresse e-mail où envoyer "
                        "la proposition.",
                        deal.reference,
                    )
                )
        return self._dally_set_state("proposal_sent")

    def action_start_negotiation(self):
        return self._dally_set_state("negotiating")

    def action_contract(self):
        """The counterparty agreed. From here the deal is a commitment."""
        for deal in self:
            if deal.approval_required and deal.approval_status != "approved":
                raise UserError(
                    _(
                        "L'opération %(reference)s ne peut être contractualisée sans "
                        "approbation. Motif : %(reason)s",
                        reference=deal.reference,
                        reason=deal.approval_reason,
                    )
                )
        return self._dally_set_state("contracted")

    def action_start_purchasing(self):
        """Only meaningful where the type has a purchase side."""
        for deal in self:
            if not operation_rule(deal.operation_type, "has_purchase_side"):
                raise UserError(
                    _(
                        "Une opération de type « %(type)s » ne comporte pas de volet "
                        "achat : DallyTrading n'acquiert pas la marchandise.",
                        type=dict(OPERATION_TYPES)[deal.operation_type],
                    )
                )
        return self._dally_set_state("purchasing")

    def action_start_execution(self):
        return self._dally_set_state("executing")

    def action_start_settlement(self):
        return self._dally_set_state("settling")

    def action_close(self):
        self._dally_set_state("closed")
        self.write({"actual_close_date": fields.Date.context_today(self)})
        return True

    def action_mark_lost(self):
        self._dally_set_state("lost")
        self.write({"actual_close_date": fields.Date.context_today(self)})
        return True

    def action_cancel(self):
        return self._dally_set_state("cancelled")

    def action_put_on_hold(self):
        """Pause, remembering where to return to."""
        for deal in self:
            if deal.state not in HOLDABLE_STATES:
                raise UserError(
                    _(
                        "L'opération %(reference)s ne peut pas être mise en pause "
                        "depuis l'état « %(state)s ».",
                        reference=deal.reference,
                        state=dict(TRADE_STATES)[deal.state],
                    )
                )
            deal.state_before_hold = deal.state
        return self._dally_set_state("on_hold")

    def action_resume(self):
        """Return to where the deal was paused from.

        Stored rather than guessed: resuming to a fixed state would silently move a
        deal backwards or forwards in its own history.
        """
        for deal in self:
            if deal.state != "on_hold":
                continue
            target = deal.state_before_hold or "qualifying"
            deal._dally_set_state(target)
            deal.state_before_hold = False
        return True

    def action_reopen(self):
        """Reopen a terminal deal — deliberate, and traced."""
        for deal in self:
            if deal.state not in TERMINAL_STATES:
                raise UserError(
                    _("L'opération %s n'est pas clôturée.", deal.reference)
                )
            deal.state = "negotiating"
            deal.actual_close_date = False
            deal.message_post(body=_("Opération réouverte."))
        return True

    # ─── Conversions into native commercial documents ─────────────────
    #
    # The same rule as dally_sourcing (ADR-013): a real line, or no document. An order
    # with no usable line can be confirmed and reported on while nobody can tell what
    # was meant to be bought; a zero-priced sale line can additionally be invoiced,
    # and the customer receives an invoice for nothing.

    def _dally_convertible_lines(self, side):
        """Lines that can produce an order line on ``side``, and why not otherwise.

        Returns ``(lines, problems)``. Nothing is created when ``problems`` is
        non-empty, so a partially usable deal fails loudly rather than producing half
        an order.
        """
        self.ensure_one()
        lines, problems = self.env["dally.trade.line"], []
        for line in self.line_ids:
            issues = line._dally_order_line_blockers(side)
            if issues:
                problems.append(
                    _(
                        "Ligne « %(line)s » : %(issues)s",
                        line=line.description or _("sans description"),
                        issues=", ".join(issues),
                    )
                )
            else:
                lines |= line
        return lines, problems

    def action_create_purchase_order(self):
        """Raise the purchase order for the buy side.

        Refused outright for types without a purchase side: a courtage or a commission
        never acquires the goods, and a purchase order would record a liability
        DallyTrading does not have.
        """
        self.ensure_one()
        rules = operation_rules(self.operation_type)

        if not rules["allows_purchase_order"]:
            raise UserError(
                _(
                    "Une opération de type « %(type)s » ne donne pas lieu à une "
                    "commande d'achat : DallyTrading n'acquiert pas la marchandise. "
                    "Émettre une commande enregistrerait une dette inexistante.",
                    type=dict(OPERATION_TYPES)[self.operation_type],
                )
            )
        if self.state not in ("contracted", "purchasing", "executing"):
            raise UserError(
                _(
                    "L'opération %s doit être contractualisée avant qu'une commande "
                    "d'achat soit émise.",
                    self.reference,
                )
            )
        if self.purchase_order_ids:
            # Idempotent by intent: re-running opens what exists rather than raising a
            # second order against the same supplier.
            return self._dally_open_records(
                "purchase.order", self.purchase_order_ids.ids,
                _("Commandes d'achat"),
            )

        missing = []
        if not self.supplier_id:
            missing.append(_("un fournisseur"))
        if not self.purchase_currency_id:
            missing.append(_("une devise d'achat"))
        if not self.company_id:
            missing.append(_("une société"))
        lines, problems = self._dally_convertible_lines("purchase")
        if not lines:
            missing.append(_("au moins une ligne d'achat exploitable"))

        if missing or problems:
            raise UserError(
                _(
                    "L'opération %(reference)s ne peut pas produire une commande "
                    "d'achat exploitable.\n\nManquant : %(missing)s\n%(problems)s\n"
                    "Une commande sans ligne exploitable peut être confirmée et "
                    "apparaît dans le reporting alors que plus personne ne sait ce "
                    "qui devait être acheté. Elle n'est donc pas créée.",
                    reference=self.reference,
                    missing=", ".join(missing) or _("rien"),
                    problems="\n".join(problems),
                )
            )

        order = self.env["purchase.order"].create({
            "partner_id": self.supplier_id.id,
            "currency_id": self.purchase_currency_id.id,
            "company_id": self.company_id.id,
            "origin": self.reference,
            "dally_trade_opportunity_id": self.id,
            "order_line": [
                (0, 0, line._dally_purchase_order_line_values()) for line in lines
            ],
        })
        self.message_post(
            body=_(
                "Commande d'achat %(order)s créée : %(count)s ligne(s).",
                order=order.name,
                count=len(lines),
            )
        )
        if self.state == "contracted":
            self._dally_set_state("purchasing")
        return self._dally_open_records(
            "purchase.order", order.ids, _("Commande d'achat"),
        )

    def action_create_sale_order(self):
        """Raise the sales order for the sell side.

        Available on every type: even a courtage or a commission invoices someone —
        the difference is what the line represents, which the line itself decides.
        """
        self.ensure_one()
        if self.state not in ("contracted", "purchasing", "executing", "settling"):
            raise UserError(
                _(
                    "L'opération %s doit être contractualisée avant qu'une commande "
                    "de vente soit émise.",
                    self.reference,
                )
            )
        if self.sale_order_ids:
            return self._dally_open_records(
                "sale.order", self.sale_order_ids.ids, _("Commandes de vente"),
            )

        missing = []
        if not self.customer_id:
            missing.append(_("un client"))
        if not self.sale_currency_id:
            missing.append(_("une devise de vente"))
        if not self.company_id:
            missing.append(_("une société"))
        lines, problems = self._dally_convertible_lines("sale")
        if not lines:
            missing.append(_("au moins une ligne de vente exploitable"))

        if missing or problems:
            raise UserError(
                _(
                    "L'opération %(reference)s ne peut pas produire une commande de "
                    "vente exploitable.\n\nManquant : %(missing)s\n%(problems)s\n"
                    "Une ligne de vente à prix nul peut être confirmée puis facturée, "
                    "et le client recevrait une facture pour rien. Elle n'est donc "
                    "pas créée.",
                    reference=self.reference,
                    missing=", ".join(missing) or _("rien"),
                    problems="\n".join(problems),
                )
            )

        order = self.env["sale.order"].create({
            "partner_id": self.customer_id.id,
            "currency_id": self.sale_currency_id.id,
            "company_id": self.company_id.id,
            "origin": self.reference,
            "dally_trade_opportunity_id": self.id,
            "opportunity_id": self.crm_lead_id.id or False,
            "order_line": [
                (0, 0, line._dally_sale_order_line_values()) for line in lines
            ],
        })
        self.message_post(
            body=_(
                "Commande de vente %(order)s créée : %(count)s ligne(s).",
                order=order.name,
                count=len(lines),
            )
        )
        return self._dally_open_records("sale.order", order.ids, _("Commande de vente"))

    # ─── Links to freight and CRM ────────────────────────────────────

    def action_create_shipment(self):
        """Create the freight file for this deal, in dally_freight.

        No carriage logic here. Weights, packages, containers, chargeable weight and
        the tracking timeline are dally_freight's and dally_tracking's; duplicating
        any of it would create two answers to "where is the cargo".
        """
        self.ensure_one()
        if self.shipment_ids:
            return self._dally_open_records(
                "dally.shipment", self.shipment_ids.ids, _("Expéditions"),
            )
        if not self.customer_id:
            raise UserError(
                _(
                    "L'opération %s n'a pas de client : une expédition sans donneur "
                    "d'ordre ne peut être ni suivie ni facturée.",
                    self.reference,
                )
            )
        shipment = self.env["dally.shipment"].create({
            "partner_id": self.customer_id.id,
            "company_id": self.company_id.id,
            "dally_trade_opportunity_id": self.id,
            "origin_country_id": self.origin_country_id.id or False,
            "destination_country_id": self.destination_country_id.id or False,
            "sale_order_id": self.sale_order_ids[:1].id or False,
        })
        self.message_post(
            body=_("Expédition %s créée dans dally_freight.", shipment.reference)
        )
        return self._dally_open_records(
            "dally.shipment", shipment.ids, _("Expédition"),
        )

    def action_create_crm_opportunity(self):
        """Mirror the deal into the CRM pipeline, once, on request.

        Not automatic: not every enquiry deserves a pipeline entry, and a pipeline
        full of dead leads is a pipeline nobody reads.
        """
        self.ensure_one()
        if self.crm_lead_id:
            return self._dally_open_records(
                "crm.lead", self.crm_lead_id.ids, _("Opportunité CRM"),
            )
        if not self.customer_id and not (self.contact_email or "").strip():
            raise UserError(
                _(
                    "L'opération %s n'a ni client ni e-mail : une opportunité CRM "
                    "sans contact ne peut pas être travaillée.",
                    self.reference,
                )
            )
        lead = self.env["crm.lead"].create({
            "name": _("%(reference)s — %(name)s",
                      reference=self.reference, name=self.name),
            "type": "opportunity",
            "partner_id": self.customer_id.id or False,
            "contact_name": self.contact_name or False,
            "email_from": self.contact_email or False,
            "phone": self.contact_phone or False,
            "company_id": self.company_id.id,
            "team_id": self.team_id.id or False,
            "user_id": self.responsible_id.id or False,
            "country_id": self.contact_country_id.id or False,
        })
        self.crm_lead_id = lead
        self.message_post(body=_("Opportunité CRM %s créée.", lead.name))
        return self._dally_open_records("crm.lead", lead.ids, _("Opportunité CRM"))

    def action_create_customer(self):
        """Turn the captured contact into a res.partner, reusing the anti-duplicate.

        ``_dally_find_existing`` lives in dally_crm and already knows which criteria
        are reliable. Re-implementing the matching here would give two answers to
        "is this the same company".
        """
        self.ensure_one()
        if self.customer_id:
            return self._dally_open_records(
                "res.partner", self.customer_id.ids, _("Client"),
            )
        Partner = self.env["res.partner"]
        existing = Partner._dally_find_existing(
            email=self.contact_email,
            phone=self.contact_phone,
            whatsapp=self.contact_whatsapp,
            company_name=self.contact_company,
        )
        if existing:
            self.customer_id = existing[:1]
            self.message_post(
                body=_("Contact existant rattaché : %s", existing[:1].display_name)
            )
            return self._dally_open_records(
                "res.partner", existing[:1].ids, _("Client"),
            )
        if not (self.contact_name or self.contact_company):
            raise UserError(
                _(
                    "L'opération %s n'a ni nom de contact ni société : il n'y a pas "
                    "de quoi créer une fiche.",
                    self.reference,
                )
            )
        partner = Partner.create({
            "name": self.contact_company or self.contact_name,
            "is_company": bool(self.contact_company),
            "email": self.contact_email or False,
            "phone": self.contact_phone or False,
            "country_id": self.contact_country_id.id or False,
            "company_id": False,
        })
        self.customer_id = partner
        self.message_post(body=_("Client créé : %s", partner.display_name))
        return self._dally_open_records("res.partner", partner.ids, _("Client"))

    # ─── Public projection ───────────────────────────────────────────

    #: What may leave the system about a trade enquiry.
    #:
    #: An allowlist, not a denylist. A field added to the model later is absent from
    #: the payload by default, which is the only direction that fails safely.
    PUBLIC_PAYLOAD_KEYS = (
        "reference", "status", "statusLabel", "operationType",
        "operationTypeLabel", "subject", "createdOn",
    )

    #: Names that must never reach a public payload, asserted by a test.
    #:
    #: Redundant with the allowlist by design: the allowlist prevents the leak, and
    #: this makes a regression fail loudly instead of quietly widening the boundary.
    FORBIDDEN_PUBLIC_FIELDS = (
        "internal_cost", "purchase_margin", "internal_margin", "supplier_score",
        "internal_commission", "negotiation_notes", "approval_status",
        "purchase_subtotal", "purchase_currency_id", "purchase_unit_price",
        "gross_margin", "net_margin", "margin_rate", "cost_total_analysis",
        "commission_total_analysis", "supplier_id", "internal_notes",
        "approval_reason", "approved_by_id", "revenue_analysis",
    )

    def _dally_public_payload(self):
        """What a caller may be shown about their own trade enquiry.

        No database ids, no counterparty, no price, no cost, no margin, no approval
        state. A trade enquirer learns the reference and where the file stands.
        """
        self.ensure_one()
        state_labels = dict(TRADE_STATES)
        type_labels = dict(OPERATION_TYPES)
        payload = {
            "reference": self.reference,
            "status": self.state,
            "statusLabel": state_labels.get(self.state, self.state),
            "operationType": self.operation_type,
            "operationTypeLabel": type_labels.get(
                self.operation_type, self.operation_type,
            ),
            "subject": self.name or None,
            "createdOn": (
                self.create_date.date().isoformat() if self.create_date else None
            ),
        }
        # Asserted rather than assumed: the allowlist is the contract, so a key that
        # drifts out of it must fail here rather than reach a caller.
        return {key: payload[key] for key in self.PUBLIC_PAYLOAD_KEYS}

    # ─── Public intake ───────────────────────────────────────────────

    @api.model
    def dally_create_from_website(self, values):
        """Create a trade enquiry from the public API.

        Idempotent on ``request_uuid``, including archived records: a submission that
        was archived as spam and then replayed would otherwise hit the unique
        constraint and surface as a 500.

        Never sets a state, a responsible user, a price or any internal field — the
        controller's allowlist stops those at the door, and this method does not
        reintroduce them.
        """
        uuid = (values.get("request_uuid") or "").strip()
        if uuid:
            existing = self.with_context(active_test=False).search(
                [("request_uuid", "=", uuid)], limit=1,
            )
            if existing:
                return existing
        return self.create(self._dally_prepare_values(values))

    @api.model
    def _dally_prepare_values(self, values):
        """Map a validated public payload onto model fields.

        Only the fields a public caller is allowed to influence. `state`,
        `responsible_id`, prices, costs, margins and approval fields are absent by
        construction — they are not in this mapping at all.
        """
        prepared = {
            "name": (values.get("subject") or "").strip()[:TEXT_LIMITS["name"]],
            "request_uuid": (values.get("request_uuid") or "").strip() or False,
            "operation_type": values.get("operation_type") or "purchase_resale",
            "description": (values.get("description") or "").strip() or False,
            "customer_requirements": (
                (values.get("requirements") or "").strip() or False
            ),
            "contact_name": (values.get("contact_name") or "").strip() or False,
            "contact_company": (values.get("company") or "").strip() or False,
            "contact_email": (values.get("email") or "").strip() or False,
            "contact_phone": (values.get("phone") or "").strip() or False,
            "contact_whatsapp": (values.get("whatsapp") or "").strip() or False,
        }
        if not prepared["name"]:
            prepared["name"] = _("Demande de trading")

        for key, field_name in (
            ("contact_country", "contact_country_id"),
            ("origin_country", "origin_country_id"),
            ("destination_country", "destination_country_id"),
        ):
            code = (values.get(key) or "").strip().upper()
            if code:
                country = self.env["res.country"].search(
                    [("code", "=", code)], limit=1,
                )
                # No default country: guessing one would attribute an enquiry to a
                # market it never came from.
                if country:
                    prepared[field_name] = country.id

        service_code = (values.get("service_code") or "").strip()
        if service_code:
            service = self.env["dally.service.type"].search(
                [("code", "=", service_code)], limit=1,
            )
            if service:
                prepared["service_id"] = service.id

        return prepared

    # ─── Navigation helpers ──────────────────────────────────────────

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

    def action_view_purchase_orders(self):
        self.ensure_one()
        return self._dally_open_records(
            "purchase.order", self.purchase_order_ids.ids, _("Commandes d'achat"),
        )

    def action_view_sale_orders(self):
        self.ensure_one()
        return self._dally_open_records(
            "sale.order", self.sale_order_ids.ids, _("Commandes de vente"),
        )

    def action_view_shipments(self):
        self.ensure_one()
        return self._dally_open_records(
            "dally.shipment", self.shipment_ids.ids, _("Expéditions"),
        )
