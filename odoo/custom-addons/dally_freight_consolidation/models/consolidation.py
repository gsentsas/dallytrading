# -*- coding: utf-8 -*-
"""A consolidation is one physical departure and one master transport file."""

import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


CONSOLIDATION_STATES = [
    ("draft", "Brouillon"),
    ("collecting", "Collecte ouverte"),
    ("collection_closed", "Collecte clôturée"),
    ("ready", "Prête au départ"),
    ("departed", "Partie"),
    ("arrived", "Arrivée"),
    ("closed", "Clôturée"),
    ("cancelled", "Annulée"),
]

CONSOLIDATION_TRANSITIONS = {
    "draft": {"collecting", "cancelled"},
    "collecting": {"collection_closed", "cancelled"},
    "collection_closed": {"collecting", "ready", "cancelled"},
    "ready": {"collecting", "departed", "cancelled"},
    "departed": {"arrived"},
    "arrived": {"closed"},
    "closed": set(),
    "cancelled": set(),
}

_CONSOLIDATION_BYPASS_TOKEN = object()


class DallyFreightConsolidation(models.Model):
    _name = "dally.freight.consolidation"
    _description = "DallyTrading Freight Consolidation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "scheduled_departure desc, id desc"

    name = fields.Char(string="Référence", required=True, copy=False, index=True,
                       default=lambda self: _("Nouveau"), tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)
    state = fields.Selection(
        CONSOLIDATION_STATES, default="draft", required=True, tracking=True,
        index=True, copy=False,
    )

    transport_mode = fields.Selection(
        [("air", "Aérien"), ("sea", "Maritime"), ("road", "Routier")],
        required=True, default="air", tracking=True,
    )
    direction = fields.Selection(
        [("import", "Import"), ("export", "Export"), ("domestic", "Domestique")],
        required=True, default="export",
    )
    origin_country_id = fields.Many2one("res.country", string="Pays d'origine")
    origin_city = fields.Char(string="Ville d'origine")
    origin_location = fields.Char(string="Aéroport / lieu d'origine")
    destination_country_id = fields.Many2one("res.country", string="Pays de destination")
    destination_city = fields.Char(string="Ville de destination")
    destination_location = fields.Char(string="Aéroport / lieu de destination")
    route_summary = fields.Char(string="Route", compute="_compute_route", store=True)

    collection_open_on = fields.Date(string="Ouverture collecte", tracking=True)
    collection_close_on = fields.Date(string="Clôture collecte", tracking=True)
    loading_closed_on = fields.Datetime(string="Chargement clôturé le", copy=False)
    carrier_name = fields.Char(string="Compagnie / transporteur", tracking=True)
    flight_number = fields.Char(string="Vol / voyage", tracking=True)
    scheduled_departure = fields.Datetime(string="Départ prévu", tracking=True)
    actual_departure = fields.Datetime(string="Départ réel", tracking=True, copy=False)
    estimated_arrival = fields.Datetime(string="Arrivée estimée", tracking=True)
    actual_arrival = fields.Datetime(string="Arrivée réelle", tracking=True, copy=False)

    mawb_number = fields.Char(string="MAWB / LTA mère", tracking=True, copy=False)
    hawb_reference = fields.Char(string="Référence HAWB", copy=False)
    goods_nature = fields.Text(string="Nature générale des marchandises")
    shipper_label = fields.Char(string="Shipper")
    consignee_label = fields.Char(string="Consignee")
    document_ids = fields.Many2many(
        "ir.attachment", "dally_consolidation_attachment_rel",
        "consolidation_id", "attachment_id", string="Documents", copy=False,
    )

    master_piece_count = fields.Integer(string="Pièces MAWB")
    master_gross_weight_kg = fields.Float(string="Poids brut MAWB (kg)", digits=(12, 3))
    master_chargeable_weight_kg = fields.Float(
        string="Poids taxable MAWB (kg)", digits=(12, 3)
    )
    master_packaging_weight_kg = fields.Float(
        string="Emballage maître (kg)", digits=(12, 3),
        help="Palettes, sacs maîtres et conditionnement. Ne modifie jamais les poids clients.",
    )

    line_ids = fields.One2many(
        "dally.freight.consolidation.line", "consolidation_id",
        string="Colis / manifeste", copy=False,
    )
    shipment_ids = fields.Many2many(
        "dally.shipment", compute="_compute_totals", string="Dossiers"
    )
    shipment_count = fields.Integer(compute="_compute_totals", string="Nb dossiers")
    package_line_count = fields.Integer(compute="_compute_totals", string="Lignes colis")
    client_package_count = fields.Integer(compute="_compute_totals", string="Colis clients")
    client_weight_kg = fields.Float(compute="_compute_totals", string="Poids clients (kg)")
    client_volume_cbm = fields.Float(compute="_compute_totals", string="Volume clients (m³)")
    manifest_mawb_difference_kg = fields.Float(
        compute="_compute_totals", string="Écart manifeste / MAWB (kg)"
    )
    reconciled_difference_kg = fields.Float(
        compute="_compute_totals", string="Écart après emballage maître (kg)"
    )
    invoice_ids = fields.Many2many("account.move", compute="_compute_totals")
    invoice_count = fields.Integer(compute="_compute_totals")

    _name_company_unique = models.Constraint(
        "UNIQUE(company_id, name)", "La référence de consolidation doit être unique par société."
    )
    _master_piece_non_negative = models.Constraint(
        "CHECK(master_piece_count >= 0)", "Le nombre de pièces MAWB ne peut pas être négatif."
    )
    _master_weights_non_negative = models.Constraint(
        "CHECK(master_gross_weight_kg >= 0 AND master_chargeable_weight_kg >= 0 "
        "AND master_packaging_weight_kg >= 0)",
        "Les poids maîtres ne peuvent pas être négatifs.",
    )

    @api.depends(
        "origin_location", "origin_city", "origin_country_id",
        "destination_location", "destination_city", "destination_country_id",
    )
    def _compute_route(self):
        for record in self:
            origin = record.origin_location or record.origin_city or record.origin_country_id.name
            destination = (
                record.destination_location or record.destination_city
                or record.destination_country_id.name
            )
            record.route_summary = " → ".join(part for part in (origin, destination) if part)

    @api.depends(
        "line_ids.shipment_id", "line_ids.package_id", "line_ids.quantity_loaded",
        "line_ids.weight_loaded", "line_ids.volume_loaded", "master_gross_weight_kg",
        "master_packaging_weight_kg", "line_ids.shipment_id.invoice_id",
    )
    def _compute_totals(self):
        for record in self:
            shipments = record.line_ids.mapped("shipment_id")
            invoices = shipments.mapped("invoice_id")
            record.shipment_ids = shipments
            record.shipment_count = len(shipments)
            record.package_line_count = len(record.line_ids)
            record.client_package_count = sum(record.line_ids.mapped("quantity_loaded"))
            record.client_weight_kg = sum(record.line_ids.mapped("weight_loaded"))
            record.client_volume_cbm = sum(record.line_ids.mapped("volume_loaded"))
            record.manifest_mawb_difference_kg = (
                record.master_gross_weight_kg - record.client_weight_kg
            )
            record.reconciled_difference_kg = (
                record.master_gross_weight_kg
                - record.client_weight_kg
                - record.master_packaging_weight_kg
            )
            record.invoice_ids = invoices
            record.invoice_count = len(invoices)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # `vals.get("name")` vaut `None` quand la clé n'est pas fournie
            # depuis un create serveur : le premier test tombait sur un dossier
            # nommé « Nouveau » (valeur par défaut appliquée par le super après
            # notre garde). On teste explicitement toutes les formes vides.
            placeholder = vals.get("name")
            if not placeholder or placeholder in (_("Nouveau"), "Nouveau", "New"):
                vals["name"] = self._next_route_reference(vals)
        return super().create(vals_list)

    @api.model
    def _next_route_reference(self, vals):
        mode = {"air": "AIR", "sea": "SEA", "road": "ROAD"}.get(
            vals.get("transport_mode", "air"), "CONS"
        )
        origin = (vals.get("origin_location") or vals.get("origin_city") or "ORG")
        destination = (
            vals.get("destination_location") or vals.get("destination_city") or "DST"
        )
        clean = lambda value: re.sub(r"[^A-Z0-9]", "", str(value).upper())[:3] or "XXX"
        date = fields.Date.to_date(vals.get("collection_open_on")) or fields.Date.context_today(self)
        prefix = "%s-%s-%s-%s-" % (mode, clean(origin), clean(destination), date.year)
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ["consolidation:" + prefix]
        )
        existing = self.search([("company_id", "=", vals.get("company_id") or self.env.company.id),
                                ("name", "like", prefix + "%")]).mapped("name")
        numbers = [int(name[-3:]) for name in existing if re.match(r"^.*-\d{3}$", name)]
        return "%s%03d" % (prefix, (max(numbers) if numbers else 0) + 1)

    def write(self, vals):
        internal_backfill = (
            self.env.context.get("_dally_consolidation_bypass")
            is _CONSOLIDATION_BYPASS_TOKEN
        )
        if "state" in vals and not internal_backfill:
            for record in self:
                if vals["state"] != record.state and vals["state"] not in CONSOLIDATION_TRANSITIONS[record.state]:
                    raise UserError(
                        _("Transition de consolidation impossible : %(current)s → %(target)s.",
                          current=record.state, target=vals["state"])
                    )
        immutable = {"transport_mode", "direction", "origin_country_id", "origin_city",
                     "origin_location", "destination_country_id", "destination_city",
                     "destination_location", "mawb_number", "line_ids"}
        if immutable.intersection(vals):
            blocked = self.filtered(lambda rec: rec.state in ("departed", "arrived", "closed"))
            if blocked:
                raise UserError(_("La composition et le dossier maître sont figés après le départ."))
        return super().write(vals)

    def _historical_mark_departed(self):
        if not self.env.user.has_group("dally_core.group_dally_manager"):
            raise AccessError(_("Seul un Manager peut importer un départ historique."))
        return self.with_context(
            _dally_consolidation_bypass=_CONSOLIDATION_BYPASS_TOKEN
        ).write({"state": "departed", "loading_closed_on": fields.Datetime.now()})

    def action_open_collection(self):
        self.write({"state": "collecting"})
        return True

    def action_close_collection(self):
        self.write({"state": "collection_closed", "loading_closed_on": fields.Datetime.now()})
        return True

    def action_mark_ready(self):
        for record in self:
            if not record.line_ids:
                raise UserError(_("Une consolidation vide ne peut pas être prête au départ."))
        self.write({"state": "ready"})
        return True

    def action_reopen_collection(self):
        if not self.env.user.has_group("dally_core.group_dally_manager"):
            raise AccessError(_("Seul un Manager peut rouvrir une collecte."))
        reason = (self.env.context.get("reopen_reason") or "").strip()
        if not reason:
            raise UserError(_("Une raison est obligatoire pour rouvrir la collecte."))
        for record in self:
            if record.state not in ("collection_closed", "ready"):
                raise UserError(_("Cette consolidation ne peut pas être rouverte."))
            record.message_post(body=_("Collecte rouverte par %(user)s. Raison : %(reason)s",
                                       user=self.env.user.display_name, reason=reason))
        self.write({"state": "collecting", "loading_closed_on": False})
        return True

    def _departure_blockers(self):
        self.ensure_one()
        blockers = []
        if not self.shipment_ids:
            blockers.append(_("Aucun dossier n'est rattaché."))
        if not self.line_ids:
            blockers.append(_("Aucun colis n'est chargé."))
        if self.transport_mode == "air" and not self.mawb_number:
            blockers.append(_("La MAWB / LTA mère est obligatoire."))
        if not self.carrier_name:
            blockers.append(_("La compagnie / le transporteur est obligatoire."))
        if not self.origin_location and not self.origin_city:
            blockers.append(_("L'origine est incomplète."))
        if not self.destination_location and not self.destination_city:
            blockers.append(_("La destination est incomplète."))
        for shipment in self.shipment_ids.sorted(lambda rec: rec.external_reference or rec.reference):
            if shipment.state != "ready":
                blockers.append(_("%(ref)s - %(client)s\nÉtat actuel : %(state)s (attendu : Prête à partir).",
                                  ref=shipment.external_reference or shipment.reference,
                                  client=shipment.partner_id.display_name, state=shipment.state))
                continue
            detail = shipment._departure_blocker()
            if detail:
                blockers.append(detail)
        return blockers

    def action_record_departure(self):
        for record in self:
            if record.state != "ready":
                raise UserError(_("La consolidation doit être « Prête au départ »."))
            blockers = record._departure_blockers()
            if blockers:
                raise UserError(
                    _("Départ impossible\n\n%(count)s dossier(s) ou contrôle(s) nécessitent une action :\n\n%(details)s",
                      count=len(blockers), details="\n\n".join(blockers))
                )

        now = fields.Datetime.now()
        for record in self:
            record.write({"actual_departure": record.actual_departure or now, "state": "departed"})
            # One transaction: any failure rolls back the consolidation and every dossier.
            for shipment in record.shipment_ids:
                shipment.action_set_state("departed")
            record.message_post(body=_("Départ enregistré. %(count)s dossiers et %(packages)s colis clients.",
                                       count=record.shipment_count,
                                       packages=record.client_package_count))
        return True

    def action_mark_arrived(self):
        self.write({"state": "arrived", "actual_arrival": fields.Datetime.now()})
        return True

    def action_close(self):
        self.write({"state": "closed"})
        return True

    def action_cancel(self):
        self.write({"state": "cancelled"})
        return True

    def action_create_next_departure(self):
        self.ensure_one()
        next_record = self.copy({
            "name": _("Nouveau"), "state": "collecting", "collection_open_on": fields.Date.context_today(self),
            "collection_close_on": False, "loading_closed_on": False, "flight_number": False,
            "scheduled_departure": False, "actual_departure": False,
            "estimated_arrival": False, "actual_arrival": False, "mawb_number": False,
            "hawb_reference": False, "master_piece_count": 0, "master_gross_weight_kg": 0.0,
            "master_chargeable_weight_kg": 0.0, "master_packaging_weight_kg": 0.0,
            "document_ids": [(5, 0, 0)], "line_ids": [(5, 0, 0)],
        })
        return {"type": "ir.actions.act_window", "res_model": self._name,
                "res_id": next_record.id, "view_mode": "form"}

    def action_view_shipments(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Dossiers"),
                "res_model": "dally.shipment", "view_mode": "list,form",
                "domain": [("id", "in", self.shipment_ids.ids)]}

    def action_view_packages(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Colis clients"),
                "res_model": "dally.shipment.package", "view_mode": "list,form",
                "domain": [("id", "in", self.line_ids.package_id.ids)]}

    def action_view_invoices(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Factures"),
                "res_model": "account.move", "view_mode": "list,form",
                "domain": [("id", "in", self.invoice_ids.ids)]}

    def action_view_documents(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Documents"),
                "res_model": "ir.attachment", "view_mode": "list,form",
                "domain": [("id", "in", self.document_ids.ids)]}

    def action_view_events(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Événements"),
                "res_model": "dally.shipment.event", "view_mode": "list,form",
                "domain": [("shipment_id", "in", self.shipment_ids.ids)]}

    def action_historical_backfill(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "target": "new", "view_mode": "form",
                "res_model": "dally.consolidation.backfill.wizard",
                "context": {"default_consolidation_id": self.id}}


class DallyFreightConsolidationLine(models.Model):
    _name = "dally.freight.consolidation.line"
    _description = "DallyTrading Freight Consolidation Line"
    _order = "consolidation_id, sequence, id"

    sequence = fields.Integer(default=10)
    consolidation_id = fields.Many2one(
        "dally.freight.consolidation", required=True, ondelete="restrict", index=True,
    )
    company_id = fields.Many2one(related="consolidation_id.company_id", store=True, index=True)
    shipment_id = fields.Many2one("dally.shipment", required=True, ondelete="restrict", index=True)
    package_id = fields.Many2one("dally.shipment.package", required=True, ondelete="restrict", index=True)
    quantity_loaded = fields.Integer(string="Quantité chargée", required=True, default=1)
    weight_loaded = fields.Float(string="Poids chargé (kg)", digits=(12, 3), required=True)
    volume_loaded = fields.Float(string="Volume chargé (m³)", digits=(12, 4), required=True)

    _package_consolidation_unique = models.Constraint(
        "UNIQUE(consolidation_id, package_id)",
        "Ce colis figure déjà dans cette consolidation.",
    )
    _loaded_values_positive = models.Constraint(
        "CHECK(quantity_loaded > 0 AND weight_loaded >= 0 AND volume_loaded >= 0)",
        "La quantité doit être positive et les mesures ne peuvent pas être négatives.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            consolidation = self.env["dally.freight.consolidation"].browse(vals["consolidation_id"])
            package = self.env["dally.shipment.package"].browse(vals["package_id"])
            if consolidation.state != "collecting":
                raise UserError(_("Seule une consolidation en collecte peut recevoir des colis."))
            vals["shipment_id"] = package.shipment_id.id
            quantity = vals.get("quantity_loaded") or 1
            vals.setdefault("weight_loaded", package.unit_weight_kg * quantity)
            vals.setdefault("volume_loaded", package.unit_volume_cbm * quantity)
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ["consolidation-package:%s" % package.id],
            )
        lines = super().create(vals_list)
        lines._check_loaded_quantity()
        return lines

    def write(self, vals):
        if self.filtered(lambda line: line.consolidation_id.state in ("departed", "arrived", "closed")):
            raise UserError(_("Une ligne partie ne peut plus être modifiée ni déplacée."))
        result = super().write(vals)
        self._check_loaded_quantity()
        return result

    def unlink(self):
        if self.filtered(lambda line: line.consolidation_id.state in ("departed", "arrived", "closed")):
            raise UserError(_("Une ligne partie ne peut pas être supprimée."))
        return super().unlink()

    @api.constrains("package_id", "shipment_id", "quantity_loaded", "consolidation_id")
    def _check_loaded_quantity(self):
        for line in self:
            if line.package_id.shipment_id != line.shipment_id:
                raise ValidationError(_("Le colis n'appartient pas au dossier sélectionné."))
            lines = self.search([
                ("package_id", "=", line.package_id.id),
                ("consolidation_id.state", "!=", "cancelled"),
            ])
            if sum(lines.mapped("quantity_loaded")) > line.package_id.quantity:
                raise ValidationError(
                    _("La quantité chargée dépasse la quantité disponible du colis %s.",
                      line.package_id.display_name)
                )
