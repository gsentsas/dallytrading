# -*- coding: utf-8 -*-
"""Extend the Dally API scope vocabulary for trusted Freight connectors."""

from odoo import api, models, _
from odoo.exceptions import ValidationError

from odoo.addons.dally_api.models.dally_api_key import AVAILABLE_SCOPES


FREIGHT_WRITE_SCOPE = "freight:write"
FREIGHT_INVOICE_SCOPE = "freight:invoice"
FREIGHT_PAYMENT_SCOPE = "freight:payment"
EXTENDED_SCOPES = frozenset(AVAILABLE_SCOPES) | {
    FREIGHT_WRITE_SCOPE,
    FREIGHT_INVOICE_SCOPE,
    FREIGHT_PAYMENT_SCOPE,
}


class DallyApiKey(models.Model):
    _inherit = "dally.api.key"

    @api.constrains("scopes")
    def _check_scopes(self):
        """Accept the base API scopes plus the optional Freight scopes.

        Data synchronisation, invoice creation and payment registration are
        intentionally distinct privileges.  A leaked key used only to update
        weights must not also be able to create accounting documents.
        """
        for record in self:
            for scope in record._scope_list():
                if scope not in EXTENDED_SCOPES:
                    raise ValidationError(
                        _(
                            "Unknown scope '%(scope)s'. Available scopes: %(available)s",
                            scope=scope,
                            available=", ".join(sorted(EXTENDED_SCOPES)),
                        )
                    )
