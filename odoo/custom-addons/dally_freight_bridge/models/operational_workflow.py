# -*- coding: utf-8 -*-
"""Make tk_freight the single operational workflow authority."""

from odoo import _, models
from odoo.exceptions import UserError

from odoo.addons.dally_freight.models.dally_shipment import (
    _OPERATIONAL_SYNC_TOKEN,
    _STATE_BYPASS_TOKEN,
)

from .freight_mapping import stage_from_state, state_from_stage


def _is_internal_projection(env):
    """Vrai si l'appelant est déjà dans la boucle de sync tk↔Dally.

    Deux tokens couvrent cette boucle : le bypass historique complet et le
    bypass opérationnel qui garde la gate financière. Les deux doivent
    court-circuiter la re-écriture côté tk pour éviter une récursion infinie
    et une double sync.
    """
    ctx = env.context
    return (
        ctx.get("_dally_state_bypass") is _STATE_BYPASS_TOKEN
        or ctx.get("_dally_operational_sync") is _OPERATIONAL_SYNC_TOKEN
    )


class DallyShipment(models.Model):
    _inherit = "dally.shipment"

    def write(self, vals):
        new_state = vals.get("state")
        internal_projection = _is_internal_projection(self.env)
        # `tk_shipment_id` est un lien technique portail-lockdown : les
        # utilisateurs de synchronisation (Sheets / API) n'y ont pas accès
        # en lecture. On repère les dossiers liés en sudo mais on continue
        # d'écrire côté tk avec les droits de l'appelant, ce qui préserve
        # les traces d'audit.
        linked_ids = (
            set(self.sudo().filtered("tk_shipment_id").ids)
            if new_state else set()
        )
        linked = self.filtered(lambda record: record.id in linked_ids)
        unlinked = self - linked

        if linked and not internal_projection:
            linked._check_state_transition(new_state)
            stage = stage_from_state(self.env, new_state)
            if not stage:
                raise UserError(
                    _("Aucune étape opérationnelle n'est configurée pour « %s ».", new_state)
                )
            for shipment in linked:
                shipment.tk_shipment_id.write({"stage_id": stage.id})

            other_values = {key: value for key, value in vals.items() if key != "state"}
            if other_values:
                super(DallyShipment, linked).write(other_values)
            if unlinked:
                super(DallyShipment, unlinked).write(vals)
            return True

        return super().write(vals)

    def _write_historical_state(self, new_state):
        if not self.env.user.has_group("dally_core.group_dally_manager"):
            raise UserError(_("Seul un Manager peut importer un état historique."))
        linked = self.filtered("tk_shipment_id")
        unlinked = self - linked
        stage = stage_from_state(self.env, new_state)
        if linked and not stage:
            raise UserError(_("Aucune étape tk n'est configurée pour l'état historique demandé."))
        for shipment in linked:
            shipment.tk_shipment_id.with_context(
                _dally_state_bypass=_STATE_BYPASS_TOKEN,
                historical_backfill=True,
                historical_event_date=self.env.context.get("historical_event_date"),
            ).write({"stage_id": stage.id})
        if unlinked:
            super(DallyShipment, unlinked)._write_historical_state(new_state)
        return True


class FreightShipment(models.Model):
    _inherit = "freight.shipment"

    def write(self, vals):
        projections = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "in", self.ids)]
        ) if "stage_id" in vals else self.env["dally.shipment"]

        internal_projection = _is_internal_projection(self.env)
        if projections and vals.get("stage_id") and not internal_projection:
            target = state_from_stage(
                self.env, self.env["freight.shipment.stages"].browse(vals["stage_id"])
            )
            if target:
                for projection in projections:
                    # Allow tk's coarser workflow to skip Dally adjacency, but
                    # retain readiness, departure and payment gates.
                    projection.with_context(
                        _dally_operational_sync=_OPERATIONAL_SYNC_TOKEN
                    )._check_state_transition(target)

        result = super().write(vals)
        if projections:
            projections._dally_freight_sync_from_tk()
        return result
