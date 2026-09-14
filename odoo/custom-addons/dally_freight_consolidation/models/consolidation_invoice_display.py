# -*- coding: utf-8 -*-
"""Affichage complet des factures d'une consolidation."""

from odoo import api, fields, models


class DallyShipmentPackage(models.Model):
    _inherit = "dally.shipment.package"

    consolidation_invoice_sale_line_ids = fields.One2many(
        "sale.order.line",
        "dally_freight_package_id",
        string="Lignes de vente fret (affichage consolidation)",
        readonly=True,
    )


class DallyFreightConsolidation(models.Model):
    _inherit = "dally.freight.consolidation"

    @api.depends(
        "line_ids.shipment_id", "line_ids.package_id", "line_ids.quantity_loaded",
        "line_ids.weight_loaded", "line_ids.volume_loaded", "master_gross_weight_kg",
        "master_packaging_weight_kg", "line_ids.shipment_id.invoice_id",
        "line_ids.package_id.consolidation_invoice_sale_line_ids.order_id.state",
        "line_ids.package_id.consolidation_invoice_sale_line_ids.invoice_lines",
        "line_ids.package_id.consolidation_invoice_sale_line_ids.invoice_lines.move_id.state",
    )
    def _compute_totals(self):
        """Complete l'affichage avec les factures complementaires."""
        super()._compute_totals()
        for record in self:
            invoices = record.invoice_ids
            for shipment in record.shipment_ids:
                invoices |= shipment._supplement_invoices()
            record.invoice_ids = invoices
            record.invoice_count = len(invoices)
