# -*- coding: utf-8 -*-
"""Commercial freight tariff grid.

The spreadsheet currently mixes two different concepts in formulas: the
commercial price per kilogram and the way the billable weight is obtained.  They
must stay independent.  A tariff rule answers only "what does one billable kg
cost for this mode/family/segment/date?".  The package line keeps the billing
method (actual, volumetric or quote) and snapshots the rule used.

This separation is important for history: changing tomorrow's tariff grid must
never rewrite a shipment already priced today.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class DallyFreightTariffFamily(models.Model):
    _name = "dally.freight.tariff.family"
    _description = "DallyTrading Freight Tariff Family"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The freight tariff family code must be unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code"):
                vals["code"] = vals["code"].strip().lower()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("code"):
            vals["code"] = vals["code"].strip().lower()
        return super().write(vals)


class DallyFreightTariffRule(models.Model):
    _name = "dally.freight.tariff.rule"
    _description = "DallyTrading Freight Tariff Rule"
    _order = "date_from desc, id desc"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    transport_mode = fields.Selection(
        selection=[("sea", "Sea"), ("air", "Air")],
        required=True,
        index=True,
    )
    family_id = fields.Many2one(
        "dally.freight.tariff.family",
        required=True,
        ondelete="restrict",
        index=True,
    )
    customer_segment = fields.Selection(
        selection=[
            ("all", "All"),
            ("individual", "Individual"),
            ("business", "Business"),
        ],
        default="all",
        required=True,
        index=True,
    )
    price_per_kg_eur = fields.Monetary(
        currency_field="currency_id",
        required=True,
    )
    volumetric_ratio_kg_cbm = fields.Float(
        digits=(12, 3),
        help=(
            "Commercial volumetric ratio snapshotted on a line when that line "
            "uses volumetric billing. It does not change the operational "
            "chargeable-weight calculation of dally.shipment."
        ),
    )
    date_from = fields.Date(index=True)
    date_to = fields.Date(index=True)
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref("base.EUR"),
    )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rule in self:
            if rule.date_from and rule.date_to and rule.date_to < rule.date_from:
                raise ValidationError(_("Tariff end date cannot precede start date."))

    @api.constrains("price_per_kg_eur", "volumetric_ratio_kg_cbm")
    def _check_non_negative(self):
        for rule in self:
            if rule.price_per_kg_eur < 0 or rule.volumetric_ratio_kg_cbm < 0:
                raise ValidationError(
                    _("Freight tariff amounts and ratios cannot be negative.")
                )

    @api.constrains(
        "active",
        "transport_mode",
        "family_id",
        "customer_segment",
        "date_from",
        "date_to",
    )
    def _check_no_overlapping_rules(self):
        """One deterministic automatic tariff per scope and date.

        Ambiguous grids are rejected at configuration time instead of depending
        on record creation order.  Rules for a specific customer segment may
        coexist with an ``all`` rule; resolution deliberately prefers the
        specific segment.
        """
        for rule in self.filtered("active"):
            domain = [
                ("id", "!=", rule.id),
                ("active", "=", True),
                ("transport_mode", "=", rule.transport_mode),
                ("family_id", "=", rule.family_id.id),
                ("customer_segment", "=", rule.customer_segment),
            ]
            if rule.date_from:
                domain += [
                    "|",
                    ("date_to", "=", False),
                    ("date_to", ">=", rule.date_from),
                ]
            if rule.date_to:
                domain += [
                    "|",
                    ("date_from", "=", False),
                    ("date_from", "<=", rule.date_to),
                ]
            if self.search_count(domain):
                raise ValidationError(
                    _(
                        "Another active freight tariff overlaps this mode, "
                        "family, customer segment and date range."
                    )
                )

    @api.model
    def _find_applicable(
        self,
        *,
        transport_mode,
        family,
        customer_segment=None,
        pricing_date=None,
    ):
        """Return the single applicable automatic tariff, or an empty recordset.

        The exact customer segment wins over ``all``.  Dates are inclusive.
        Missing rules are a valid configuration state: maritime non-food is
        intentionally manual in the source workbook.
        """
        if not transport_mode or not family:
            return self.browse()

        family_id = family.id if hasattr(family, "id") else int(family)
        day = fields.Date.to_date(pricing_date) if pricing_date else fields.Date.context_today(self)

        base_domain = [
            ("active", "=", True),
            ("transport_mode", "=", transport_mode),
            ("family_id", "=", family_id),
            "|",
            ("date_from", "=", False),
            ("date_from", "<=", day),
            "|",
            ("date_to", "=", False),
            ("date_to", ">=", day),
        ]

        if customer_segment in ("individual", "business"):
            exact = self.search(
                base_domain + [("customer_segment", "=", customer_segment)],
                limit=1,
            )
            if exact:
                return exact

        return self.search(
            base_domain + [("customer_segment", "=", "all")],
            limit=1,
        )
