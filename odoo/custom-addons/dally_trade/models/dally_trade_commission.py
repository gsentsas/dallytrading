# -*- coding: utf-8 -*-
"""Commissions — who is paid what, and by whom.

## Why direction is a field and not two models

A commission DallyTrading *receives* on a courtage and one it *pays* to an intermediary
are the same object seen from two sides: a payer, a payee, a basis, an amount. Two models
would duplicate the computation and let them drift. One model with an explicit
``direction`` keeps the arithmetic in one place, and the opportunity adds receivables to
revenue and subtracts payables from margin — which is the only place the sign matters.

## Fixed or percentage, never both

A commission is either an agreed amount or an agreed rate on a basis. Storing both and
picking one at read time is how a figure ends up depending on which code path read it.
``computed_amount`` resolves it once, and a constraint refuses a percentage without a
basis.

## No default rate

There is deliberately no default commission rate. A rate is negotiated per deal and per
counterparty; a constant in the code would be a rate nobody agreed to, applied silently.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

#: Which side of the deal the commission sits on.
COMMISSION_DIRECTIONS = [
    ("receivable", "À recevoir par DallyTrading"),
    ("payable", "À verser par DallyTrading"),
]

#: How the amount is established.
COMMISSION_BASIS = [
    ("fixed", "Montant fixe"),
    ("percentage", "Pourcentage d'une base"),
]

#: What a percentage applies to. A closed list, so "percentage of what" is never
#: ambiguous — the single most common source of commission disputes.
COMMISSION_BASE_FIELDS = [
    ("sale_subtotal", "Total de vente"),
    ("purchase_subtotal", "Total d'achat"),
    ("custom", "Base saisie explicitement"),
]


class DallyTradeCommission(models.Model):
    _name = "dally.trade.commission"
    _description = "DallyTrading Trade Commission"
    _order = "opportunity_id, direction, id"

    opportunity_id = fields.Many2one(
        comodel_name="dally.trade.opportunity",
        string="Opération",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="opportunity_id.company_id", store=True, index=True, readonly=True,
    )

    name = fields.Char(
        string="Libellé",
        required=True,
        help="What this commission is for. Required: « commission » alone does not "
             "say which introduction or which mandate it rewards.",
    )
    direction = fields.Selection(
        selection=COMMISSION_DIRECTIONS,
        string="Sens",
        required=True,
        default="receivable",
        index=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Contrepartie",
        required=True,
        index=True,
        help="Who pays it, when receivable; who receives it, when payable. Required "
             "either way: a commission owed to nobody is not a commission.",
    )

    basis = fields.Selection(
        selection=COMMISSION_BASIS,
        string="Mode de calcul",
        required=True,
        default="fixed",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Devise",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    fixed_amount = fields.Monetary(
        string="Montant fixe", currency_field="currency_id",
    )
    rate = fields.Float(
        string="Taux",
        digits=(5, 4),
        help="Expressed as a fraction: 0,03 for 3 %. No default — a rate is "
             "negotiated per deal, and a constant in the code would be a rate nobody "
             "agreed to.",
    )
    base_field = fields.Selection(
        selection=COMMISSION_BASE_FIELDS,
        string="Base du pourcentage",
        help="What the rate applies to. A closed list, because « percentage of what » "
             "is the most common source of commission disputes.",
    )
    custom_base_amount = fields.Monetary(
        string="Base saisie", currency_field="currency_id",
    )

    computed_amount = fields.Monetary(
        string="Montant",
        currency_field="currency_id",
        compute="_compute_amount",
        store=True,
        help="Resolved once, so the figure does not depend on which code path read it.",
    )
    conversion_rate = fields.Float(
        string="Taux vers la devise d'analyse",
        digits=(16, 6),
        help="Used only when the opportunity's rate source is manual.",
    )

    is_settled = fields.Boolean(string="Réglée", default=False)
    settlement_date = fields.Date(string="Date de règlement")
    notes = fields.Text(string="Notes")

    @api.depends(
        "basis", "fixed_amount", "rate", "base_field", "custom_base_amount",
        "opportunity_id.sale_subtotal", "opportunity_id.purchase_subtotal",
    )
    def _compute_amount(self):
        """Resolve the amount from the basis.

        A percentage of a base in a different currency is not computed: the base comes
        from the opportunity's own sale or purchase currency, and multiplying it by a
        rate then labelling the result with this record's currency would silently
        assert a 1:1 exchange. ``computed_amount`` stays at zero, and the
        opportunity's ``margin_blocker`` reports it.
        """
        for commission in self:
            if commission.basis == "fixed":
                commission.computed_amount = commission.fixed_amount
                continue

            deal = commission.opportunity_id
            if commission.base_field == "custom":
                base = commission.custom_base_amount
            elif commission.base_field == "sale_subtotal":
                base = (
                    deal.sale_subtotal
                    if deal.sale_currency_id == commission.currency_id
                    else 0.0
                )
            elif commission.base_field == "purchase_subtotal":
                base = (
                    deal.purchase_subtotal
                    if deal.purchase_currency_id == commission.currency_id
                    else 0.0
                )
            else:
                base = 0.0
            commission.computed_amount = base * commission.rate

    @api.constrains("basis", "rate", "base_field", "fixed_amount",
                    "custom_base_amount", "currency_id")
    def _check_basis_is_complete(self):
        for commission in self:
            if commission.basis == "fixed":
                if commission.fixed_amount <= 0:
                    raise ValidationError(
                        _(
                            "La commission « %s » est à montant fixe : renseignez un "
                            "montant strictement positif.",
                            commission.name or _("sans libellé"),
                        )
                    )
                continue

            if commission.rate <= 0:
                raise ValidationError(
                    _(
                        "La commission « %s » est en pourcentage : renseignez un taux "
                        "strictement positif (0,03 pour 3 %%).",
                        commission.name or _("sans libellé"),
                    )
                )
            if not commission.base_field:
                raise ValidationError(
                    _(
                        "La commission « %s » n'indique pas sur quelle base porte le "
                        "pourcentage. « Pourcentage de quoi » est la première source "
                        "de litige sur une commission.",
                        commission.name or _("sans libellé"),
                    )
                )
            if (commission.base_field == "custom"
                    and commission.custom_base_amount <= 0):
                raise ValidationError(
                    _(
                        "La commission « %s » a une base saisie nulle.",
                        commission.name or _("sans libellé"),
                    )
                )
            deal = commission.opportunity_id
            if (commission.base_field == "sale_subtotal"
                    and deal.sale_currency_id
                    and deal.sale_currency_id != commission.currency_id):
                raise ValidationError(
                    _(
                        "La commission « %(name)s » est en %(commission)s mais porte "
                        "sur le total de vente, exprimé en %(sale)s. Un pourcentage "
                        "d'une base dans une autre devise supposerait un taux 1:1. "
                        "Alignez les devises, ou utilisez une base saisie.",
                        name=commission.name or _("sans libellé"),
                        commission=commission.currency_id.name,
                        sale=deal.sale_currency_id.name,
                    )
                )

    @api.constrains("rate")
    def _check_rate_is_a_fraction(self):
        """Catch a rate entered as 3 instead of 0,03.

        A commission of 300 % is not impossible in theory, but it is far more often a
        unit mistake — and one that would inflate every margin below it.
        """
        for commission in self:
            if commission.rate > 1.0:
                raise ValidationError(
                    _(
                        "Le taux de la commission « %(name)s » vaut %(rate)s, soit "
                        "%(percent)s %%. Le taux s'exprime en fraction : 0,03 pour "
                        "3 %%.",
                        name=commission.name or _("sans libellé"),
                        rate=commission.rate,
                        percent=round(commission.rate * 100, 2),
                    )
                )
