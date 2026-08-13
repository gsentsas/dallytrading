# -*- coding: utf-8 -*-
"""Trade costs — everything between the purchase price and the real cost.

## Why costs are lines and not a single field

"Freight, customs and insurance came to 4 200 €" is not a usable record. When the margin
turns out wrong, the question is *which* cost was underestimated, and a single total
cannot answer it. Categorised lines can, and they are also what makes a cost comparable
across deals.

## Why the model is entirely internal

A cost line is the purchase side of the business. Its ACL excludes the commercial and
read-only groups altogether, and it has no public endpoint and appears in no DTO.
Disclosing a landed cost would require writing an endpoint on purpose — which is the
point of separating the model rather than filtering a field.

## Currency

Each cost keeps the currency it was incurred in. Customs paid in XOF and freight paid in
USD are not converted on entry, because converting on entry destroys the original figure
and hides the rate used. The conversion happens once, on the opportunity, against a
declared rate and date.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

#: Cost categories.
#:
#: Deliberately a closed list rather than free text: free text makes the same cost
#: appear as "douane", "Douanes" and "customs", and reporting across deals becomes
#: impossible. "other" exists as the honest escape hatch, with a mandatory description.
COST_CATEGORIES = [
    ("goods", "Marchandise"),
    ("freight", "Transport"),
    ("insurance", "Assurance"),
    ("customs", "Douane et taxes"),
    ("handling", "Manutention et magasinage"),
    ("inspection", "Inspection et certification"),
    ("finance", "Frais financiers et bancaires"),
    ("logistics_admin", "Documentation et administratif"),
    ("other", "Autre"),
]


class DallyTradeCost(models.Model):
    _name = "dally.trade.cost"
    _description = "DallyTrading Trade Cost"
    _order = "opportunity_id, category, id"

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

    category = fields.Selection(
        selection=COST_CATEGORIES,
        string="Catégorie",
        required=True,
        index=True,
        default="freight",
    )
    name = fields.Char(
        string="Libellé",
        required=True,
        help="What this cost actually is. Required even when the category is obvious: "
             "« transport » does not distinguish pre-carriage from main freight.",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Prestataire",
        index=True,
        help="Who charged it. Optional at estimate stage, and the reason a cost can be "
             "reconciled against an invoice later.",
    )

    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Devise",
        required=True,
        default=lambda self: self.env.company.currency_id,
        help="The currency the cost was incurred in, kept as incurred. Converting on "
             "entry would destroy the original figure and hide the rate used.",
    )
    amount = fields.Monetary(
        string="Montant", currency_field="currency_id", required=True,
    )
    conversion_rate = fields.Float(
        string="Taux vers la devise d'analyse",
        digits=(16, 6),
        help="Used only when the opportunity's rate source is manual. One unit of this "
             "cost's currency expressed in the analysis currency.",
    )

    is_estimate = fields.Boolean(
        string="Estimation",
        default=True,
        help="An estimate until an invoice confirms it. Kept explicit so a margin "
             "built on estimates is not mistaken for a settled one.",
    )
    invoice_reference = fields.Char(string="Référence de facture")
    incurred_date = fields.Date(string="Date")
    notes = fields.Text(string="Notes")

    @api.constrains("amount")
    def _check_amount(self):
        for cost in self:
            if cost.amount < 0:
                raise ValidationError(
                    _(
                        "Le coût « %s » ne peut pas être négatif. Un remboursement se "
                        "saisit comme une ligne distincte, pas comme un coût négatif "
                        "qui masquerait le coût d'origine.",
                        cost.name or _("sans libellé"),
                    )
                )

    @api.constrains("conversion_rate")
    def _check_conversion_rate(self):
        for cost in self:
            if cost.conversion_rate < 0:
                raise ValidationError(
                    _("Un taux de conversion ne peut pas être négatif.")
                )
