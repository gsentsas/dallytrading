# -*- coding: utf-8 -*-
"""Freight file — the business source of truth for DallyTrading shipments.

Design notes worth stating:

* **Nothing native is duplicated.** The customer is a ``res.partner``, the quote a
  ``sale.order``, the invoice an ``account.move`` (§70). This model adds only what
  freight needs and Odoo does not model: transport mode, route, cargo, chargeable
  weight, operational milestones.

* **Sensitive fields are group-restricted at ORM level.** ``supplier_cost`` and
  ``margin`` carry ``groups=``, so Odoo removes them from the recordset for any
  user outside Finance. That is a layer *below* the API's field allowlist: even a
  coding mistake in a controller cannot read what the ORM never loaded. It is not
  a substitute for the allowlist — ``sudo()`` bypasses field groups — which is
  exactly why the tracking API deliberately does not use ``sudo()``.

* **Totals are computed from packages but stay editable.** A freight operator
  often knows the total before entering each package. ``compute + store +
  readonly=False`` keeps a manual value until a package line changes.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

#: Shipment lifecycle (§20). Ordered: the sequence is the operational reality of a
#: freight file, and the form status bar relies on it.
#: French labels live in i18n/fr.po — these are the source strings.
SHIPMENT_STATES = [
    ("draft", "Draft"),
    ("request_received", "Request Received"),
    ("awaiting_goods", "Awaiting Goods"),
    ("goods_received", "Goods Received"),
    ("preparing", "Preparing"),
    ("ready", "Ready to Ship"),
    ("departed", "Departed"),
    ("in_transit", "In Transit"),
    ("arrived", "Arrived"),
    ("customs", "Customs Clearance"),
    ("available", "Available for Pickup"),
    ("out_for_delivery", "Out for Delivery"),
    ("delivered", "Delivered"),
    ("cancelled", "Cancelled"),
]

#: States that close a file. Reached, nothing further is expected.
CLOSING_STATES = ("delivered", "cancelled")

TRANSPORT_MODES = [
    ("sea", "Sea Freight"),
    ("air", "Air Freight"),
    ("road", "Road Transport"),
    ("vehicle", "Vehicle Transport"),
    ("groupage", "Groupage"),
    ("other", "Other"),
]

#: Volumetric conversion, kg per m³, used to derive chargeable weight.
#:
#: Freight is billed on whichever is greater: actual weight or volume converted at
#: the mode's ratio. Getting this wrong under-quotes light bulky cargo, which is
#: most consumer goods — the single most common quoting error in this business.
#: Air uses the IATA 1:167 ratio; LCL sea and groupage bill 1 m³ as 1 tonne.
VOLUMETRIC_RATIOS = {
    "air": 167.0,
    "road": 333.0,
    "groupage": 1000.0,
    "sea": 1000.0,
}


class DallyShipment(models.Model):
    _name = "dally.shipment"
    _description = "DallyTrading Shipment"
    _inherit = ["dally.reference.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    #: Feeds the mixin. Produces DT-SHP-YYYY-NNNNNN.
    _dally_sequence_code = "dally.shipment"

    # ─── Identification ──────────────────────────────────────────────
    # `reference` comes from dally.reference.mixin and is the public tracking
    # reference the customer quotes.

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        help="Owning company. Drives the multi-company record rule.",
    )
    active = fields.Boolean(default=True)

    # ─── Parties ─────────────────────────────────────────────────────
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        required=True,
        index=True,
        tracking=True,
        help="The customer this file belongs to. A plain res.partner (§70).",
    )
    consignee_id = fields.Many2one(
        comodel_name="res.partner",
        string="Consignee",
        help="Who receives the goods, when it is not the customer.",
    )
        # Restreint au personnel interne. Un utilisateur portail lit ses propres
        # dossiers ; ce champ, lui, expose l'identité d'un salarié et ne doit
        # jamais lui être chargé par l'ORM, même sur un record qui lui appartient.
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Responsible",
        default=lambda self: self.env.user,
        index=True,
        tracking=True,
        domain=[("share", "=", False)],
        groups="dally_core.group_dally_readonly",
    )

    # ─── Service and mode ────────────────────────────────────────────
    service_type_id = fields.Many2one(
        comodel_name="dally.service.type",
        string="Service",
        ondelete="restrict",
        index=True,
    )
    transport_mode = fields.Selection(
        selection=TRANSPORT_MODES,
        string="Transport Mode",
        required=True,
        default="sea",
        index=True,
        tracking=True,
    )
    direction = fields.Selection(
        selection=[
            ("import", "Import"),
            ("export", "Export"),
            ("domestic", "Domestic"),
        ],
        string="Direction",
        required=True,
        default="import",
        index=True,
    )

    # ─── Route ───────────────────────────────────────────────────────
    origin_country_id = fields.Many2one(
        comodel_name="res.country", string="Origin Country", index=True
    )
    origin_city = fields.Char(string="Origin City")
    origin_location = fields.Char(
        string="Origin Port / Airport",
        help="Loading port, airport or terminal. Free text: codes vary by carrier.",
    )
    destination_country_id = fields.Many2one(
        comodel_name="res.country", string="Destination Country", index=True
    )
    destination_city = fields.Char(string="Destination City")
    destination_location = fields.Char(string="Destination Port / Airport")

    route_summary = fields.Char(
        string="Route",
        compute="_compute_route_summary",
        store=True,
        help="Origin → destination, for lists and the public tracking page.",
    )

    # ─── Dates ───────────────────────────────────────────────────────
    request_date = fields.Date(
        string="Request Date",
        default=fields.Date.context_today,
        tracking=True,
    )
    departure_date = fields.Date(string="Departure", tracking=True)
    estimated_arrival = fields.Date(string="ETA", tracking=True)
    actual_arrival = fields.Date(string="Actual Arrival", tracking=True)
    delivery_date = fields.Date(string="Delivered On", tracking=True)

    is_late = fields.Boolean(
        string="Late",
        compute="_compute_is_late",
        search="_search_is_late",
        help="Past its ETA and not yet arrived.",
    )

    # ─── Cargo ───────────────────────────────────────────────────────
    goods_description = fields.Text(
        string="Goods Description",
        help="Nature of the goods. Shown to the customer on the tracking page.",
    )
    package_ids = fields.One2many(
        comodel_name="dally.shipment.package",
        inverse_name="shipment_id",
        string="Packages",
    )

    # compute + store + readonly=False: an operator can type a total before the
    # detail exists, and it is kept until a package line changes.
    packages_count = fields.Integer(
        string="Packages",
        compute="_compute_cargo_totals",
        store=True,
        readonly=False,
        tracking=True,
    )
    weight_kg = fields.Float(
        string="Gross Weight (kg)",
        digits=(12, 3),
        compute="_compute_cargo_totals",
        store=True,
        readonly=False,
        tracking=True,
    )
    volume_cbm = fields.Float(
        string="Volume (CBM)",
        digits=(12, 4),
        compute="_compute_cargo_totals",
        store=True,
        readonly=False,
        tracking=True,
        help="Cubic metres. Derived from package dimensions when available.",
    )
    chargeable_weight_kg = fields.Float(
        string="Chargeable Weight (kg)",
        digits=(12, 3),
        compute="_compute_chargeable_weight",
        store=True,
        help="The greater of gross weight and volumetric weight for the mode. "
             "This is what freight is billed on.",
    )

    container_type = fields.Selection(
        selection=[
            ("none", "Not Containerised"),
            ("lcl", "LCL / Groupage"),
            ("20ft", "20' Container"),
            ("40ft", "40' Container"),
            ("40hc", "40' High Cube"),
            ("reefer", "Reefer"),
            ("other", "Other"),
        ],
        string="Container Type",
        default="none",
    )
    container_number = fields.Char(
        string="Container Number",
        help="Container or trailer number. Visible to the customer.",
    )
    carrier_name = fields.Char(string="Carrier")
    carrier_tracking_number = fields.Char(
        string="Carrier Tracking Number",
        help="Bill of lading, AWB or carrier reference. Visible to the customer, "
             "so they can also follow the shipment with the carrier directly.",
    )

    declared_value = fields.Monetary(
        string="Declared Value",
        currency_field="currency_id",
        help="Value declared by the customer, for customs and insurance.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
    )

    # ─── Commercial links (native models reused) ─────────────────────
    sale_order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Sales Order",
        index=True,
        help="Linked quotation or order. Pricing lives there, not here.",
    )
    invoice_id = fields.Many2one(
        comodel_name="account.move",
        string="Invoice",
        domain=[("move_type", "in", ("out_invoice", "out_refund"))],
    )

    # ─── Restricted: never leaves Finance ────────────────────────────
    # `groups=` makes the ORM strip these for any user outside the group. The
    # tracking API runs as an integration user without it, so these columns are
    # not merely filtered from the response — they are never loaded.
    supplier_cost = fields.Monetary(
        string="Supplier Cost",
        currency_field="currency_id",
        groups="dally_core.group_dally_finance",
        help="Cost paid to carriers and agents. Never exposed publicly.",
    )
    margin = fields.Monetary(
        string="Margin",
        currency_field="currency_id",
        compute="_compute_margin",
        store=True,
        groups="dally_core.group_dally_finance",
        help="Sales amount minus supplier cost. Never exposed publicly.",
    )
    internal_notes = fields.Text(
        string="Internal Notes",
        groups="dally_core.group_dally_readonly",
        help="Internal working notes. Never exposed publicly, in any circumstance.",
    )

    # ─── Lifecycle ───────────────────────────────────────────────────
    state = fields.Selection(
        selection=SHIPMENT_STATES,
        string="Status",
        default="draft",
        required=True,
        index=True,
        tracking=True,
        copy=False,
    )
    state_changed_on = fields.Datetime(
        string="Status Changed",
        readonly=True,
        copy=False,
        help="When the status last changed. Feeds the public 'last update'.",
    )

    _dally_shipment_weight_positive = models.Constraint(
        'CHECK(weight_kg >= 0)',
        'Gross weight cannot be negative.',
    )
    _dally_shipment_volume_positive = models.Constraint(
        'CHECK(volume_cbm >= 0)',
        'Volume cannot be negative.',
    )
    _dally_shipment_packages_positive = models.Constraint(
        'CHECK(packages_count >= 0)',
        'The number of packages cannot be negative.',
    )

    # ─── Computes ────────────────────────────────────────────────────

    @api.depends(
        "origin_city", "origin_country_id", "origin_location",
        "destination_city", "destination_country_id", "destination_location",
    )
    def _compute_route_summary(self):
        for shipment in self:
            origin = shipment._format_place(
                shipment.origin_location, shipment.origin_city,
                shipment.origin_country_id,
            )
            destination = shipment._format_place(
                shipment.destination_location, shipment.destination_city,
                shipment.destination_country_id,
            )
            if origin and destination:
                shipment.route_summary = "%s → %s" % (origin, destination)
            else:
                shipment.route_summary = origin or destination or ""

    @staticmethod
    def _format_place(location, city, country):
        """Most specific place available, without repeating a value."""
        parts = []
        for value in (location, city):
            text = (value or "").strip()
            if text and text.lower() not in {p.lower() for p in parts}:
                parts.append(text)
        if country:
            parts.append(country.name)
        return ", ".join(parts)

    @api.depends(
        "package_ids", "package_ids.quantity",
        "package_ids.total_weight_kg", "package_ids.total_volume_cbm",
    )
    def _compute_cargo_totals(self):
        for shipment in self:
            packages = shipment.package_ids
            if packages:
                shipment.packages_count = int(sum(packages.mapped("quantity")))
                shipment.weight_kg = sum(packages.mapped("total_weight_kg"))
                shipment.volume_cbm = sum(packages.mapped("total_volume_cbm"))
            else:
                # No detail: keep whatever was entered by hand. Assigning the
                # current value is required — a compute must assign every field.
                shipment.packages_count = shipment.packages_count or 0
                shipment.weight_kg = shipment.weight_kg or 0.0
                shipment.volume_cbm = shipment.volume_cbm or 0.0

    @api.depends("weight_kg", "volume_cbm", "transport_mode")
    def _compute_chargeable_weight(self):
        for shipment in self:
            ratio = VOLUMETRIC_RATIOS.get(shipment.transport_mode)
            if not ratio or not shipment.volume_cbm:
                shipment.chargeable_weight_kg = shipment.weight_kg
                continue
            volumetric = shipment.volume_cbm * ratio
            shipment.chargeable_weight_kg = max(shipment.weight_kg, volumetric)

    @api.depends("sale_order_id.amount_untaxed", "supplier_cost")
    def _compute_margin(self):
        for shipment in self:
            revenue = shipment.sale_order_id.amount_untaxed or 0.0
            shipment.margin = revenue - (shipment.supplier_cost or 0.0)

    def _compute_is_late(self):
        today = fields.Date.context_today(self)
        for shipment in self:
            shipment.is_late = bool(
                shipment.estimated_arrival
                and not shipment.actual_arrival
                and shipment.state not in CLOSING_STATES
                and shipment.estimated_arrival < today
            )

    def _search_is_late(self, operator, value):
        """Make `is_late` filterable, so the list view can show late files.

        A computed non-stored field is not searchable unless a search method is
        provided, and "what is late" is the first question an operations manager
        asks in the morning.
        """
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(_("Unsupported search on 'Late'."))

        late_domain = [
            ("estimated_arrival", "<", fields.Date.context_today(self)),
            ("actual_arrival", "=", False),
            ("state", "not in", list(CLOSING_STATES)),
        ]
        looking_for_late = (operator == "=") == value
        if looking_for_late:
            return late_domain
        return [
            "|", "|", "|",
            ("estimated_arrival", "=", False),
            ("estimated_arrival", ">=", fields.Date.context_today(self)),
            ("actual_arrival", "!=", False),
            ("state", "in", list(CLOSING_STATES)),
        ]

    # ─── Constraints ─────────────────────────────────────────────────

    @api.constrains("departure_date", "estimated_arrival", "actual_arrival")
    def _check_date_order(self):
        """Dates must tell a coherent story.

        An arrival before departure is always a data-entry error, and it would be
        shown to the customer on the tracking page.
        """
        for shipment in self:
            if (
                shipment.departure_date
                and shipment.actual_arrival
                and shipment.actual_arrival < shipment.departure_date
            ):
                raise ValidationError(
                    _("The actual arrival cannot precede the departure date.")
                )
            if (
                shipment.departure_date
                and shipment.estimated_arrival
                and shipment.estimated_arrival < shipment.departure_date
            ):
                raise ValidationError(
                    _("The ETA cannot precede the departure date.")
                )

    @api.constrains("consignee_id", "partner_id")
    def _check_consignee(self):
        for shipment in self:
            if shipment.consignee_id and shipment.consignee_id == shipment.partner_id:
                raise ValidationError(
                    _("Leave the consignee empty when it is the customer itself.")
                )

    # ─── Writes ──────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("state") and vals["state"] != "draft":
                vals.setdefault("state_changed_on", fields.Datetime.now())
        return super().create(vals_list)

    def write(self, vals):
        if "state" in vals:
            vals["state_changed_on"] = fields.Datetime.now()
            self._apply_state_side_effects(vals["state"])
        return super().write(vals)

    def _apply_state_side_effects(self, new_state):
        """Fill the obvious dates when a milestone is reached.

        Operators forget to set them, and an empty arrival date on a delivered
        shipment makes reporting wrong. Never overwrite a value already there.
        """
        today = fields.Date.context_today(self)
        for shipment in self:
            if new_state == "departed" and not shipment.departure_date:
                shipment.departure_date = today
            elif new_state == "arrived" and not shipment.actual_arrival:
                shipment.actual_arrival = today
            elif new_state == "delivered":
                if not shipment.actual_arrival:
                    shipment.actual_arrival = today
                if not shipment.delivery_date:
                    shipment.delivery_date = today

    def unlink(self):
        """Only a draft or cancelled file may be deleted.

        A shipment that has moved is an operational record the customer has been
        told about; it is archived, not erased (§87).
        """
        for shipment in self:
            if shipment.state not in ("draft", "cancelled"):
                raise UserError(
                    _(
                        "Shipment %(reference)s is in progress and cannot be "
                        "deleted. Cancel it, or archive it instead.",
                        reference=shipment.reference,
                    )
                )
        return super().unlink()

    # ─── Actions ─────────────────────────────────────────────────────

    def action_set_state(self, new_state):
        """Move to a state, refusing an unknown value."""
        valid = dict(SHIPMENT_STATES)
        if new_state not in valid:
            raise UserError(_("Unknown status '%s'.", new_state))
        self.write({"state": new_state})
        return True

    def action_cancel(self):
        for shipment in self:
            if shipment.state == "delivered":
                raise UserError(
                    _("A delivered shipment cannot be cancelled.")
                )
        return self.action_set_state("cancelled")

    def action_view_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": self.sale_order_id.id,
            "view_mode": "form",
        }
