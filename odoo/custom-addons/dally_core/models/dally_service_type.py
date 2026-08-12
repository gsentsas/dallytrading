# -*- coding: utf-8 -*-
"""Catalogue of DallyTrading commercial activities.

Odoo is the source of truth. The website reads this catalogue over
``GET /api/v1/services`` and keeps no business list of its own: the requirement
flags below are what drive which steps and fields the public quote form shows.

Services are designated by ``code``, never by database id. Ids differ between
environments and break the moment staging and production diverge; codes are
stable, reviewable, and validated on every inbound request.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Broad families, used for reporting and for grouping the catalogue.
SERVICE_CATEGORIES = [
    ("import_export", "Import & Export"),
    ("logistics", "Logistics & Transport"),
    ("freight", "Freight"),
    ("trade", "Trade & Commerce"),
    ("sourcing", "Sourcing"),
    ("ecommerce", "E-commerce"),
    ("agrobusiness", "Agrobusiness"),
    ("other", "Other"),
]

#: Requirement flags published to the website. Named here so the API controller
#: and the tests agree on the list without repeating it.
REQUIREMENT_FLAGS = (
    "requires_origin",
    "requires_destination",
    "requires_weight",
    "requires_volume",
    "requires_vehicle",
    "requires_budget",
    "requires_goods",
)


class DallyServiceType(models.Model):
    _name = "dally.service.type"
    _description = "DallyTrading Service Type"
    _order = "sequence, name"

    name = fields.Char(
        string="Name",
        required=True,
        translate=True,
        help="Label shown to customers on the website and in documents.",
    )
    code = fields.Char(
        string="Code",
        required=True,
        help="Stable technical identifier used by the website and the API. "
             "Never change it once published: external systems refer to it.",
    )
    sequence = fields.Integer(
        string="Display Order",
        default=10,
        help="Published as 'sort_order'. The website renders services in this "
             "order, so it controls what a visitor sees first.",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="Archive instead of deleting: existing records keep referring to it.",
    )
    category = fields.Selection(
        selection=SERVICE_CATEGORIES,
        string="Category",
        required=True,
        default="other",
        help="Broad family, used for reporting and grouping.",
    )
    description = fields.Text(string="Description", translate=True)

    published = fields.Boolean(
        string="Published on Website",
        default=True,
        help="Uncheck to keep the service internal: it is then absent from "
             "GET /api/v1/services and cannot be requested from the public form.",
    )

    # ─── What the public form must ask for ───────────────────────────
    #
    # Deliberately granular rather than one "requires_route" flag. Air freight
    # needs weight and dimensions, sea freight needs volume and packages, a
    # vehicle shipment needs neither — it needs the vehicle. Collapsing these into
    # one flag is how a form ends up asking a sourcing prospect for a port of
    # loading, which is the fastest way to lose them.
    requires_origin = fields.Boolean(
        string="Requires Origin",
        default=False,
        help="Ask where the goods start from.",
    )
    requires_destination = fields.Boolean(
        string="Requires Destination",
        default=False,
        help="Ask where the goods must be delivered.",
    )
    requires_weight = fields.Boolean(
        string="Requires Weight",
        default=False,
        help="Ask for gross weight. Decisive for air freight pricing.",
    )
    requires_volume = fields.Boolean(
        string="Requires Volume",
        default=False,
        help="Ask for volume in CBM and package count. Decisive for sea freight.",
    )
    requires_vehicle = fields.Boolean(
        string="Requires Vehicle Details",
        default=False,
        help="Ask for make, model and year instead of generic cargo details.",
    )
    requires_budget = fields.Boolean(
        string="Requires Budget",
        default=False,
        help="Ask for a target price or budget. Relevant to sourcing and trading, "
             "where it is the first thing a supplier search needs.",
    )
    requires_goods = fields.Boolean(
        string="Requires Goods Description",
        default=False,
        help="Ask what the goods are, and in what quantity.",
    )

    _sql_constraints = [
        (
            "dally_service_type_code_uniq",
            "UNIQUE(code)",
            "A service type with this code already exists. Codes must be unique.",
        ),
    ]

    @api.constrains("code")
    def _check_code_format(self):
        """Codes travel in URLs, JSON payloads and e-mail subjects.

        Restricting them to lowercase, digits and underscore avoids escaping
        problems and makes them safe to embed anywhere.
        """
        for record in self:
            code = record.code or ""
            if not code:
                continue
            if not code.replace("_", "").isalnum() or code != code.lower():
                raise ValidationError(
                    _(
                        "Invalid service code '%(code)s'. Use lowercase letters, "
                        "digits and underscores only (e.g. 'freight_sea').",
                        code=code,
                    )
                )

    @api.constrains("requires_vehicle", "requires_goods")
    def _check_cargo_flags(self):
        """A service cannot ask for both a vehicle and generic goods.

        They are alternative descriptions of the same thing — what is being
        shipped — and asking for both produces a form that contradicts itself.
        """
        for record in self:
            if record.requires_vehicle and record.requires_goods:
                raise ValidationError(
                    _(
                        "Service '%(name)s' cannot require both vehicle details "
                        "and a goods description: they describe the same thing.",
                        name=record.name,
                    )
                )

    @api.model
    def _get_by_code(self, code):
        """Resolve a service by code, including archived ones.

        Archived services must still resolve: a request created last year keeps
        pointing at a service since withdrawn from the website. Returns an empty
        recordset when unknown — callers decide how to react.
        """
        if not code:
            return self.browse()
        return self.with_context(active_test=False).search(
            [("code", "=", code)], limit=1
        )

    # ─── Public projection ───────────────────────────────────────────

    @api.model
    def _dally_public_catalogue(self):
        """Services offered to the public, in display order.

        Only active *and* published services are returned. An archived or
        unpublished service must not be offerable — a form that lets a visitor
        pick a withdrawn service produces a request nobody can price.
        """
        services = self.search(
            [("active", "=", True), ("published", "=", True)],
            order="sequence, name",
        )
        return [service._dally_public_payload() for service in services]

    def _dally_public_payload(self):
        """The public view of one service.

        Every key is named explicitly: an allowlist stays correct when a field is
        added later, whereas a denylist quietly starts leaking. ``category`` and
        ``published`` are deliberately absent — they are internal organisation,
        not something the form needs.
        """
        self.ensure_one()
        payload = {
            "code": self.code,
            "name": self.name or "",
            "description": self.description or "",
            # Always True here, since the catalogue filters on it. Present because
            # it is part of the published contract: a client can rely on the key
            # existing without special-casing its absence.
            "active": bool(self.active),
            "sort_order": self.sequence,
        }
        for flag in REQUIREMENT_FLAGS:
            payload[flag] = bool(self[flag])
        return payload
