# -*- coding: utf-8 -*-
"""Keep consolidation references immutable once the record exists."""

from odoo import _, models
from odoo.exceptions import UserError


class DallyFreightConsolidationReferenceGuard(models.Model):
    _inherit = "dally.freight.consolidation"

    def write(self, vals):
        """Reject every post-create reference mutation.

        Historical imports can still provide an explicit valid ``name`` during
        ``create``. No supported backfill path needs to rename an existing
        consolidation, so keeping writes fully immutable is the narrowest and
        safest server-side contract.
        """
        if "name" in vals:
            raise UserError(_("La référence de consolidation est immuable après création."))
        return super().write(vals)
