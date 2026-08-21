# -*- coding: utf-8 -*-
"""Extend the Dally API scope vocabulary for the trusted Sheet connector."""

from odoo import api, models, _
from odoo.exceptions import ValidationError

from odoo.addons.dally_api.models.dally_api_key import AVAILABLE_SCOPES


FREIGHT_WRITE_SCOPE = "freight:write"
EXTENDED_SCOPES = frozenset(AVAILABLE_SCOPES) | {FREIGHT_WRITE_SCOPE}


class DallyApiKey(models.Model):
    _inherit = "dally.api.key"

    @api.constrains("scopes")
    def _check_scopes(self):
        """Accept the base API scopes plus the freight Sheet write scope.

        The parent model stores scopes as a comma-separated Char, so there is no
        ``selection_add`` hook.  Overriding the constraint keeps the extension
        local to this optional module and avoids granting freight write to any
        existing key automatically.
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
