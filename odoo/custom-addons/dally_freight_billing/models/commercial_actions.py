# -*- coding: utf-8 -*-
from odoo import models, _


class DallyShipment(models.Model):
    _inherit = "dally.shipment"

    def action_prepare_native_freight_invoice_ui(self):
        self.ensure_one()
        invoice = self.action_prepare_native_freight_invoice()
        return {
            "type": "ir.actions.act_window",
            "name": _("Freight Invoice"),
            "res_model": "account.move",
            "res_id": invoice.id,
            "view_mode": "form",
            "views": [(self.env.ref("account.view_move_form").id, "form")],
            "target": "current",
        }
