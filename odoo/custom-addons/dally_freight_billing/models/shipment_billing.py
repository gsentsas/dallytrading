# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DallyShipment(models.Model):
    _inherit = "dally.shipment"

    external_reference = fields.Char(index=True, copy=False)
    goods_received_on = fields.Date()
    customer_segment_snapshot = fields.Selection(
        selection=[("individual", "Individual"), ("business", "Business")],
        copy=False,
    )
    sync_source = fields.Selection(
        selection=[("legacy_xlsx", "Legacy Excel"), ("google_sheets", "Google Sheets"), ("backoffice", "Back Office")],
        copy=False,
    )
    last_sync_at = fields.Datetime(copy=False, readonly=True)
    sync_message = fields.Char(copy=False, readonly=True)

    _external_reference_unique = models.Constraint(
        "UNIQUE(company_id, external_reference)",
        "The external freight reference must be unique per company.",
    )


class DallyShipmentPackage(models.Model):
    _inherit = "dally.shipment.package"

    external_line_key = fields.Char(index=True, copy=False)
    goods_category = fields.Char()
    announced_weight_kg = fields.Float(digits=(12, 3))
    billing_method = fields.Selection(
        selection=[("real", "Actual weight"), ("volumetric", "Volumetric"), ("quote", "On quotation")],
        default="real",
        required=True,
    )
    tariff_family_id = fields.Many2one(
        "dally.freight.tariff.family",
        ondelete="restrict",
        index=True,
    )
    volumetric_ratio_kg_cbm = fields.Float(digits=(12, 3))
    billable_weight_kg = fields.Float(
        compute="_compute_billable_weight_kg",
        store=True,
        digits=(12, 3),
    )
    manual_unit_price_eur = fields.Monetary(currency_field="billing_currency_id")
    applied_unit_price_eur = fields.Monetary(currency_field="billing_currency_id", copy=False)
    billing_currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref("base.EUR"),
    )
    pricing_type_snapshot = fields.Selection(
        selection=[("standard", "Standard"), ("promotion", "Promotion"), ("special", "Special")],
        copy=False,
    )
    pricing_reason = fields.Char(copy=False)
    customs_value_xof = fields.Monetary(currency_field="customs_currency_id")
    customs_currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref("base.XOF"),
    )

    _external_line_key_unique = models.Constraint(
        "UNIQUE(external_line_key)",
        "The external freight line key must be unique.",
    )

    @api.depends("billing_method", "total_weight_kg", "total_volume_cbm", "volumetric_ratio_kg_cbm")
    def _compute_billable_weight_kg(self):
        for line in self:
            if line.billing_method == "quote":
                line.billable_weight_kg = 0.0
            elif line.billing_method == "volumetric":
                volumetric = (line.total_volume_cbm or 0.0) * (line.volumetric_ratio_kg_cbm or 0.0)
                line.billable_weight_kg = max(line.total_weight_kg or 0.0, volumetric)
            else:
                line.billable_weight_kg = line.total_weight_kg or 0.0

    @api.constrains("announced_weight_kg", "volumetric_ratio_kg_cbm", "manual_unit_price_eur", "applied_unit_price_eur", "customs_value_xof")
    def _check_non_negative_billing_values(self):
        for line in self:
            for value in (
                line.announced_weight_kg,
                line.volumetric_ratio_kg_cbm,
                line.manual_unit_price_eur,
                line.applied_unit_price_eur,
                line.customs_value_xof,
            ):
                if value and value < 0:
                    raise ValidationError("Freight billing values cannot be negative.")

    @api.constrains("manual_unit_price_eur", "pricing_reason")
    def _check_manual_price_reason(self):
        for line in self:
            if line.manual_unit_price_eur and not (line.pricing_reason or "").strip():
                raise ValidationError("A manual freight price requires a reason.")
