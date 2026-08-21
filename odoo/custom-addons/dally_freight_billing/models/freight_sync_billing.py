# -*- coding: utf-8 -*-
"""Billing-level additions to the core Freight Sheet upsert."""

from odoo import api, models, _
from odoo.exceptions import ValidationError


class DallyFreightSyncService(models.AbstractModel):
    _inherit = "dally.freight.sync.service"

    @api.model
    def upsert(self, payload):
        data, shipment = super().upsert(payload)

        fee_values = {}
        for source, target in (
            ("dossier_fee_eur", "dossier_fee_eur"),
            ("other_fees_eur", "other_fees_eur"),
        ):
            if source in payload:
                fee_values[target] = self._freight_sync_non_negative_number(
                    payload.get(source), source
                )
        if fee_values:
            shipment.write(fee_values)

        data.update({
            "freight_amount_eur": shipment.freight_amount_eur,
            "dossier_fee_eur": shipment.dossier_fee_eur,
            "other_fees_eur": shipment.other_fees_eur,
            "billing_total_eur": shipment.billing_total_eur,
            "billing_locked": shipment.billing_locked,
            "sale_order_id": shipment.sale_order_id.id or None,
            "invoice_id": shipment.invoice_id.id or None,
            "invoice_number": shipment.invoice_id.name if shipment.invoice_id else None,
            "invoice_state": shipment.invoice_id.state if shipment.invoice_id else None,
        })
        return data, shipment

    @api.model
    def _price_line_if_ready(self, line):
        # After invoice generation an idempotent replay may re-send the exact
        # same row. Do not refresh tariff timestamps or touch pricing snapshots.
        if line.shipment_id.billing_locked:
            return "locked"
        return super()._price_line_if_ready(line)

    @staticmethod
    def _freight_sync_non_negative_number(value, field_name):
        if value in (None, "", False):
            return 0.0
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("%s must be numeric.", field_name)) from exc
        if number < 0:
            raise ValidationError(_("%s cannot be negative.", field_name))
        return number
