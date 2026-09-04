# -*- coding: utf-8 -*-
"""Keep spreadsheet retries side-effect free once billing is frozen."""

from odoo import api, models


class DallyFreightSyncService(models.AbstractModel):
    _inherit = "dally.freight.sync.service"

    @api.model
    def _price_line_if_ready(self, line):
        # The billing lock already rejects any real cargo/pricing mutation in
        # ``line.write``.  If the incoming values are identical, however, this is
        # a harmless network retry and must stay harmless: do not resolve the
        # *current* tariff again because the tariff table may have changed since
        # the invoice snapshot was produced.
        if line.shipment_id.billing_locked and not line._supplement_pricing_allowed():
            return "locked"
        return super()._price_line_if_ready(line)
