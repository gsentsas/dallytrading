# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError


IMMUTABLE_REGISTERED_FIELDS = frozenset({
    "external_payment_key",
    # Rediriger un encaissement deja comptabilise vers une autre piece
    # deplacerait de l'argent entre deux factures sans ecriture pour le dire.
    "target_invoice_id",
    "shipment_id",
    "amount",
    "currency_id",
    "payment_date",
    "source_method",
    "source",
    "collected_by_id",
    "collected_by_name",
})


class DallyFreightCollection(models.Model):
    _inherit = "dally.freight.collection"

    def write(self, vals):
        protected = IMMUTABLE_REGISTERED_FIELDS.intersection(vals)
        if protected and self.filtered(lambda record: record.payment_id):
            raise UserError(
                _(
                    "A registered freight collection is accounting history and "
                    "cannot be rewritten. Create a corrective collection instead."
                )
            )
        return super().write(vals)

    def unlink(self):
        if self.filtered("payment_id"):
            raise UserError(
                _(
                    "A freight collection linked to an accounting payment cannot "
                    "be deleted. Reverse/correct it through Accounting instead."
                )
            )
        return super().unlink()
