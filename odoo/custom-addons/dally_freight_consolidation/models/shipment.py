# -*- coding: utf-8 -*-
"""Shipment readiness, payment gate and consolidation projections."""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
import re


_OVERRIDE_TOKEN = object()
_INTAKE_IDENTITY_TOKEN = object()
_INTAKE_IDENTITY_FIELDS = frozenset({
    "intake_consolidation_id", "collection_sequence", "collection_local_ref",
    "sync_source_key", "external_reference",
})


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

    intake_consolidation_id = fields.Many2one("dally.freight.consolidation", string="Consolidation d'entrée", copy=False, index=True, readonly=True)
    planned_consolidation_id = fields.Many2one("dally.freight.consolidation", string="Consolidation prévue", copy=False, index=True)
    collection_sequence = fields.Integer(string="N° collecte", copy=False, index=True)
    collection_local_ref = fields.Char(string="Référence locale", copy=False, index=True)
    sync_source_key = fields.Char(string="Clé source de synchronisation", copy=False, index=True)

    _intake_sequence_unique = models.Constraint("UNIQUE(company_id, intake_consolidation_id, collection_sequence)", "Le numéro local doit être unique dans la consolidation d'entrée.")
    _sync_source_key_unique = models.Constraint("UNIQUE(company_id, sync_source, sync_source_key)", "La clé source doit être unique par société et source.")

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
    departure_payment_override_invoice_id = fields.Many2one(
        "account.move", string="Facture autorisée", readonly=True, copy=False,
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

    @api.model
    def _allocate_intake_identity(self, consolidation, *, sync_source_key=False, local_ref=False, source="google_sheets"):
        if not consolidation or consolidation.company_id != self.env.company:
            raise ValidationError(_("La consolidation d'entrée est invalide pour cette société."))
        if consolidation.state != "collecting":
            raise ValidationError(_("Une nouvelle collecte ne peut être initialisée que sur une consolidation ouverte."))
        if sync_source_key:
            existing = self.search([("company_id", "=", consolidation.company_id.id), ("sync_source", "=", source), ("sync_source_key", "=", sync_source_key)], limit=1)
            if existing:
                return existing
        if local_ref:
            match = re.fullmatch(r"A([0-9]+)", str(local_ref).strip().upper())
            if not match or int(match.group(1)) <= 0:
                raise ValidationError(_("collection_local_ref doit respecter le format A001."))
            sequence = int(match.group(1))
            local = ("A%03d" % sequence) if sequence < 1000 else ("A%d" % sequence)
            if self.search_count([("company_id", "=", consolidation.company_id.id), ("intake_consolidation_id", "=", consolidation.id), ("collection_sequence", "=", sequence)]):
                raise ValidationError(_("Le numéro local %s est déjà utilisé dans cette consolidation.", local))
        else:
            if not consolidation.intake_sequence_id:
                raise ValidationError(_("La séquence de collecte est indisponible."))
            sequence = int(consolidation.intake_sequence_id.sudo().next_by_id())
            local = ("A%03d" % sequence) if sequence < 1000 else ("A%d" % sequence)
        return sequence, local

    def _check_planned_consolidation_compatibility(self, consolidation):
        self.ensure_one()
        if consolidation.company_id != self.company_id:
            raise ValidationError(_("Société incompatible."))
        if consolidation.state != "collecting":
            raise UserError(_("La consolidation prévue doit être en collecte."))
        if self.transport_mode != consolidation.transport_mode:
            raise ValidationError(_("Le mode de transport de la consolidation prévue est incompatible."))
        if self.direction != consolidation.direction:
            raise ValidationError(_("La direction de la consolidation prévue est incompatible."))
        if self.consolidation_line_ids.filtered(lambda line: line.consolidation_id != consolidation):
            raise UserError(_("Le dossier est déjà chargé dans une autre consolidation."))
        for prefix in ("origin", "destination"):
            for suffix in ("country_id", "city", "location"):
                current = getattr(self, "%s_%s" % (prefix, suffix))
                expected = getattr(consolidation, "%s_%s" % (prefix, suffix))
                if current and expected and current != expected:
                    raise ValidationError(_("La route de la consolidation prévue est incompatible avec le dossier."))
        return True

    @api.model
    def _create_with_intake_identity(self, values):
        created = self.with_context(_dally_intake_identity_token=_INTAKE_IDENTITY_TOKEN).create(values)
        return self.browse(created.ids)

    def _bind_sync_source_key(self, source_key):
        self.ensure_one()
        self.with_context(_dally_intake_identity_token=_INTAKE_IDENTITY_TOKEN).write({
            "sync_source_key": source_key,
        })
        return self

    def _add_available_packages_to_consolidation(self, consolidation):
        Line = self.env["dally.freight.consolidation.line"]
        for shipment in self:
            if shipment.company_id != consolidation.company_id:
                raise ValidationError(_("Société incompatible."))
            if shipment.state not in ("goods_received", "preparing"):
                raise UserError(_("Le dossier doit être reçu ou en préparation."))
            if consolidation.state != "collecting":
                raise UserError(_("La consolidation n'est plus ouverte à la collecte."))
            if not shipment.package_ids:
                raise UserError(_("Ce dossier ne contient aucun colis à charger."))
            for package in shipment.package_ids:
                Line._check_operational_compatibility(consolidation, package)
            for package in shipment.package_ids:
                if package.available_quantity > 0 and not Line.search_count([("consolidation_id", "=", consolidation.id), ("package_id", "=", package.id)]):
                    Line.create({"consolidation_id": consolidation.id, "package_id": package.id, "quantity_loaded": package.available_quantity})
            shipment.planned_consolidation_id = consolidation
        return True

    @api.depends(
        # Colis et désignation (préparation).
        "package_ids",
        "package_ids.total_weight_kg", "package_ids.description",
        "goods_description",
        # Facturation optionnelle par colis (finding #6).
        "package_ids.billing_method", "package_ids.applied_unit_price_eur",
        # Route et mode (contrôles opérationnels).
        "origin_country_id", "origin_city", "origin_location",
        "destination_country_id", "destination_city", "destination_location",
        "transport_mode",
        # Facture et paiement.
        "invoice_id", "invoice_id.state", "invoice_id.payment_state",
        "invoice_id.amount_residual", "invoice_id.currency_id",
        "sale_order_id",
        # Segment client (dérogation Manager possible).
        "customer_segment_snapshot", "partner_id", "partner_id.company_type",
        # Consolidation aérienne rattachée.
        "consolidation_line_ids.consolidation_id.state",
        # Dérogation Manager (trace immuable, mais son apparition change
        # le contrôle affiché).
        "departure_payment_override_reason", "departure_payment_override_invoice_id",
    )
    def _compute_operational_controls(self):
        for shipment in self:
            shipment.ready_for_departure = not bool(shipment._ready_blockers())
            shipment.payment_control = _("Bloqué") if shipment._departure_blocker() else _("OK")
            if shipment.departure_payment_override_reason and not shipment._invoice_is_settled():
                shipment.payment_control = _("Dérogation Manager")

    @api.model_create_multi
    def create(self, vals_list):
        internal = self.env.context.get("_dally_intake_identity_token") is _INTAKE_IDENTITY_TOKEN
        for vals in vals_list:
            identity = _INTAKE_IDENTITY_FIELDS.intersection(vals)
            intake_fields = identity - {"external_reference"}
            if intake_fields and not internal:
                raise AccessError(_("Les identifiants de collecte sont réservés au service métier."))
            if identity:
                sequence = vals.get("collection_sequence")
                local = vals.get("collection_local_ref")
                expected = ("A%03d" % sequence) if sequence and sequence < 1000 else ("A%d" % sequence) if sequence else False
                if sequence and local != expected:
                    raise ValidationError(_("collection_sequence et collection_local_ref doivent rester cohérents."))
        return super().create(vals_list)

    def write(self, vals):
        internal = self.env.context.get("_dally_intake_identity_token") is _INTAKE_IDENTITY_TOKEN
        identity = _INTAKE_IDENTITY_FIELDS.intersection(vals)
        for shipment in self:
            if identity and shipment.intake_consolidation_id and not internal:
                raise AccessError(_("Les identifiants de collecte sont immuables."))
            if "collection_sequence" in vals or "collection_local_ref" in vals:
                sequence = vals.get("collection_sequence", shipment.collection_sequence)
                local = vals.get("collection_local_ref", shipment.collection_local_ref)
                expected = ("A%03d" % sequence) if sequence and sequence < 1000 else ("A%d" % sequence) if sequence else False
                if sequence and local != expected:
                    raise ValidationError(_("collection_sequence et collection_local_ref doivent rester cohérents."))
        if "intake_consolidation_id" in vals:
            target = vals.get("intake_consolidation_id") or False
            for shipment in self:
                if shipment.intake_consolidation_id.id != target:
                    raise ValidationError(_("La consolidation d'entrée est immuable après allocation."))
        if "planned_consolidation_id" in vals:
            target = self.env["dally.freight.consolidation"].browse(vals.get("planned_consolidation_id")).exists()
            for shipment in self:
                if not target:
                    raise ValidationError(_("Une consolidation prévue est requise."))
                shipment._check_planned_consolidation_compatibility(target)
                if shipment.package_ids:
                    self.env["dally.freight.consolidation.line"]._check_operational_compatibility(target, shipment.package_ids[:1])
        internal = self.env.context.get("_dally_override_token") is _OVERRIDE_TOKEN
        protected = {
            "departure_payment_override_reason", "departure_payment_override_user_id",
            "departure_payment_override_on", "departure_payment_override_residual",
            "departure_payment_override_invoice_id",
        }
        if protected.intersection(vals) and not internal:
            raise AccessError(_("La trace de dérogation paiement est immuable."))
        if identity and any(shipment.intake_consolidation_id for shipment in self) and (
            self.env.context.get("_dally_intake_identity_token") is not _INTAKE_IDENTITY_TOKEN
        ):
            raise AccessError(_("Les identifiants de collecte sont immuables."))
        if "invoice_id" in vals and not internal:
            new_invoice_id = vals.get("invoice_id") or False
            changed_invoice = self.filtered(lambda shipment: shipment.invoice_id.id != new_invoice_id)
            result = super().write(vals)
            if changed_invoice:
                changed_invoice.sudo().with_context(_dally_override_token=_OVERRIDE_TOKEN).write({
                    "departure_payment_override_reason": False,
                    "departure_payment_override_user_id": False,
                    "departure_payment_override_on": False,
                    "departure_payment_override_residual": 0.0,
                    "departure_payment_override_invoice_id": False,
                })
            return result
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
        secured = self.sudo()
        reference = secured.external_reference or secured.reference
        invoice = secured.invoice_id
        if not invoice:
            return _("%(ref)s - %(client)s\nAucune facture comptabilisée.",
                     ref=reference, client=secured.partner_id.display_name)
        if invoice.state != "posted":
            return _("%(ref)s - %(client)s\nFacture %(invoice)s non comptabilisée (état : %(state)s).",
                     ref=reference, client=secured.partner_id.display_name,
                     invoice=invoice.display_name, state=invoice.state)
        if secured._invoice_is_settled():
            return False
        if (secured._customer_segment() == "business"
                and secured.departure_payment_override_reason
                and secured.departure_payment_override_invoice_id == invoice):
            return False

        paid = invoice.amount_total - invoice.amount_residual
        return _(
            "%(ref)s - %(client)s\nFacture : %(invoice)s\nTotal : %(total)s\n"
            "Réglé : %(paid)s\nReste à payer : %(residual)s\n"
            "La facture doit être entièrement réglée avant le départ.",
            ref=reference, client=secured.partner_id.display_name,
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
            "departure_payment_override_invoice_id": self.invoice_id.id,
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

    @api.depends(
        "consolidation_line_ids.quantity_loaded",
        "consolidation_line_ids.consolidation_id.state",

        # Finding #6 : sans dépendance sur `quantity`, l'ajustement direct
        # de la quantité d'un colis ne recalcule pas `available_quantity`.
        "quantity",
    )
    def _compute_consolidation_data(self):
        for package in self:
            active_lines = package.sudo().consolidation_line_ids.filtered(
                lambda line: line.consolidation_id.state != "cancelled"
            )
            package.loaded_quantity = sum(active_lines.mapped("quantity_loaded"))


            package.available_quantity = package.quantity - package.loaded_quantity
            package.consolidation_id = active_lines.sorted("id", reverse=True)[:1].consolidation_id
    def write(self, vals):
        if "quantity" in vals:
            for package in self:
                self.env.cr.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ["consolidation-package:%s" % package.id],
                )
                package.invalidate_recordset(["consolidation_line_ids", "quantity"])
                loaded = sum(package.sudo().consolidation_line_ids.filtered(
                    lambda line: line.consolidation_id.state != "cancelled"
                ).mapped("quantity_loaded"))
                if vals["quantity"] < loaded:
                    raise ValidationError(_(
                        "La quantité du colis %(package)s ne peut pas être inférieure "
                        "à la quantité déjà chargée (%(loaded)s).",
                        package=package.display_name, loaded=loaded))
        return super().write(vals)
