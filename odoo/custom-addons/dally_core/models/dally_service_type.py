# -*- coding: utf-8 -*-
"""Catalogue of DallyTrading commercial activities.

The public website, the quote form and the API all designate a service by its
``code``, never by its database id. Ids differ between environments and would
break as soon as staging and production diverge; codes are stable and
reviewable.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Broad families used for reporting and for deciding which fields the public
# quote form should display.
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
    sequence = fields.Integer(string="Display Order", default=10)
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
        help="Broad family, used for reporting and to drive the public form.",
    )
    description = fields.Text(string="Description", translate=True)

    # Drives the public quote form: which extra questions are relevant.
    requires_route = fields.Boolean(
        string="Requires Origin / Destination",
        default=False,
        help="Ask for origin and destination on the public quote form.",
    )
    requires_cargo = fields.Boolean(
        string="Requires Cargo Details",
        default=False,
        help="Ask for goods description, weight, volume and packages.",
    )
    published = fields.Boolean(
        string="Published on Website",
        default=True,
        help="Uncheck to keep the service internal: it will not be offered "
             "on the public form.",
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

    @api.model
    def _get_by_code(self, code):
        """Resolve a service by code, including archived ones.

        Archived services must still resolve: a lead created last year keeps
        pointing at a service that has since been withdrawn from the website.
        Returns an empty recordset when unknown — callers decide how to react.
        """
        if not code:
            return self.browse()
        return self.with_context(active_test=False).search(
            [("code", "=", code)], limit=1
        )
