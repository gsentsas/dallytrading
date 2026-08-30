# -*- coding: utf-8 -*-
"""Extend the Dally API scope vocabulary for trusted Freight connectors."""

from odoo import api, models, _
from odoo.exceptions import ValidationError

from odoo.addons.dally_api.models.dally_api_key import AVAILABLE_SCOPES


FREIGHT_WRITE_SCOPE = "freight:write"
FREIGHT_INVOICE_SCOPE = "freight:invoice"
FREIGHT_PAYMENT_SCOPE = "freight:payment"
FREIGHT_CASH_SCOPE = "freight:cash"
#: Lecture de la boîte d'envoi et accusé de projection, et rien d'autre.
#:
#: Un scope dédié plutôt que `freight:write` : le connecteur qui projette vers
#: le classeur n'a besoin ni de créer un dossier, ni d'émettre une facture, ni
#: de toucher à la caisse. Lui prêter ces pouvoirs pour lire une file
#: d'attente serait payer très cher une commodité.
FREIGHT_SHEET_SCOPE = "freight:sheet"
EXTENDED_SCOPES = frozenset(AVAILABLE_SCOPES) | {
    FREIGHT_SHEET_SCOPE,
    FREIGHT_WRITE_SCOPE,
    FREIGHT_INVOICE_SCOPE,
    FREIGHT_PAYMENT_SCOPE,
    FREIGHT_CASH_SCOPE,
}


class DallyApiKey(models.Model):
    _inherit = "dally.api.key"

    @api.constrains("scopes")
    def _check_scopes(self):
        """Accept the base API scopes plus the optional Freight scopes.

        Data synchronisation, invoice creation, customer payments and internal
        cash operations are intentionally distinct privileges. A leaked key used
        only to update weights must not also be able to create financial records.
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
