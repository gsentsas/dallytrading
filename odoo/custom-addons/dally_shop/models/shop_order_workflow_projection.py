# -*- coding: utf-8 -*-
"""Adapte la projection checkout au workflow client-safe du Lot B."""

from odoo import models


class SaleOrderShopWorkflowProjection(models.Model):
    _inherit = "sale.order"

    def _dally_shop_projection(self):
        self.ensure_one()
        projection = super()._dally_shop_projection()
        projection["status"] = self.dally_shop_workflow_state or "received"
        return projection
