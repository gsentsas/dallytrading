# -*- coding: utf-8 -*-
from odoo import fields, models


class DallyDeparturePaymentOverrideWizard(models.TransientModel):
    _name = "dally.departure.payment.override.wizard"
    _description = "Dérogation Manager au contrôle de paiement"

    shipment_id = fields.Many2one("dally.shipment", required=True, readonly=True)
    reason = fields.Text(string="Raison", required=True)

    def action_confirm(self):
        self.ensure_one()
        self.shipment_id._record_payment_override(self.reason)
        return {"type": "ir.actions.act_window_close"}
