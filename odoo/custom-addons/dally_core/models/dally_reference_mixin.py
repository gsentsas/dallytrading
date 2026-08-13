# -*- coding: utf-8 -*-
"""Business reference numbering shared by all DallyTrading records.

A single reference identifies a business case across every channel: the
website confirmation screen, the transactional e-mails, the CRM record and
the tracking page. It is therefore generated once, server-side, and never
recomputed.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DallyReferenceMixin(models.AbstractModel):
    """Give a model an immutable, sequence-backed business reference.

    Usage in a concrete model::

        class DallyShipment(models.Model):
            _name = "dally.shipment"
            _inherit = ["dally.reference.mixin"]
            _dally_sequence_code = "dally.shipment"

    The sequence must exist as an ``ir.sequence`` record with that code.
    """

    _name = "dally.reference.mixin"
    _description = "DallyTrading Reference Mixin"

    #: Code of the ``ir.sequence`` to draw from. Concrete models MUST set it.
    _dally_sequence_code = None

    reference = fields.Char(
        string="Reference",
        required=True,
        readonly=True,
        copy=False,
        default="/",
        index=True,
        help="Business reference, generated automatically. Shared with the "
             "customer: it appears on the website, in e-mails and on invoices.",
    )

    _dally_reference_uniq = models.Constraint(
        'UNIQUE(reference)',
        'This reference already exists. References must be unique.',
    )

    @api.model
    def _dally_next_reference(self):
        """Return the next reference, or raise if the sequence is missing.

        Failing loudly matters here: a silent fallback would let two records
        share a reference, and the reference is what customers quote when they
        contact support.
        """
        code = self._dally_sequence_code
        if not code:
            raise UserError(
                _(
                    "Model '%(model)s' inherits dally.reference.mixin but does "
                    "not define _dally_sequence_code.",
                    model=self._name,
                )
            )

        # next_by_code is company-aware and increments atomically at database
        # level, so concurrent website submissions cannot collide.
        reference = self.env["ir.sequence"].next_by_code(code)
        if not reference:
            raise UserError(
                _(
                    "The sequence '%(code)s' is missing. It is normally created "
                    "when the module is installed — reinstall or upgrade the "
                    "module that owns it.",
                    code=code,
                )
            )
        return reference

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # "/" is the placeholder default; treat it as "not provided".
            if not vals.get("reference") or vals["reference"] == "/":
                vals["reference"] = self._dally_next_reference()
        return super().create(vals_list)

    def copy(self, default=None):
        """Never carry a reference over to a duplicate."""
        default = dict(default or {})
        default.setdefault("reference", "/")
        return super().copy(default)

    def name_get(self):
        """Show the reference first — it is how records are looked up."""
        result = []
        for record in self:
            name = record.reference or _("New")
            display = getattr(record, "name", False)
            if display and display != name:
                name = "%s — %s" % (name, display)
            result.append((record.id, name))
        return result
