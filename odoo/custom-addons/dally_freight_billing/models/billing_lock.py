# -*- coding: utf-8 -*-
"""Freeze commercial inputs once native invoice documents exist."""

from odoo import api, models, _
from odoo.exceptions import UserError


LOCKED_SHIPMENT_FIELDS = frozenset({
    "partner_id",
    "external_reference",
    "transport_mode",
    "direction",
    "goods_received_on",
    "customer_segment_snapshot",
    "dossier_fee_eur",
    "other_fees_eur",
})

LOCKED_PACKAGE_FIELDS = frozenset({
    "shipment_id",
    "quantity",
    "unit_weight_kg",
    "length_cm",
    "width_cm",
    "height_cm",
    "unit_volume_cbm",
    "billing_method",
    "tariff_family_id",
    "volumetric_ratio_kg_cbm",
    "manual_unit_price_eur",
    "applied_unit_price_eur",
    "pricing_type_snapshot",
    "pricing_reason",
    "customs_value_xof",
})


def _normalised_current_value(record, field_name):
    value = record[field_name]
    if hasattr(value, "id"):
        return value.id or False
    return value


def _same_value(record, field_name, new_value):
    current = _normalised_current_value(record, field_name)
    if current in (None, ""):
        current = False
    if new_value in (None, ""):
        new_value = False
    return current == new_value


def _actual_changes(record, vals, protected):
    return {
        field_name
        for field_name in protected
        if not _same_value(record, field_name, vals[field_name])
    }


class DallyShipment(models.Model):
    _inherit = "dally.shipment"

    def write(self, vals):
        protected = LOCKED_SHIPMENT_FIELDS.intersection(vals)
        if protected:
            offenders = []
            changed_fields = set()
            for shipment in self.filtered("billing_locked"):
                changes = _actual_changes(shipment, vals, protected)
                if changes:
                    offenders.append(shipment.display_name)
                    changed_fields.update(changes)
            if offenders:
                raise UserError(
                    _(
                        "Freight billing is locked for %(references)s. Reset the "
                        "draft billing documents before changing: %(fields)s."
                    )
                    % {
                        "references": ", ".join(offenders),
                        "fields": ", ".join(sorted(changed_fields)),
                    }
                )
        return super().write(vals)


class DallyShipmentPackage(models.Model):
    _inherit = "dally.shipment.package"

    @api.model_create_multi
    def create(self, vals_list):
        shipment_ids = {
            vals.get("shipment_id")
            for vals in vals_list
            if vals.get("shipment_id")
        }
        if shipment_ids:
            locked = self.env["dally.shipment"].browse(shipment_ids).filtered("billing_locked")
            if locked:
                raise UserError(
                    _("Cannot add freight lines while billing is locked. Reset the draft billing first.")
                )
        return super().create(vals_list)

    def write(self, vals):
        protected = LOCKED_PACKAGE_FIELDS.intersection(vals)
        if protected:
            for line in self.filtered(lambda item: item.shipment_id.billing_locked):
                if _actual_changes(line, vals, protected):
                    raise UserError(
                        _(
                            "Cannot change invoiced freight article data while billing "
                            "is locked. Reset the draft billing first."
                        )
                    )
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda line: line.shipment_id.billing_locked):
            raise UserError(
                _("Cannot delete freight lines while billing is locked. Reset the draft billing first.")
            )
        return super().unlink()
