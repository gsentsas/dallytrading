# -*- coding: utf-8 -*-
"""Idempotent preview/confirmation of the first historical air departure."""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..models.consolidation import route_endpoint_compatible

_logger = logging.getLogger(__name__)


class DallyConsolidationBackfillWizard(models.TransientModel):
    _name = "dally.consolidation.backfill.wizard"
    _description = "Prévisualisation du backfill d'une consolidation"

    consolidation_id = fields.Many2one("dally.freight.consolidation", required=True)
    cutoff_date = fields.Date(
        string="Reçu avant le", required=True, default=lambda self: fields.Date.to_date("2026-08-25")
    )
    candidate_line_ids = fields.One2many(
        "dally.consolidation.backfill.line", "wizard_id", string="Dossiers candidats"
    )
    candidate_weight_kg = fields.Float(compute="_compute_totals")
    included_weight_kg = fields.Float(compute="_compute_totals")
    mawb_difference_kg = fields.Float(compute="_compute_totals")

    @api.depends("candidate_line_ids.include", "candidate_line_ids.weight_kg",
                 "consolidation_id.master_gross_weight_kg")
    def _compute_totals(self):
        for wizard in self:
            wizard.candidate_weight_kg = sum(wizard.candidate_line_ids.mapped("weight_kg"))
            wizard.included_weight_kg = sum(
                wizard.candidate_line_ids.filtered("include").mapped("weight_kg")
            )
            wizard.mawb_difference_kg = (
                wizard.consolidation_id.master_gross_weight_kg - wizard.included_weight_kg
            )

    def action_preview(self):
        self.ensure_one()
        self.candidate_line_ids.unlink()
        # Finding #8 : filtrer aussi sur direction + route.
        # On priorise les identifiants structurés (`*_country_id`) qui
        # existent quasi systématiquement en base ; les champs texte
        # `city` / `location` sont utilisés en fallback seulement quand la
        # consolidation ne porte pas le pays. Sans cela, une consolidation
        # DSS→CDG dont l'operateur écrit "DSS" en `origin_location` alors
        # que les dossiers historiques écrivent "Dakar" excluerait tout
        # candidat — c'est ce qu'a montré le dry-run 2026-08-25 round 2.
        consolidation = self.consolidation_id
        domain = [
            ("company_id", "=", consolidation.company_id.id),
            ("transport_mode", "=", consolidation.transport_mode),
            ("direction", "=", consolidation.direction),
            ("goods_received_on", "<", self.cutoff_date),
        ]
        if consolidation.origin_country_id:
            domain.append(("origin_country_id", "=", consolidation.origin_country_id.id))
        if consolidation.destination_country_id:
            domain.append(("destination_country_id", "=", consolidation.destination_country_id.id))
        shipments = self.env["dally.shipment"].search(
            domain, order="goods_received_on, external_reference, id",
        )
        Candidate = self.env["dally.consolidation.backfill.line"]
        rows = []
        for shipment in shipments:
            reason = self._eligibility_reason(shipment)
            if reason == _("Route incompatible."):
                _logger.info("Backfill route exclusion %s: route mismatch", shipment.external_reference or shipment.reference)
                continue
            existing = shipment.consolidation_ids.filtered(
                lambda record: record.state != "cancelled"
            )
            invoice = shipment.invoice_id
            include = not reason and not existing
            Candidate.create({
                "wizard_id": self.id, "shipment_id": shipment.id, "include": include,
                "external_reference": shipment.external_reference,
                "client_name": shipment.partner_id.display_name,
                "goods_received_on": shipment.goods_received_on, "shipment_state": shipment.state,
                "weight_kg": shipment.weight_kg, "package_count": shipment.packages_count,
                "invoice_name": invoice.display_name if invoice else False,
                "invoice_state": invoice.state if invoice else False,
                "payment_state": invoice.payment_state if invoice else False,
                "amount_total": invoice.amount_total if invoice else 0.0,
                "amount_residual": invoice.amount_residual if invoice else 0.0,
                "currency_id": invoice.currency_id.id if invoice else self.env.company.currency_id.id,
                "existing_consolidation": ", ".join(existing.mapped("name")),
                "decision_note": reason,
            })
            rows.append(
                "%s | %s | %s | %s kg | %s colis | facture=%s | paiement=%s | reste=%s | consolidation=%s"
                % (shipment.external_reference or shipment.reference, shipment.partner_id.display_name,
                   shipment.state, shipment.weight_kg, shipment.packages_count,
                   invoice.display_name if invoice else "-", invoice.payment_state if invoice else "-",
                   invoice.amount_residual if invoice else "-", ",".join(existing.mapped("name")) or "-")
            )
        _logger.info("DRY RUN consolidation %s\n%s", self.consolidation_id.name, "\n".join(rows))
        return {
            "type": "ir.actions.act_window", "res_model": self._name,
            "res_id": self.id, "view_mode": "form", "target": "new",
        }

    def _eligibility_reason(self, shipment):
        """Single authoritative eligibility check shared by preview/confirm."""
        consolidation = self.consolidation_id
        if shipment.company_id != consolidation.company_id:
            return _("Société incompatible.")
        if shipment.transport_mode != consolidation.transport_mode or shipment.direction != consolidation.direction:
            return _("Mode ou direction incompatible.")
        if not route_endpoint_compatible(consolidation, shipment, "origin") or not route_endpoint_compatible(consolidation, shipment, "destination"):
            return _("Route incompatible.")
        if not shipment.goods_received_on or shipment.goods_received_on >= self.cutoff_date:
            return _("Date de réception hors cutoff.")
        if shipment.state == "cancelled":
            return _("Dossier annulé : exclu par défaut.")
        existing = shipment.consolidation_ids.filtered(lambda record: record.state != "cancelled")
        if existing and any(record != consolidation for record in existing):
            return _("Déjà rattaché à une autre consolidation : %s", ", ".join(existing.mapped("name")))
        if not existing:
            for package in shipment.package_ids:
                loaded = sum(package.consolidation_line_ids.filtered(
                    lambda line: line.consolidation_id.state != "cancelled"
                ).mapped("quantity_loaded"))
                if loaded >= package.quantity:
                    return _("Le colis %s n'est plus disponible.", package.display_name)
        return False

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group("dally_core.group_dally_manager"):
            raise AccessError(_("Seul un Manager peut confirmer le backfill historique."))
        consolidation = self.consolidation_id
        if consolidation.state not in ("collecting", "departed"):
            raise UserError(_("La consolidation historique doit être ouverte ou déjà partie."))

        selected = self.candidate_line_ids.filtered("include")
        if not selected:
            raise UserError(_("Aucun dossier n'est sélectionné."))
        invalid = []
        for candidate in selected:
            reason = self._eligibility_reason(candidate.shipment_id)
            if reason:
                invalid.append("%s : %s" % (candidate.external_reference or candidate.shipment_id.reference, reason))
        if invalid:
            raise UserError(_("Backfill impossible : la prévisualisation n'est plus valide.\n\n%s", "\n".join(invalid)))
        created = 0
        Line = self.env["dally.freight.consolidation.line"].with_context(historical_backfill=True)
        for candidate in selected:
            shipment = candidate.shipment_id
            for package in shipment.package_ids:
                existing = Line.search([
                    ("consolidation_id", "=", consolidation.id),
                    ("package_id", "=", package.id),
                ], limit=1)
                if existing:
                    continue
                if consolidation.state != "collecting":
                    raise UserError(_("Le backfill est incomplet mais la consolidation est déjà partie."))
                Line.create({
                    "consolidation_id": consolidation.id, "package_id": package.id,
                    "quantity_loaded": package.quantity,
                })
                created += 1
            if shipment.state != "departed":
                historical_date = consolidation.actual_departure or False
                shipment.with_context(historical_event_date=historical_date)._write_historical_state(
                    "departed"
                )
            marker = _("Historique importé lors de la création de la consolidation %s.",
                       consolidation.name)
            if not self.env["mail.message"].sudo().search_count([
                ("model", "=", "dally.shipment"), ("res_id", "=", shipment.id),
                ("body", "ilike", consolidation.name),
            ]):
                shipment.message_post(body=marker, subtype_xmlid="mail.mt_note")

        if consolidation.state != "departed":
            consolidation._historical_mark_departed()
        consolidation.message_post(
            body=_("Backfill historique confirmé : %(shipments)s dossiers, %(lines)s lignes créées. "
                   "Aucune notification client n'a été générée.",
                   shipments=len(selected), lines=created), subtype_xmlid="mail.mt_note",
        )
        return {"type": "ir.actions.act_window_close"}


class DallyConsolidationBackfillLine(models.TransientModel):
    _name = "dally.consolidation.backfill.line"
    _description = "Ligne de prévisualisation du backfill"
    _order = "goods_received_on, external_reference, id"

    wizard_id = fields.Many2one("dally.consolidation.backfill.wizard", required=True,
                                ondelete="cascade")
    include = fields.Boolean(string="Inclure")
    shipment_id = fields.Many2one("dally.shipment", required=True, readonly=True)
    external_reference = fields.Char(readonly=True)
    client_name = fields.Char(readonly=True)
    goods_received_on = fields.Date(readonly=True)
    shipment_state = fields.Char(readonly=True)
    weight_kg = fields.Float(readonly=True)
    package_count = fields.Integer(readonly=True)
    invoice_name = fields.Char(readonly=True)
    invoice_state = fields.Char(readonly=True)
    payment_state = fields.Char(readonly=True)
    amount_total = fields.Monetary(readonly=True, currency_field="currency_id")
    amount_residual = fields.Monetary(readonly=True, currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", readonly=True)
    existing_consolidation = fields.Char(readonly=True)
    decision_note = fields.Char(string="Décision / anomalie")
