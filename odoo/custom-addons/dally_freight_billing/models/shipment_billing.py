# -*- coding: utf-8 -*-
"""Billing additions on the freight projection and its package lines."""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class DallyShipment(models.Model):
    _inherit = "dally.shipment"

    external_reference = fields.Char(
        string="External Freight Reference",
        index=True,
        copy=False,
        help="Operational reference coming from the historical workbook/Sheet.",
    )
    goods_received_on = fields.Date(
        string="Goods Received On",
        help="Physical drop-off date. Used as pricing date when available.",
    )
    customer_segment_snapshot = fields.Selection(
        selection=[("individual", "Individual"), ("business", "Business")],
        string="Customer Segment",
        copy=False,
        help="Snapshot used for pricing; later contact edits do not rewrite history.",
    )
    sync_source = fields.Selection(
        selection=[
            ("legacy_xlsx", "Legacy Excel"),
            ("google_sheets", "Google Sheets"),
            ("backoffice", "Back Office"),
        ],
        copy=False,
    )
    last_sync_at = fields.Datetime(copy=False, readonly=True)
    sync_message = fields.Char(copy=False, readonly=True)

    _external_reference_unique = models.Constraint(
        "UNIQUE(company_id, external_reference)",
        "The external freight reference must be unique per company.",
    )

    def _dally_billing_pricing_date(self):
        self.ensure_one()
        return self.goods_received_on or self.request_date or fields.Date.context_today(self)


class DallyShipmentPackage(models.Model):
    _inherit = "dally.shipment.package"

    external_line_key = fields.Char(
        string="External Line Key",
        index=True,
        copy=False,
        help="Idempotency key of one billable article line from the Sheet.",
    )
    goods_category = fields.Char(string="Source Product Category")
    announced_weight_kg = fields.Float(string="Announced Weight (kg)", digits=(12, 3))
    billing_method = fields.Selection(
        selection=[
            ("real", "Actual weight"),
            ("volumetric", "Volumetric"),
            ("quote", "On quotation"),
        ],
        default="real",
        required=True,
    )
    tariff_family_id = fields.Many2one(
        "dally.freight.tariff.family",
        string="Tariff Family",
        ondelete="restrict",
        index=True,
    )
    tariff_rule_id = fields.Many2one(
        "dally.freight.tariff.rule",
        string="Applied Tariff Rule",
        ondelete="restrict",
        copy=False,
        readonly=True,
    )
    tariff_applied_on = fields.Datetime(
        string="Tariff Applied On",
        copy=False,
        readonly=True,
    )
    volumetric_ratio_kg_cbm = fields.Float(
        string="Billing Volumetric Ratio (kg/CBM)",
        digits=(12, 3),
        help="Commercial ratio snapshotted when pricing is applied.",
    )
    billable_weight_kg = fields.Float(
        string="Billable Weight (kg)",
        compute="_compute_billable_weight_kg",
        store=True,
        digits=(12, 3),
    )
    manual_unit_price_eur = fields.Monetary(
        string="Manual Price / kg",
        currency_field="billing_currency_id",
        help="Overrides the tariff grid. Historical and promotional prices use this field.",
    )
    applied_unit_price_eur = fields.Monetary(
        string="Applied Price / kg",
        currency_field="billing_currency_id",
        copy=False,
        readonly=True,
    )
    transport_amount_eur = fields.Monetary(
        string="Transport Amount",
        currency_field="billing_currency_id",
        compute="_compute_transport_amount_eur",
        store=True,
    )
    billing_currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref("base.EUR"),
    )
    pricing_type_snapshot = fields.Selection(
        selection=[
            ("standard", "Standard"),
            ("promotion", "Promotion"),
            ("special", "Special"),
        ],
        string="Pricing Type",
        copy=False,
    )
    pricing_reason = fields.Char(
        string="Pricing Reason",
        copy=False,
        help="Mandatory when a manual price is used.",
    )
    customs_value_xof = fields.Monetary(
        string="Declared Customs Value",
        currency_field="customs_currency_id",
    )
    customs_currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref("base.XOF"),
    )

    _external_line_key_unique = models.Constraint(
        "UNIQUE(external_line_key)",
        "The external freight line key must be unique.",
    )

    @api.depends(
        "billing_method",
        "total_weight_kg",
        "total_volume_cbm",
        "volumetric_ratio_kg_cbm",
    )
    def _compute_billable_weight_kg(self):
        for line in self:
            if line.billing_method == "quote":
                line.billable_weight_kg = 0.0
            elif line.billing_method == "volumetric":
                volumetric = (
                    (line.total_volume_cbm or 0.0)
                    * (line.volumetric_ratio_kg_cbm or 0.0)
                )
                line.billable_weight_kg = max(
                    line.total_weight_kg or 0.0,
                    volumetric,
                )
            else:
                line.billable_weight_kg = line.total_weight_kg or 0.0

    @api.depends("billable_weight_kg", "applied_unit_price_eur", "billing_method")
    def _compute_transport_amount_eur(self):
        for line in self:
            if line.billing_method == "quote":
                line.transport_amount_eur = 0.0
            else:
                line.transport_amount_eur = (
                    (line.billable_weight_kg or 0.0)
                    * (line.applied_unit_price_eur or 0.0)
                )

    @api.constrains(
        "announced_weight_kg",
        "volumetric_ratio_kg_cbm",
        "manual_unit_price_eur",
        "applied_unit_price_eur",
        "customs_value_xof",
    )
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
                    raise ValidationError(_("Freight billing values cannot be negative."))

    @api.constrains("manual_unit_price_eur", "pricing_reason")
    def _check_manual_price_reason(self):
        for line in self:
            if line.manual_unit_price_eur and not (line.pricing_reason or "").strip():
                raise ValidationError(_("A manual freight price requires a reason."))

    def action_apply_freight_tariff(self):
        """Snapshot the current commercial tariff on each selected package line.

        A manual price always wins and is never overwritten by a future grid.
        This is how the legacy maritime rates and campaign promotions remain
        historically exact.  Without a manual price, the current dated rule is
        resolved deterministically.  Missing automatic pricing is an explicit
        error; maritime non-food is intentionally such a case.
        """
        Tariff = self.env["dally.freight.tariff.rule"]
        now = fields.Datetime.now()

        for line in self:
            shipment = line.shipment_id
            if not shipment:
                raise UserError(_("The freight line must belong to a shipment."))

            if line.manual_unit_price_eur:
                if not (line.pricing_reason or "").strip():
                    raise UserError(_("A manual freight price requires a reason."))
                pricing_type = line.pricing_type_snapshot
                if pricing_type not in ("promotion", "special"):
                    pricing_type = "special"
                line.write({
                    "applied_unit_price_eur": line.manual_unit_price_eur,
                    "tariff_rule_id": False,
                    "tariff_applied_on": now,
                    "pricing_type_snapshot": pricing_type,
                })
                continue

            if not line.tariff_family_id:
                raise UserError(_("A tariff family is required before automatic pricing."))

            rule = Tariff._find_applicable(
                transport_mode=shipment.transport_mode,
                family=line.tariff_family_id,
                customer_segment=shipment.customer_segment_snapshot,
                pricing_date=shipment._dally_billing_pricing_date(),
            )
            if not rule:
                raise UserError(
                    _(
                        "No automatic freight tariff exists for %(mode)s / %(family)s. "
                        "Enter a manual price and its reason."
                    )
                    % {
                        "mode": shipment.transport_mode,
                        "family": line.tariff_family_id.display_name,
                    }
                )

            values = {
                "applied_unit_price_eur": rule.price_per_kg_eur,
                "tariff_rule_id": rule.id,
                "tariff_applied_on": now,
                "pricing_type_snapshot": "standard",
                "pricing_reason": False,
            }
            # The ratio matters only for volumetric billing. Snapshotting it on
            # every automatic price still makes later inspection unambiguous.
            values["volumetric_ratio_kg_cbm"] = rule.volumetric_ratio_kg_cbm
            line.write(values)

        return True
