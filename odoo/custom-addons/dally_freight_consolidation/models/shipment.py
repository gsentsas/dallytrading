# -*- coding: utf-8 -*-
"""Shipment readiness, payment gate and consolidation projections."""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


_OVERRIDE_TOKEN = object()


def _format_money(currency, amount):
    return "%.2f %s" % (amount or 0.0, currency.name or "")


class DallyShipment(models.Model):
    _inherit = "dally.shipment"

    consolidation_line_ids = fields.One2many(
        "dally.freight.consolidation.line", "shipment_id", string="Lignes de consolidation"
    )
    consolidation_ids = fields.Many2many(
        "dally.freight.consolidation", compute="_compute_consolidations", string="Consolidations",
        store=True
    )
    consolidation_id = fields.Many2one(
        "dally.freight.consolidation", compute="_compute_consolidations",
        string="Consolidation", store=True,
    )
    consolidation_state = fields.Selection(
        related="consolidation_id.state", string="État consolidation", store=True
    )
    ready_for_departure = fields.Boolean(compute="_compute_operational_controls", store=True)
    payment_control = fields.Char(compute="_compute_operational_controls", string="Contrôle paiement",
                                  store=True)

    departure_payment_override_reason = fields.Text(
        string="Raison de dérogation paiement", readonly=True, copy=False,
        groups="dally_core.group_dally_manager",
    )
    departure_payment_override_user_id = fields.Many2one(
        "res.users", string="Dérogation accordée par", readonly=True, copy=False,
        groups="dally_core.group_dally_manager",
    )
    departure_payment_override_on = fields.Datetime(
        string="Dérogation accordée le", readonly=True, copy=False,
        groups="dally_core.group_dally_manager",
    )
    departure_payment_override_residual = fields.Monetary(
        string="Solde lors de la dérogation", readonly=True, copy=False,
        currency_field="currency_id", groups="dally_core.group_dally_manager",
    )

    @api.depends("consolidation_line_ids.consolidation_id.state")
    def _compute_consolidations(self):
        for shipment in self:
            consolidations = shipment.consolidation_line_ids.mapped("consolidation_id").filtered(
                lambda record: record.state != "cancelled"
            )
            shipment.consolidation_ids = consolidations
            shipment.consolidation_id = consolidations.sorted("id", reverse=True)[:1]

    @api.depends(
        "package_ids.total_weight_kg", "package_ids.description", "goods_description",
        "invoice_id.state", "invoice_id.payment_state", "invoice_id.amount_residual",
        "consolidation_line_ids.consolidation_id.state",
        "departure_payment_override_reason",
    )
    def _compute_operational_controls(self):
        for shipment in self:
            shipment.ready_for_departure = not bool(shipment._ready_blockers())
            shipment.payment_control = _("Bloqué") if shipment._departure_blocker() else _("OK")
            if shipment.departure_payment_override_reason and not shipment._invoice_is_settled():
                shipment.payment_control = _("Dérogation Manager")

    def write(self, vals):
        protected = {
            "departure_payment_override_reason", "departure_payment_override_user_id",
            "departure_payment_override_on", "departure_payment_override_residual",
        }
        if protected.intersection(vals) and self.env.context.get("_dally_override_token") is not _OVERRIDE_TOKEN:
            raise AccessError(_("La trace de dérogation paiement est immuable."))
        return super().write(vals)

    def _customer_segment(self):
        self.ensure_one()
        return self.customer_segment_snapshot or (
            "business" if self.partner_id.company_type == "company" else "individual"
        )

    def _ready_blockers(self):
        self.ensure_one()
        blockers = []
        if not self.package_ids:
            blockers.append(_("aucun colis réel enregistré"))
        for package in self.package_ids:
            if package.total_weight_kg <= 0:
                blockers.append(_("poids réel absent pour %s", package.display_name))
            if not (package.description or self.goods_description):
                blockers.append(_("désignation absente pour %s", package.display_name))
            if "billing_method" in package._fields:
                if package.billing_method == "quote":
                    if not (self.sale_order_id or self.invoice_id):
                        blockers.append(_("tarification sur devis sans devis ni facture"))
                elif package.applied_unit_price_eur <= 0:
                    blockers.append(_("tarification incomplète pour %s", package.display_name))
        if not (self.origin_location or self.origin_city or self.origin_country_id):
            blockers.append(_("origine absente"))
        if not (self.destination_location or self.destination_city or self.destination_country_id):
            blockers.append(_("destination absente"))
        if self.transport_mode == "air" and not self.consolidation_ids.filtered(
            lambda record: record.state in ("collecting", "collection_closed", "ready")
        ):
            blockers.append(_("aucune consolidation aérienne sélectionnée"))
        return blockers

    def _check_ready_requirements(self):
        super()._check_ready_requirements()
        for shipment in self:
            blockers = shipment._ready_blockers()
            if blockers:
                raise UserError(
                    _("Dossier non prêt\n\n%(reference)s ne peut pas passer à « Prête à partir » :\n- %(details)s",
                      reference=shipment.external_reference or shipment.reference,
                      details="\n- ".join(blockers))
                )
        return True

    def _invoice_is_settled(self):
        self.ensure_one()
        invoice = self.invoice_id
        return bool(
            invoice
            and invoice.state == "posted"
            and invoice.payment_state not in ("not_paid", "partial")
            and invoice.currency_id.is_zero(invoice.amount_residual)
        )

    def _departure_blocker(self):
        self.ensure_one()
        reference = self.external_reference or self.reference
        invoice = self.invoice_id
        if not invoice:
            return _("%(ref)s - %(client)s\nAucune facture comptabilisée.",
                     ref=reference, client=self.partner_id.display_name)
        if invoice.state != "posted":
            return _("%(ref)s - %(client)s\nFacture %(invoice)s non comptabilisée (état : %(state)s).",
                     ref=reference, client=self.partner_id.display_name,
                     invoice=invoice.display_name, state=invoice.state)
        if self._invoice_is_settled():
            return False
        if self._customer_segment() == "business" and self.departure_payment_override_reason:
            return False

        paid = invoice.amount_total - invoice.amount_residual
        return _(
            "%(ref)s - %(client)s\nFacture : %(invoice)s\nTotal : %(total)s\n"
            "Réglé : %(paid)s\nReste à payer : %(residual)s\n"
            "La facture doit être entièrement réglée avant le départ.",
            ref=reference, client=self.partner_id.display_name,
            invoice=invoice.display_name,
            total=_format_money(invoice.currency_id, invoice.amount_total),
            paid=_format_money(invoice.currency_id, paid),
            residual=_format_money(invoice.currency_id, invoice.amount_residual),
        )

    def _check_departure_requirements(self):
        super()._check_departure_requirements()
        for shipment in self:
            blocker = shipment._departure_blocker()
            if blocker:
                raise UserError(_("Départ impossible\n\n%s", blocker))
        return True

    def _record_payment_override(self, reason):
        self.ensure_one()
        if not self.env.user.has_group("dally_core.group_dally_manager"):
            raise AccessError(_("Seul un Manager peut accorder une dérogation paiement."))
        if self._customer_segment() != "business":
            raise UserError(_("Une dérogation de paiement est interdite pour un particulier."))
        reason = (reason or "").strip()
        if not reason:
            raise UserError(_("La raison de la dérogation est obligatoire."))
        residual = self.invoice_id.amount_residual if self.invoice_id else 0.0
        self.with_context(_dally_override_token=_OVERRIDE_TOKEN).write({
            "departure_payment_override_reason": reason,
            "departure_payment_override_user_id": self.env.user.id,
            "departure_payment_override_on": fields.Datetime.now(),
            "departure_payment_override_residual": residual,
        })
        self.message_post(
            body=_("Dérogation de départ avec solde accordée par %(user)s. "
                   "Solde constaté : %(amount)s. Raison : %(reason)s",
                   user=self.env.user.display_name,
                   amount=_format_money(self.currency_id, residual), reason=reason),
            subtype_xmlid="mail.mt_note",
        )
        return True

    def action_payment_override(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "dally.departure.payment.override.wizard",
            "view_mode": "form", "target": "new",
            "context": {"default_shipment_id": self.id},
        }

    def action_add_to_open_consolidation(self):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("transport_mode", "=", self.transport_mode),
            ("direction", "=", self.direction),
            ("state", "=", "collecting"),
        ]
        if self.origin_country_id:
            domain.append(("origin_country_id", "=", self.origin_country_id.id))
        if self.destination_country_id:
            domain.append(("destination_country_id", "=", self.destination_country_id.id))
        candidates = self.env["dally.freight.consolidation"].search(domain)
        return {
            "type": "ir.actions.act_window", "target": "new", "view_mode": "form",
            "res_model": "dally.add.to.consolidation.wizard",
            "context": {
                "default_shipment_id": self.id,
                "default_consolidation_id": candidates.id if len(candidates) == 1 else False,
                "compatible_consolidation_ids": candidates.ids,
            },
        }

    def action_view_consolidation(self):
        self.ensure_one()
        if not self.consolidation_id:
            return False
        return {"type": "ir.actions.act_window", "res_model": "dally.freight.consolidation",
                "res_id": self.consolidation_id.id, "view_mode": "form"}


class DallyShipmentPackage(models.Model):
    _inherit = "dally.shipment.package"

    consolidation_line_ids = fields.One2many(
        "dally.freight.consolidation.line", "package_id", string="Lignes de consolidation"
    )
    loaded_quantity = fields.Integer(compute="_compute_consolidation_data", string="Quantité chargée",
                                     store=True)
    available_quantity = fields.Integer(compute="_compute_consolidation_data", string="Quantité disponible",
                                        store=True)
    consolidation_id = fields.Many2one(
        "dally.freight.consolidation", compute="_compute_consolidation_data", string="Consolidation",
        store=True
    )
    consolidation_state = fields.Selection(related="consolidation_id.state", string="État consolidation")
    shipment_state = fields.Selection(related="shipment_id.state", string="Statut dossier")
    partner_id = fields.Many2one(related="shipment_id.partner_id", string="Client")
    transport_mode = fields.Selection(related="shipment_id.transport_mode", string="Mode")
    route_summary = fields.Char(related="shipment_id.route_summary", string="Route")
    ready_for_departure = fields.Boolean(related="shipment_id.ready_for_departure", string="Prêt à partir")
    payment_control = fields.Char(related="shipment_id.payment_control", string="Contrôle paiement")
    external_reference = fields.Char(related="shipment_id.external_reference", string="Dossier externe",
                                     store=True)
    goods_received_on = fields.Date(related="shipment_id.goods_received_on", string="Réception",
                                    store=True)

    @api.depends("consolidation_line_ids.quantity_loaded", "consolidation_line_ids.consolidation_id.state")
    def _compute_consolidation_data(self):
        for package in self:
            active_lines = package.consolidation_line_ids.filtered(
                lambda line: line.consolidation_id.state != "cancelled"
            )
            package.loaded_quantity = sum(active_lines.mapped("quantity_loaded"))
            package.available_quantity = package.quantity - package.loaded_quantity
            package.consolidation_id = active_lines.sorted("id", reverse=True)[:1].consolidation_id
