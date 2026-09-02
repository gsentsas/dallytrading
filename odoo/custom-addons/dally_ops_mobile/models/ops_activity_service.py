# -*- coding: utf-8 -*-
"""Lecture métier du journal Dally Ops.

Le modèle d'audit conserve la preuve interne. Ce service en produit une vue
mobile, bornée et compréhensible : aucun nom de modèle, identifiant SQL,
``request_uuid`` ni détail de l'outbox Sheet ne traverse la frontière.
"""

import base64
import json
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Domain

from .ops_errors import DallyOpsError
from .ops_format import montant, nombre, poids


LIMIT_DEFAUT = 25
LIMIT_MAXIMAL = 100

EVENEMENTS_PUBLICS = {
    "customer_created": ("Client créé", "customer"),
    "intake_created": ("Réception enregistrée", "reception"),
    "intake_line_added": ("Article ajouté", "article"),
    "intake_line_updated": ("Article corrigé", "correction"),
    "intake_state_advanced": ("État du dossier mis à jour", "reception"),
    "payment_recorded": ("Paiement enregistré", "payment"),
    "wave_payment_recorded": ("Paiement Wave", "payment"),
    "expense_recorded": ("Dépense enregistrée", "expense"),
    "expense_receipt_attached": ("Justificatif de dépense ajouté", "expense"),
    "photo_added": ("Photo ajoutée au dossier", "reception"),
    "photo_deleted": ("Photo retirée du dossier", "reception"),
    "event_recorded": ("Événement consigné", "reception"),
    "package_loaded": ("Colis chargé au départ", "loading"),
    "package_unloaded": ("Colis retiré du départ", "loading"),
    "cash_transfer_recorded": ("Transfert de caisse enregistré", "transfer"),
    "cash_transfer_received": ("Transfert de caisse reçu", "transfer"),
    "appointment_recorded": ("Rendez-vous créé", "appointment"),
    "appointment_marked_present": ("Client arrivé", "appointment"),
    "appointment_marked_absent": ("Client absent", "appointment"),
    "appointment_rescheduled": ("Rendez-vous reporté", "appointment"),
}

LIBELLES_CHAMPS = {
    "state": "État du dossier",
    "ops_event_kind": "Nature de l'événement",
    "shipment_state": "État au moment du geste",
    "description": "Désignation",
    "goods_category": "Catégorie",
    "package_type": "Type de colis",
    "quantity": "Quantité",
    "announced_weight_kg": "Poids annoncé",
    "exact_weight_kg": "Poids exact",
    "length_cm": "Longueur",
    "width_cm": "Largeur",
    "height_cm": "Hauteur",
    "billing_method": "Mode de facturation",
    "tariff_family_code": "Famille tarifaire",
    "customs_value_xof": "Valeur douanière",
}


class DallyOpsActivityService(models.AbstractModel):
    _name = "dally.ops.activity.service"
    _description = "Dally Ops — journal opérationnel public"

    @api.model
    def list_activity(self, *, date=None, cursor=None, limit=None,
                      event_type=None, scope="mine"):
        """Activité du jour : soi-même, ou l'équipe pour un responsable."""
        self._require_ops()
        limite = self._limit(limit)
        if scope not in ("mine", "team"):
            raise DallyOpsError(_("Périmètre d'activité invalide."))
        if scope == "team" and not self.env.user.has_group(
                "dally_ops_mobile.group_dally_ops_supervisor"):
            raise AccessError(_("Vue d'équipe réservée au responsable opérations."))

        debut, fin, jour = self._day_bounds(date)
        domain = [
            ("company_id", "=", self.env.company.id),
            ("action", "in", list(EVENEMENTS_PUBLICS)),
            ("created_at", ">=", debut),
            ("created_at", "<", fin),
        ]
        if scope == "mine":
            domain.append(("operator_user_id", "=", self.env.uid))
        domain = self._with_type_and_cursor(domain, event_type, cursor)
        return self._page(domain, limite, {"date": jour.isoformat(), "scope": scope})

    @api.model
    def intake_activity(self, reference, *, cursor=None, limit=None,
                        event_type=None):
        """Timeline d'un dossier accessible dans la société courante."""
        self._require_ops()
        shipment = self.env["dally.ops.intake.line.service"]._resoudre_dossier(reference)
        packages = shipment.sudo().package_ids.ids
        collections = self.env["dally.freight.collection"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("shipment_id", "=", shipment.id),
        ]).ids
        # Un événement peut désigner le dossier de quatre façons : par l'ancre
        # posée à l'écriture, ou par l'objet métier qu'il touchait — le dossier
        # lui-même, un de ses colis, un de ses encaissements.
        anchors = Domain.OR([
            Domain([("shipment_id", "=", shipment.id)]),
            Domain([("entity_model", "=", "dally.shipment"),
                    ("entity_res_id", "=", shipment.id)]),
            Domain([("entity_model", "=", "dally.shipment.package"),
                    ("entity_res_id", "in", packages or [0])]),
            Domain([("entity_model", "=", "dally.freight.collection"),
                    ("entity_res_id", "in", collections or [0])]),
        ])
        domain = Domain.AND([
            Domain([("company_id", "=", self.env.company.id),
                    ("action", "in", list(EVENEMENTS_PUBLICS))]),
            anchors,
        ])
        domain = self._with_type_and_cursor(domain, event_type, cursor)
        return self._page(domain, self._limit(limit), {
            "dossier_reference": shipment.external_reference,
            "dossier_label": shipment.collection_local_ref,
        })

    @api.model
    def _page(self, domain, limit, extra):
        events = self.env["dally.ops.audit.event"].sudo().search(
            domain, order="created_at desc, id desc", limit=limit + 1)
        has_more = len(events) > limit
        selected = events[:limit]
        payload = dict(extra)
        payload.update({
            "events": [self._dto(event) for event in selected],
            "next_cursor": self._encode_cursor(selected[-1]) if has_more else None,
            "timezone": self._timezone(),
        })
        return payload

    @api.model
    def _dto(self, event):
        label, category = EVENEMENTS_PUBLICS[event.action]
        shipment = self._event_shipment(event)
        changes = [self._change_dto(change) for change in (event.changes_json or [])]
        return {
            "event": event.action,
            "category": category,
            "label": label,
            "occurred_at": self._iso_utc(event.created_at),
            "actor": event.operator_user_id.name or "",
            "dossier_reference": shipment.external_reference if shipment else None,
            "dossier_label": shipment.collection_local_ref if shipment else None,
            "summary": self._summary(event, shipment, changes),
            "changes": changes,
        }

    @api.model
    def _event_shipment(self, event):
        shipment = event.shipment_id.sudo()
        if shipment and shipment.company_id == event.company_id:
            return shipment
        model = event.entity_model
        if model == "dally.shipment":
            shipment = self.env[model].sudo().browse(event.entity_res_id).exists()
        elif model in ("dally.shipment.package", "dally.freight.collection"):
            record = self.env[model].sudo().browse(event.entity_res_id).exists()
            shipment = record.shipment_id if record else self.env["dally.shipment"].browse()
        else:
            shipment = self.env["dally.shipment"].browse()
        return shipment if shipment and shipment.company_id == event.company_id else False

    @api.model
    def _summary(self, event, shipment, changes):
        model = event.entity_model
        record = self.env[model].sudo().browse(event.entity_res_id).exists() \
            if model in self.env and event.entity_res_id else False
        if record and "company_id" in record._fields and record.company_id != event.company_id:
            record = False
        if event.action == "intake_created" and shipment:
            return "Dossier %s" % (shipment.collection_local_ref or shipment.external_reference)
        if event.action == "intake_state_advanced" and changes:
            return "%s → %s" % (changes[0]["old_value"], changes[0]["new_value"])
        if event.action in ("intake_line_added", "intake_line_updated") and record:
            if changes:
                return "%s → %s" % (changes[0]["old_value"], changes[0]["new_value"])
            return self._article_summary(record)
        if event.action in ("payment_recorded", "wave_payment_recorded") and record:
            return montant(record.amount, record.currency_id.name)
        if event.action.startswith("expense_") and record:
            return montant(record.total_amount, record.currency_id.name)
        if event.action.startswith("cash_transfer_") and record:
            return montant(record.amount, record.currency_id.name)
        if event.action.startswith("appointment_") and record:
            return self._local_datetime(record.start)
        return ""

    @api.model
    def _article_summary(self, package):
        description = (package.description or "").strip()
        poids_lu = poids(package.total_weight_kg)
        return "%s — %s" % (description, poids_lu) if description else poids_lu

    @api.model
    def _change_dto(self, change):
        field = str(change.get("field") or "")
        old = self._format_change(field, change.get("old_value"))
        new = self._format_change(field, change.get("new_value"))
        return {
            "field": field,
            "label": LIBELLES_CHAMPS.get(field, "Valeur"),
            "old_value": old,
            "new_value": new,
        }

    @api.model
    def _format_change(self, field, value):
        if value in (None, False, ""):
            return "—"
        if field in ("announced_weight_kg", "exact_weight_kg"):
            return poids(value)
        if field in ("length_cm", "width_cm", "height_cm"):
            return "%s cm" % nombre(value)
        if field == "customs_value_xof":
            return montant(value, "XOF")
        if field == "state":
            # Les libellés viennent du champ lui-même : le journal ne tient pas
            # un second vocabulaire des états, qui divergerait au premier ajout.
            return self._libelle_etat(value)
        return nombre(value) if isinstance(value, (int, float)) else str(value)

    @api.model
    def _libelle_etat(self, code):
        libelles = dict(
            self.env["dally.shipment"]._fields["state"]._description_selection(
                self.env))
        return libelles.get(code, str(code))

    @api.model
    def _timezone(self):
        """Le fuseau qui définit « aujourd'hui », et celui que l'écran affiche.

        Il est publié dans la charge utile : le serveur borne la journée avec
        ce fuseau, et le navigateur formate les heures avec le même. Un écran
        qui choisirait le sien afficherait, autour de minuit, des heures d'un
        jour que le serveur n'a pas retenu.

        Dakar est le repli, pas une constante : l'entrepôt y est, mais un
        compte dont le fuseau est renseigné doit être servi dans le sien.
        """
        return self.env.user.tz or "Africa/Dakar"

    @api.model
    def _local_datetime(self, value):
        if not value:
            return ""
        naive = fields.Datetime.to_datetime(value).replace(tzinfo=pytz.UTC)
        timezone = pytz.timezone(self._timezone())
        return naive.astimezone(timezone).strftime("%d/%m/%Y %H:%M")

    @staticmethod
    def _iso_utc(value):
        return fields.Datetime.to_datetime(value).isoformat(timespec="seconds") + "Z"

    @api.model
    def _day_bounds(self, value):
        try:
            day = fields.Date.to_date(value) if value else fields.Date.context_today(self)
        except (TypeError, ValueError):
            day = False
        if not day or (value and day.isoformat() != value):
            raise DallyOpsError(_("Date d'activité invalide."))
        timezone = pytz.timezone(self._timezone())
        local_start = timezone.localize(datetime.combine(day, time.min))
        local_end = local_start + timedelta(days=1)
        return (
            local_start.astimezone(pytz.UTC).replace(tzinfo=None),
            local_end.astimezone(pytz.UTC).replace(tzinfo=None),
            day,
        )

    @staticmethod
    def _limit(value):
        try:
            limit = int(value or LIMIT_DEFAUT)
        except (TypeError, ValueError) as error:
            raise DallyOpsError(_("Limite d'activité invalide.")) from error
        if limit < 1 or limit > LIMIT_MAXIMAL:
            raise DallyOpsError(_("Limite d'activité invalide."))
        return limit

    @api.model
    def _with_type_and_cursor(self, domain, event_type, cursor):
        domain = Domain(domain)
        if event_type:
            if event_type not in EVENEMENTS_PUBLICS:
                raise DallyOpsError(_("Type d'événement invalide."))
            domain &= Domain([("action", "=", event_type)])
        if cursor:
            created_at, event_id = self._decode_cursor(cursor)
            # Keyset : l'identifiant départage deux événements du même instant,
            # sans quoi l'un des deux disparaîtrait entre deux pages.
            domain &= Domain.OR([
                Domain([("created_at", "<", created_at)]),
                Domain([("created_at", "=", created_at), ("id", "<", event_id)]),
            ])
        return domain

    @staticmethod
    def _encode_cursor(event):
        raw = json.dumps([
            fields.Datetime.to_string(event.created_at), event.id,
        ], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor):
        try:
            padding = "=" * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode((cursor + padding).encode())
            created_at, event_id = json.loads(raw)
            value = fields.Datetime.to_datetime(created_at)
            event_id = int(event_id)
            if event_id < 1:
                raise ValueError
            return value, event_id
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise DallyOpsError(_("Curseur d'activité invalide.")) from error

    @api.model
    def _require_ops(self):
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))
