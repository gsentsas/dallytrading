# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DallyAddToConsolidationWizard(models.TransientModel):
    _name = "dally.add.to.consolidation.wizard"
    _description = "Ajouter un dossier à une consolidation ouverte"

    shipment_id = fields.Many2one("dally.shipment", required=True, readonly=True)
    consolidation_id = fields.Many2one(
        "dally.freight.consolidation", required=True,
        domain="[('id', 'in', compatible_consolidation_ids)]",
    )
    compatible_consolidation_ids = fields.Many2many(
        "dally.freight.consolidation", compute="_compute_compatible"
    )

    @api.depends("shipment_id")
    def _compute_compatible(self):
        context_ids = self.env.context.get("compatible_consolidation_ids") or []
        for wizard in self:
            if context_ids:
                wizard.compatible_consolidation_ids = [(6, 0, context_ids)]
                continue
            shipment = wizard.shipment_id
            wizard.compatible_consolidation_ids = self.env["dally.freight.consolidation"].search([
                ("company_id", "=", shipment.company_id.id),
                ("transport_mode", "=", shipment.transport_mode),
                ("direction", "=", shipment.direction),
                ("state", "=", "collecting"),
            ])

    def action_confirm(self):
        self.ensure_one()
        if self.consolidation_id not in self.compatible_consolidation_ids:
            raise UserError(_("La consolidation choisie n'est pas compatible avec ce dossier."))
        created = 0
        Line = self.env["dally.freight.consolidation.line"]
        for package in self.shipment_id.package_ids:
            if package.available_quantity <= 0:
                continue
            Line.create({
                "consolidation_id": self.consolidation_id.id,
                "package_id": package.id,
                "quantity_loaded": package.available_quantity,
            })
            created += 1
        if not created:
            raise UserError(_("Ce dossier ne contient aucun colis disponible à charger."))
        self.shipment_id.message_post(
            body=_("Dossier ajouté à la consolidation %s.", self.consolidation_id.display_name)
        )
        return {"type": "ir.actions.act_window_close"}
