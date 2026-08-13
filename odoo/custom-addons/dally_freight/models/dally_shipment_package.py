# -*- coding: utf-8 -*-
"""Package lines of a shipment.

Freight is quoted on measurements, so the detail matters: a customer who declares
"3 pallets" and a customer who declares 3 pallets of 120 × 100 × 150 cm are
quoted very differently. These lines let volume — and therefore chargeable
weight — be derived instead of guessed.

Lines are optional. A file can carry only its totals when the detail is not yet
known, which is the normal state of a shipment at quotation time.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

PACKAGE_TYPES = [
    ("parcel", "Parcel"),
    ("pallet", "Pallet"),
    ("crate", "Crate"),
    ("bag", "Bag"),
    ("drum", "Drum"),
    ("container", "Container"),
    ("vehicle", "Vehicle"),
    ("other", "Other"),
]

#: cm³ in one m³. Dimensions are captured in centimetres because that is how
#: shippers measure; volume is expressed in CBM because that is how it is billed.
CM3_PER_M3 = 1_000_000.0


class DallyShipmentPackage(models.Model):
    _name = "dally.shipment.package"
    _description = "DallyTrading Shipment Package"
    _order = "shipment_id, sequence, id"

    shipment_id = fields.Many2one(
        comodel_name="dally.shipment",
        string="Shipment",
        required=True,
        ondelete="cascade",
        index=True,
    )
    # Denormalised from the parent so the multi-company record rule can apply to
    # lines directly, without a join through the shipment on every read.
    company_id = fields.Many2one(
        related="shipment_id.company_id",
        store=True,
        index=True,
        readonly=True,
    )
    sequence = fields.Integer(string="Order", default=10)

    package_type = fields.Selection(
        selection=PACKAGE_TYPES,
        string="Type",
        required=True,
        default="parcel",
    )
    description = fields.Char(string="Description")

    quantity = fields.Integer(string="Quantity", required=True, default=1)

    unit_weight_kg = fields.Float(
        string="Unit Weight (kg)",
        digits=(12, 3),
        help="Gross weight of one unit of this type.",
    )
    length_cm = fields.Float(string="Length (cm)", digits=(10, 1))
    width_cm = fields.Float(string="Width (cm)", digits=(10, 1))
    height_cm = fields.Float(string="Height (cm)", digits=(10, 1))

    unit_volume_cbm = fields.Float(
        string="Unit Volume (CBM)",
        digits=(12, 4),
        compute="_compute_volumes",
        store=True,
        readonly=False,
        help="Derived from the dimensions. Can be set directly for an irregular "
             "shape whose bounding box would overstate the volume.",
    )
    total_weight_kg = fields.Float(
        string="Total Weight (kg)",
        digits=(12, 3),
        compute="_compute_totals",
        store=True,
    )
    total_volume_cbm = fields.Float(
        string="Total Volume (CBM)",
        digits=(12, 4),
        compute="_compute_totals",
        store=True,
    )

    _dally_package_quantity_positive = models.Constraint(
        'CHECK(quantity > 0)',
        'A package line must have a quantity of at least 1.',
    )
    _dally_package_weight_positive = models.Constraint(
        'CHECK(unit_weight_kg >= 0)',
        'Unit weight cannot be negative.',
    )

    @api.depends("length_cm", "width_cm", "height_cm")
    def _compute_volumes(self):
        for line in self:
            if line.length_cm and line.width_cm and line.height_cm:
                line.unit_volume_cbm = (
                    line.length_cm * line.width_cm * line.height_cm
                ) / CM3_PER_M3
            else:
                # Incomplete dimensions: keep any manually entered volume rather
                # than zeroing what an operator typed on purpose.
                line.unit_volume_cbm = line.unit_volume_cbm or 0.0

    @api.depends("quantity", "unit_weight_kg", "unit_volume_cbm")
    def _compute_totals(self):
        for line in self:
            line.total_weight_kg = (line.quantity or 0) * (line.unit_weight_kg or 0.0)
            line.total_volume_cbm = (line.quantity or 0) * (line.unit_volume_cbm or 0.0)

    @api.constrains("length_cm", "width_cm", "height_cm")
    def _check_dimensions(self):
        for line in self:
            for value, label in (
                (line.length_cm, _("length")),
                (line.width_cm, _("width")),
                (line.height_cm, _("height")),
            ):
                if value and value < 0:
                    raise ValidationError(
                        _("The %s cannot be negative.", label)
                    )

    def name_get(self):
        result = []
        for line in self:
            label = dict(PACKAGE_TYPES).get(line.package_type, "")
            name = "%s × %s" % (line.quantity, label)
            if line.description:
                name = "%s — %s" % (name, line.description)
            result.append((line.id, name))
        return result
