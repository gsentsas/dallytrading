# -*- coding: utf-8 -*-
"""Candidate suppliers on a sourcing request.

This model is a **participation**, not a supplier database. The supplier itself is a
plain ``res.partner``: building a second, parallel list of suppliers is how a company
ends up with two addresses for the same factory and no idea which is current.

What is stored here is what belongs to *this* search: was the supplier contacted, did
they reply, were they verified, were they shortlisted. The same partner can appear on
twenty requests with a different outcome each time.

## Why a few contact fields are duplicated anyway

``contact_name``, ``contact_email`` and ``contact_phone`` are a deliberate snapshot.
A factory's sales representative changes; the person who quoted this price on this
request is part of the record of that quote. The partner keeps the current details,
these keep the historical ones — and they are optional, so nothing forces an operator
to retype what ``res.partner`` already holds.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

#: Where a supplier stands in this particular search.
#:
#: Deliberately short. This tracks a sourcing exercise, not a supplier relationship —
#: turning it into a second CRM pipeline would duplicate what the CRM already does.
SUPPLIER_STATUSES = [
    ("identified", "Identified"),
    ("contacted", "Contacted"),
    ("awaiting_reply", "Awaiting Reply"),
    ("qualified", "Qualified"),
    ("offer_received", "Offer Received"),
    ("shortlisted", "Shortlisted"),
    ("selected", "Selected"),
    ("rejected", "Rejected"),
]


class DallySourcingSupplier(models.Model):
    _name = "dally.sourcing.supplier"
    _description = "DallyTrading Sourcing Candidate Supplier"
    _order = "request_id, sequence, id"
    _rec_name = "display_name"

    request_id = fields.Many2one(
        comodel_name="dally.sourcing.request",
        string="Sourcing Request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    # Denormalised from the parent so the multi-company record rule applies to this
    # model directly, without joining through the request on every read.
    company_id = fields.Many2one(
        related="request_id.company_id", store=True, index=True, readonly=True,
    )
    sequence = fields.Integer(string="Order", default=10)

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Supplier",
        required=True,
        ondelete="restrict",
        index=True,
        help="The supplier as a standard contact. Tick 'Is a Vendor' on the partner "
             "to make it selectable in purchase orders.",
    )
    display_name = fields.Char(compute="_compute_display_name_field", store=True)

    country_id = fields.Many2one(
        comodel_name="res.country",
        string="Country",
        compute="_compute_country",
        store=True,
        readonly=False,
        index=True,
        help="Taken from the supplier's contact by default, and overridable: a "
             "trading company may be registered elsewhere than its factory.",
    )

    # Historical snapshot — see the module docstring.
    contact_name = fields.Char(string="Contact Person")
    contact_email = fields.Char(string="Contact Email")
    contact_phone = fields.Char(string="Contact Phone")
    website = fields.Char(string="Website")

    status = fields.Selection(
        selection=SUPPLIER_STATUSES,
        string="Status",
        default="identified",
        required=True,
        index=True,
    )

    verified = fields.Boolean(
        string="Verified",
        help="Checks were carried out on this supplier. What was checked belongs in "
             "the verification notes: a bare tick tells a colleague nothing.",
    )
    verification_date = fields.Date(string="Verified On")
    verification_notes = fields.Text(
        string="Verification Notes",
        help="What was verified and what was found, including anything that looked "
             "doubtful. Sourcing does not eliminate risk; it documents it.",
    )

    minimum_order_quantity = fields.Float(string="MOQ", digits=(16, 3))
    lead_time_days = fields.Integer(string="Lead Time (days)")

    internal_notes = fields.Text(string="Internal Notes")

    offer_ids = fields.One2many(
        comodel_name="dally.sourcing.offer",
        inverse_name="supplier_id",
        string="Offers",
    )
    offer_count = fields.Integer(string="Offers", compute="_compute_offer_count")

    _dally_sourcing_supplier_uniq = models.Constraint(
        'UNIQUE(request_id, partner_id)',
        'This supplier is already a candidate on this sourcing request.',
    )
    _dally_sourcing_supplier_moq_positive = models.Constraint(
        'CHECK(minimum_order_quantity >= 0)',
        'The minimum order quantity cannot be negative.',
    )
    _dally_sourcing_supplier_lead_time_positive = models.Constraint(
        'CHECK(lead_time_days >= 0)',
        'The lead time cannot be negative.',
    )

    @api.depends("partner_id", "request_id.reference")
    def _compute_display_name_field(self):
        for candidate in self:
            candidate.display_name = candidate.partner_id.display_name or _("Supplier")

    @api.depends("partner_id")
    def _compute_country(self):
        for candidate in self:
            # readonly=False: recomputes when the partner changes, but an operator's
            # manual value survives until then.
            if candidate.partner_id.country_id:
                candidate.country_id = candidate.partner_id.country_id
            else:
                candidate.country_id = candidate.country_id

    @api.depends("offer_ids")
    def _compute_offer_count(self):
        for candidate in self:
            candidate.offer_count = len(candidate.offer_ids)

    @api.constrains("verified", "verification_date")
    def _check_verification(self):
        """A verification with no date is not a verification.

        Six months later, "verified" without a date says nothing about whether the
        check is still current.
        """
        for candidate in self:
            if candidate.verified and not candidate.verification_date:
                raise ValidationError(
                    _(
                        "Supplier %s is marked as verified but has no verification "
                        "date. Without one, nobody can tell whether the check is "
                        "still current.",
                        candidate.partner_id.display_name,
                    )
                )

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        """Prefill the snapshot from the partner, without overwriting entries."""
        for candidate in self:
            partner = candidate.partner_id
            if not partner:
                continue
            if not candidate.contact_email and partner.email:
                candidate.contact_email = partner.email
            if not candidate.contact_phone and partner.phone:
                candidate.contact_phone = partner.phone
            if not candidate.website and partner.website:
                candidate.website = partner.website

    # ─── Actions ─────────────────────────────────────────────────────

    def action_mark_contacted(self):
        self.write({"status": "contacted"})
        return True

    def action_mark_awaiting_reply(self):
        self.write({"status": "awaiting_reply"})
        return True

    def action_shortlist(self):
        self.write({"status": "shortlisted"})
        return True

    def action_reject(self):
        self.write({"status": "rejected"})
        return True

    def action_mark_verified(self):
        """Record a verification, stamping today's date."""
        self.write({
            "verified": True,
            "verification_date": fields.Date.context_today(self),
        })
        return True

    def action_view_offers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Offers"),
            "res_model": "dally.sourcing.offer",
            "view_mode": "list,form",
            "domain": [("supplier_id", "=", self.id)],
            "context": {
                "default_supplier_id": self.id,
                "default_request_id": self.request_id.id,
            },
        }
