# -*- coding: utf-8 -*-
"""Tracking behaviour added to the freight file.

This module owns the boundary between what DallyTrading knows and what the
customer is shown. The boundary is one method — ``_dally_public_payload`` — and it
is built from an explicit allowlist.

Why an allowlist and not a filter: a denylist has to be updated every time a field
is added to ``dally.shipment``, and the day someone adds ``agent_commission`` and
forgets, it is published. With an allowlist, a new field is invisible until
somebody deliberately publishes it. The test suite asserts the payload's keys are
a subset of the declared set, so the guarantee is enforced, not just intended.
"""

from odoo import _, api, fields, models

#: Every key the public tracking payload may contain. The single source of truth
#: for what leaves the server, asserted by the tests.
PUBLIC_PAYLOAD_KEYS = frozenset({
    "reference",
    "transportMode",
    "transportModeLabel",
    "origin",
    "destination",
    "status",
    "statusLabel",
    "departureDate",
    "estimatedArrival",
    "actualArrival",
    "lastUpdate",
    "carrierTrackingNumber",
    "containerNumber",
    "goodsDescription",
    "packagesCount",
    "timeline",
})

#: Fields that must never appear in a public payload, under any circumstances.
#: Asserted by the tests against the serialised output, so a future change that
#: reintroduces one fails loudly.
FORBIDDEN_PUBLIC_FIELDS = frozenset({
    "supplier_cost",
    "margin",
    "internal_notes",
    "internal_note",
    "declared_value",
    "sale_order_id",
    "invoice_id",
    "user_id",
    "partner_id",
    "consignee_id",
    "id",
})


class DallyShipment(models.Model):
    _inherit = "dally.shipment"

    event_ids = fields.One2many(
        comodel_name="dally.shipment.event",
        inverse_name="shipment_id",
        string="Tracking Events",
    )
    event_count = fields.Integer(
        string="Events", compute="_compute_event_counts"
    )
    public_event_count = fields.Integer(
        string="Visible Events", compute="_compute_event_counts"
    )
    last_public_event_id = fields.Many2one(
        comodel_name="dally.shipment.event",
        string="Last Customer-Visible Event",
        compute="_compute_last_public_event",
        help="What the customer currently sees as the latest news.",
    )

    @api.depends("event_ids", "event_ids.visible_to_customer")
    def _compute_event_counts(self):
        for shipment in self:
            events = shipment.event_ids
            shipment.event_count = len(events)
            shipment.public_event_count = len(
                events.filtered("visible_to_customer")
            )

    @api.depends("event_ids", "event_ids.visible_to_customer", "event_ids.event_date")
    def _compute_last_public_event(self):
        for shipment in self:
            visible = shipment.event_ids.filtered("visible_to_customer")
            shipment.last_public_event_id = visible.sorted(
                key=lambda e: (e.event_date, e.id), reverse=True
            )[:1]

    # ─── Automatic events on status change ───────────────────────────

    def _apply_state_side_effects(self, new_state):
        """Record an event whenever the status moves.

        Extends the freight module's hook. Without this, a shipment could be
        delivered with an empty timeline, and the customer would see nothing while
        the file said "delivered" — the most common complaint about tracking pages.

        The generated event is customer-visible only for milestones that mean
        something to a customer. Internal transitions are recorded but not
        published.
        """
        super()._apply_state_side_effects(new_state)

        publishable = self._dally_public_state_wording()
        for shipment in self:
            if shipment.state == new_state:
                # No actual transition: avoid a duplicate event when write() is
                # called with the value it already has.
                continue
            wording = publishable.get(new_state)
            self.env["dally.shipment.event"].create({
                "shipment_id": shipment.id,
                "event_date": fields.Datetime.now(),
                "status": new_state,
                "description": wording or shipment._dally_default_event_wording(new_state),
                "location": shipment._dally_event_location(new_state),
                "visible_to_customer": bool(wording),
                "is_automatic": True,
            })

    @api.model
    def _dally_public_state_wording(self):
        """Customer-facing wording per milestone.

        A state absent from this mapping produces an internal-only event. That is
        the safe direction: a new state added later is not published until someone
        writes the sentence a customer should read.
        """
        return {
            "goods_received": _("Your goods have been received at our warehouse."),
            "ready": _("Your shipment is ready to be dispatched."),
            "departed": _("Your shipment has departed."),
            "in_transit": _("Your shipment is in transit."),
            "arrived": _("Your shipment has arrived at destination."),
            "customs": _("Your shipment is undergoing customs clearance."),
            "available": _("Your shipment is available for pickup."),
            "out_for_delivery": _("Your shipment is out for delivery."),
            "delivered": _("Your shipment has been delivered."),
        }

    def _dally_default_event_wording(self, state):
        """Internal wording for states with no public sentence."""
        self.ensure_one()
        labels = dict(self._fields["state"]._description_selection(self.env))
        return _("Status changed to: %s", labels.get(state, state))

    def _dally_event_location(self, state):
        """Best guess at where a milestone happened.

        Departure happens at the origin, arrival at the destination. Everything
        else is left empty rather than guessed: a wrong location on a tracking
        page is worse than none.
        """
        self.ensure_one()
        if state in ("departed",):
            return self._format_place(
                self.origin_location, self.origin_city, self.origin_country_id
            ) or False
        if state in ("arrived", "customs", "available", "out_for_delivery", "delivered"):
            return self._format_place(
                self.destination_location, self.destination_city,
                self.destination_country_id,
            ) or False
        return False

    # ─── Public projection: the confidentiality boundary ─────────────

    @api.model
    def _dally_normalise_reference(self, reference):
        """Normalise a reference typed by a human.

        Customers read references off e-mails and phone calls: lower case, extra
        spaces, non-breaking spaces pasted from a PDF. Normalising here means the
        tracking page works for them instead of returning "not found" for a
        reference that is in fact correct.
        """
        if not reference or not isinstance(reference, str):
            return ""
        # str.split() with no argument splits on every kind of whitespace,
        # including the non-breaking space that arrives with a copy-paste from
        # a PDF invoice - the most common way a correct reference fails to match.
        return "".join(reference.split()).upper()

    @api.model
    def _dally_find_for_tracking(self, reference):
        """Resolve a public reference to a shipment, or an empty recordset.

        Only the shipment's own reference is matched. The carrier's number is
        deliberately *not* searchable here: it is not ours, it is not unique
        across carriers, and matching on it would let someone probe for shipments
        using numbers printed on any bill of lading they hold.
        """
        normalised = self._dally_normalise_reference(reference)
        if not normalised:
            return self.browse()
        return self.search([("reference", "=", normalised)], limit=1)

    def _dally_public_payload(self):
        """Build the customer-facing view of this shipment.

        Every key is named explicitly. Nothing is copied wholesale from the
        record, so a field added to ``dally.shipment`` tomorrow cannot appear here
        by accident.

        Read the list of what is *not* here: customer identity, declared value,
        supplier cost, margin, internal notes, sales order, invoice, responsible
        user, and any database id (§42, §44).
        """
        self.ensure_one()

        state_labels = dict(self._fields["state"]._description_selection(self.env))
        mode_labels = dict(
            self._fields["transport_mode"]._description_selection(self.env)
        )

        visible_events = self.event_ids.filtered("visible_to_customer")
        last_event = self.last_public_event_id

        # "Last update" is the most recent thing the customer could observe: the
        # latest published event, falling back to the status change itself.
        if last_event and last_event.event_date:
            last_update = last_event.event_date
        else:
            last_update = self.state_changed_on or self.write_date

        return {
            "reference": self.reference,
            "transportMode": self.transport_mode,
            "transportModeLabel": mode_labels.get(
                self.transport_mode, self.transport_mode
            ),
            "origin": self._format_place(
                self.origin_location, self.origin_city, self.origin_country_id
            ) or None,
            "destination": self._format_place(
                self.destination_location, self.destination_city,
                self.destination_country_id,
            ) or None,
            "status": self.state,
            "statusLabel": state_labels.get(self.state, self.state),
            "departureDate": (
                self.departure_date.isoformat() if self.departure_date else None
            ),
            "estimatedArrival": (
                self.estimated_arrival.isoformat() if self.estimated_arrival else None
            ),
            "actualArrival": (
                self.actual_arrival.isoformat() if self.actual_arrival else None
            ),
            "lastUpdate": last_update.isoformat() if last_update else None,
            # Both are the customer's own shipment identifiers, printed on their
            # documents. Sharing them lets the customer follow the shipment with
            # the carrier directly.
            "carrierTrackingNumber": self.carrier_tracking_number or None,
            "containerNumber": self.container_number or None,
            "goodsDescription": self.goods_description or None,
            "packagesCount": self.packages_count or 0,
            "timeline": visible_events._dally_public_event_payload(),
        }

    # ─── Actions ─────────────────────────────────────────────────────

    def action_view_events(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tracking Events"),
            "res_model": "dally.shipment.event",
            "view_mode": "list,form",
            "domain": [("shipment_id", "=", self.id)],
            "context": {
                "default_shipment_id": self.id,
                "default_status": self.state,
            },
        }
