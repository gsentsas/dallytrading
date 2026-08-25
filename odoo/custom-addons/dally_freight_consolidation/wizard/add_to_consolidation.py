# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


# Le wizard n'ajoute qu'un dossier déjà réceptionné ou en préparation. Un
# dossier `ready` a déjà passé le contrôle de préparation ; l'ajouter à une
# consolidation en cours modifierait sa composition après validation.
_ALLOWED_SHIPMENT_STATES = ("goods_received", "preparing")


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
        """Suggestion UI. Ne sert PAS de garde de sécurité ; le contexte est
        contrôlé par l'appelant RPC. `action_confirm` refait la vérification
        côté serveur (finding #7)."""
        context_ids = self.env.context.get("compatible_consolidation_ids") or []
        for wizard in self:
            if context_ids:
                wizard.compatible_consolidation_ids = [(6, 0, context_ids)]
                continue
            wizard.compatible_consolidation_ids = self._server_compatible(wizard.shipment_id)

    @api.model
    def _server_compatible(self, shipment):
        """Recherche autoritaire : société, mode, direction, route, état
        `collecting`. Utilisée par la suggestion UI et par `action_confirm`
        comme dernier rempart."""
        if not shipment:
            return self.env["dally.freight.consolidation"]
        Consolidation = self.env["dally.freight.consolidation"]
        Line = self.env["dally.freight.consolidation.line"]
        candidates = Consolidation.search([
            ("company_id", "=", shipment.company_id.id),
            ("transport_mode", "=", shipment.transport_mode),
            ("direction", "=", shipment.direction),
            ("state", "=", "collecting"),
        ])
        compatible = Consolidation.browse()
        for candidate in candidates:
            try:
                # On réutilise la garde modèle (finding #3) sur un colis
                # représentatif — la première est suffisante pour trancher
                # la compatibilité route/mode/direction.
                pivot = shipment.package_ids[:1]
                if not pivot:
                    continue
                Line._check_operational_compatibility(candidate, pivot)
            except Exception:  # noqa: BLE001 — filtre sur un candidat, ni log ni relance.
                continue
            compatible |= candidate
        return compatible

    def action_confirm(self):
        self.ensure_one()
        # Finding #7 : ne pas se contenter du domaine UI. Refaire la
        # validation avec les critères authentiques, indépendamment de
        # `compatible_consolidation_ids` fourni via `context`.
        if self.shipment_id.state not in _ALLOWED_SHIPMENT_STATES:
            raise UserError(
                _("Ce dossier est actuellement « %(state)s ». Seuls les "
                  "états %(allowed)s peuvent être rattachés à une "
                  "consolidation ouverte.",
                  state=self.shipment_id.state,
                  allowed=", ".join(_ALLOWED_SHIPMENT_STATES))
            )
        if self.consolidation_id.state != "collecting":
            raise UserError(
                _("La consolidation choisie n'est plus en collecte."))
        server_compatible = self._server_compatible(self.shipment_id)
        if self.consolidation_id not in server_compatible:
            raise UserError(
                _("La consolidation choisie n'est pas compatible avec ce "
                  "dossier (société, mode, direction ou route divergents).")
            )
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
