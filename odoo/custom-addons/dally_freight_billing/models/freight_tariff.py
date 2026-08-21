# -*- coding: utf-8 -*-
from odoo import api, fields, models
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
        selection=[("all", "All"), ("individual", "Individual"), ("business", "Business")],
        default="all",
        required=True,
    )
    billing_method = fields.Selection(
        selection=[("real", "Actual weight"), ("volumetric", "Volumetric"), ("quote", "On quotation")],
        default="real",
        required=True,
    )
    price_per_kg_eur = fields.Monetary(currency_field="currency_id")
    volumetric_ratio_kg_cbm = fields.Float(digits=(12, 3))
    date_from = fields.Date()
    date_to = fields.Date()
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref("base.EUR"),
    )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rule in self:
            if rule.date_from and rule.date_to and rule.date_to < rule.date_from:
                raise ValidationError("Tariff end date cannot precede start date.")

    @api.constrains("price_per_kg_eur", "volumetric_ratio_kg_cbm")
    def _check_non_negative(self):
        for rule in self:
            if rule.price_per_kg_eur < 0 or rule.volumetric_ratio_kg_cbm < 0:
                raise ValidationError("Freight tariff amounts and ratios cannot be negative.")
