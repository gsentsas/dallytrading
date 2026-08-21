# -*- coding: utf-8 -*-
"""Idempotent synchronisation of the freight workbook into the CRM business layer.

This service deliberately targets ``dally.shipment`` and
``dally.shipment.package``: these are the DallyTrading business records used by
billing, portal and reporting.  A shipment already linked to the provider's
``freight.shipment`` is read-only from this path because the bridge defines tk →
Dally as one-way.  That guard prevents the Sheet from fighting the operational
engine.
"""

import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


VALID_MODES = frozenset({"air", "sea"})
VALID_DIRECTIONS = frozenset({"import", "export", "domestic"})
VALID_SEGMENTS = frozenset({"individual", "business"})
VALID_BILLING_METHODS = frozenset({"real", "volumetric", "quote"})
VALID_PRICING_TYPES = frozenset({"standard", "promotion", "special"})
VALID_STATES = frozenset({
    "draft",
    "request_received",
    "awaiting_goods",
    "goods_received",
    "preparing",
    "ready",
    "departed",
    "in_transit",
    "arrived",
    "customs",
    "available",
    "out_for_delivery",
    "delivered",
    "cancelled",
})
VALID_SOURCES = frozenset({"legacy_xlsx", "google_sheets", "backoffice"})


class DallyFreightSyncService(models.AbstractModel):
    _name = "dally.freight.sync.service"
    _description = "DallyTrading Freight Sheet Synchronisation Service"

    @api.model
    def upsert(self, payload):
        """Create/update customer, freight file and article lines atomically.

        Object-level idempotence does not rely on the HTTP ``request_uuid``:
        ``external_reference`` identifies a dossier and ``external_line_key`` an
        article.  A new HTTP UUID may therefore safely retry the same business
        data without duplicating it.
        """
        external_reference = self._text(payload.get("external_reference"), 120)
        if not external_reference:
            raise ValidationError(_("external_reference is required."))

        mode = self._choice(payload.get("transport_mode"), VALID_MODES, "transport_mode")
        direction = self._choice(payload.get("direction"), VALID_DIRECTIONS, "direction")
        source = self._choice(
            payload.get("source") or "google_sheets",
            VALID_SOURCES,
            "source",
        )
        segment = payload.get("customer_segment")
        if segment:
            segment = self._choice(segment, VALID_SEGMENTS, "customer_segment")

        self._lock("freight-dossier", "%s:%s" % (self.env.company.id, external_reference))

        Shipment = self.env["dally.shipment"].with_context(active_test=False)
        shipment = Shipment.search([
            ("company_id", "=", self.env.company.id),
            ("external_reference", "=", external_reference),
        ], limit=1)
        shipment_created = not bool(shipment)

        if shipment and "tk_shipment_id" in shipment._fields and shipment.tk_shipment_id:
            raise UserError(
                _(
                    "Shipment %(reference)s is linked to the operational freight "
                    "engine. Sheet synchronisation cannot rewrite its cargo; "
                    "the tk → Dally bridge is one-way."
                )
                % {"reference": shipment.display_name}
            )

        partner, partner_created = self._resolve_partner(
            payload.get("client") or {},
            existing=shipment.partner_id if shipment else None,
            explicit_id=payload.get("partner_id"),
        )

        values = {
            "partner_id": partner.id,
            "external_reference": external_reference,
            "transport_mode": mode,
            "direction": direction,
            "sync_source": source,
            "last_sync_at": fields.Datetime.now(),
            "sync_message": False,
        }
        if segment:
            values["customer_segment_snapshot"] = segment

        goods_received_on = self._date(payload.get("goods_received_on"), "goods_received_on")
        if goods_received_on:
            values["goods_received_on"] = goods_received_on

        state = payload.get("state")
        if state:
            values["state"] = self._choice(state, VALID_STATES, "state")
        elif shipment_created:
            values["state"] = "request_received"

        self._apply_route(values, payload)

        if shipment:
            shipment.write(values)
        else:
            shipment = Shipment.create(values)

        line_results = []
        descriptions = []
        for item in payload.get("lines") or []:
            line, created, pricing_status = self._upsert_line(shipment, item)
            if line.description:
                descriptions.append(line.description)
            line_results.append({
                "external_line_key": line.external_line_key,
                "line_id": line.id,
                "created": created,
                "pricing_status": pricing_status,
                "billable_weight_kg": line.billable_weight_kg,
                "applied_unit_price_eur": line.applied_unit_price_eur,
                "transport_amount_eur": line.transport_amount_eur,
            })

        if descriptions:
            # Summary only; package lines remain the detailed authority.
            summary = " ; ".join(dict.fromkeys(descriptions))
            shipment.goods_description = summary[:5000]

        shipment.write({
            "last_sync_at": fields.Datetime.now(),
            "sync_message": "OK",
        })

        return {
            "partner_id": partner.id,
            "partner_created": partner_created,
            "shipment_id": shipment.id,
            "shipment_created": shipment_created,
            "shipment_reference": shipment.reference,
            "external_reference": shipment.external_reference,
            "state": shipment.state,
            "lines": line_results,
        }, shipment

    # ------------------------------------------------------------------
    # Customer
    # ------------------------------------------------------------------

    @api.model
    def _resolve_partner(self, client, *, existing=None, explicit_id=None):
        Partner = self.env["res.partner"]

        if explicit_id:
            partner = Partner.browse(int(explicit_id)).exists()
            if not partner:
                raise ValidationError(_("partner_id does not identify an existing customer."))
            created = False
        elif existing:
            partner = existing
            created = False
        else:
            email = self._text(client.get("email"), 254)
            phone = self._text(client.get("phone"), 40)
            self._lock_partner_identity(email, phone)
            partner = Partner._dally_find_existing(email=email, phone=phone)
            created = not bool(partner)
            if not partner:
                name = self._text(client.get("name"), 200)
                if not name:
                    raise ValidationError(_("client.name is required for a new customer."))
                partner = Partner.create({"name": name})

        updates = {}
        for source_name, target_name, limit in (
            ("name", "name", 200),
            ("email", "email", 254),
            ("phone", "phone", 40),
            ("address", "street", 500),
        ):
            if source_name in client:
                value = self._text(client.get(source_name), limit)
                if value:
                    updates[target_name] = value

        if updates:
            partner.write(updates)
        return partner, created

    @api.model
    def _lock_partner_identity(self, email, phone):
        email_key = (email or "").strip().lower()
        phone_key = re.sub(r"\D", "", phone or "")[-9:]
        identity = email_key or phone_key
        if identity:
            self._lock("freight-partner", identity)

    # ------------------------------------------------------------------
    # Shipment line
    # ------------------------------------------------------------------

    @api.model
    def _upsert_line(self, shipment, item):
        if not isinstance(item, dict):
            raise ValidationError(_("Each freight line must be an object."))

        external_key = self._text(item.get("external_line_key"), 180)
        if not external_key:
            raise ValidationError(_("Every freight line requires external_line_key."))

        self._lock("freight-line", external_key)
        Package = self.env["dally.shipment.package"]
        line = Package.search([("external_line_key", "=", external_key)], limit=1)
        created = not bool(line)
        if line and line.shipment_id != shipment:
            raise ValidationError(
                _("external_line_key '%s' already belongs to another shipment.", external_key)
            )

        quantity = self._positive_int(item.get("quantity") or 1, "quantity")
        values = {
            "shipment_id": shipment.id,
            "external_line_key": external_key,
            "quantity": quantity,
        }

        if "package_type" in item:
            values["package_type"] = self._text(item.get("package_type"), 30) or "parcel"
        elif created:
            values["package_type"] = "parcel"

        if "description" in item:
            values["description"] = self._text(item.get("description"), 500)
        if "goods_category" in item:
            values["goods_category"] = self._text(item.get("goods_category"), 200)

        announced = self._number(item.get("announced_weight_kg"), "announced_weight_kg")
        if announced is not None:
            values["announced_weight_kg"] = announced

        # The workbook's exact weight is the TOTAL of the article line, while
        # dally.shipment.package stores a unit weight. Divide once here so a row
        # "4 parcels / 79.9 kg" remains 79.9 kg, not 319.6 kg.
        exact_total = self._number(item.get("exact_weight_kg"), "exact_weight_kg")
        if exact_total is not None:
            values["unit_weight_kg"] = exact_total / quantity

        for key in ("length_cm", "width_cm", "height_cm"):
            number = self._number(item.get(key), key)
            if number is not None:
                values[key] = number

        unit_volume = self._number(item.get("unit_volume_cbm"), "unit_volume_cbm")
        total_volume = self._number(item.get("total_volume_cbm"), "total_volume_cbm")
        if unit_volume is not None:
            values["unit_volume_cbm"] = unit_volume
        elif total_volume is not None:
            values["unit_volume_cbm"] = total_volume / quantity

        if "billing_method" in item:
            values["billing_method"] = self._choice(
                item.get("billing_method"), VALID_BILLING_METHODS, "billing_method"
            )

        family_code = self._text(item.get("tariff_family_code"), 80)
        if family_code:
            family = self.env["dally.freight.tariff.family"].search([
                ("code", "=", family_code.strip().lower()),
                ("active", "=", True),
            ], limit=1)
            if not family:
                raise ValidationError(_("Unknown tariff_family_code '%s'.", family_code))
            values["tariff_family_id"] = family.id

        if "manual_unit_price_eur" in item:
            manual = self._number(item.get("manual_unit_price_eur"), "manual_unit_price_eur")
            values["manual_unit_price_eur"] = manual or 0.0
        if "pricing_reason" in item:
            values["pricing_reason"] = self._text(item.get("pricing_reason"), 500)
        if "pricing_type" in item and item.get("pricing_type"):
            values["pricing_type_snapshot"] = self._choice(
                item.get("pricing_type"), VALID_PRICING_TYPES, "pricing_type"
            )
        if "customs_value_xof" in item:
            customs = self._number(item.get("customs_value_xof"), "customs_value_xof")
            values["customs_value_xof"] = customs or 0.0

        if line:
            line.write(values)
        else:
            line = Package.create(values)

        pricing_status = self._price_line_if_ready(line)
        return line, created, pricing_status

    @api.model
    def _price_line_if_ready(self, line):
        if line.billing_method == "quote":
            return "quote"
        if line.manual_unit_price_eur:
            line.action_apply_freight_tariff()
            return "manual"
        if not line.tariff_family_id:
            return "pending_family"
        if not line.total_weight_kg and not line.total_volume_cbm:
            return "pending_weight"

        rule = self.env["dally.freight.tariff.rule"]._find_applicable(
            transport_mode=line.shipment_id.transport_mode,
            family=line.tariff_family_id,
            customer_segment=line.shipment_id.customer_segment_snapshot,
            pricing_date=line.shipment_id._dally_billing_pricing_date(),
        )
        if not rule:
            return "manual_required"

        line.action_apply_freight_tariff()
        return "automatic"

    # ------------------------------------------------------------------
    # Route and parsing helpers
    # ------------------------------------------------------------------

    @api.model
    def _apply_route(self, values, payload):
        Country = self.env["res.country"]
        for prefix in ("origin", "destination"):
            place = payload.get(prefix) or {}
            if not isinstance(place, dict):
                raise ValidationError(_("%s must be an object.", prefix))
            if "city" in place:
                values["%s_city" % prefix] = self._text(place.get("city"), 120)
            if "location" in place:
                values["%s_location" % prefix] = self._text(place.get("location"), 200)
            code = self._text(place.get("country_code"), 2)
            if code:
                country = Country.search([("code", "=", code.upper())], limit=1)
                if not country:
                    raise ValidationError(_("Unknown country code '%s'.", code))
                values["%s_country_id" % prefix] = country.id

    @api.model
    def _lock(self, namespace, key):
        # Transaction-scoped advisory lock: two Apps Script executions cannot
        # both pass search-before-create for the same business key.
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ["%s:%s" % (namespace, key)],
        )

    @staticmethod
    def _text(value, limit=None):
        if value in (None, False):
            return False
        text = str(value).strip()
        if limit and len(text) > limit:
            raise ValidationError(_("A synchronised text field exceeds %s characters.", limit))
        return text or False

    @staticmethod
    def _choice(value, allowed, field_name):
        value = str(value or "").strip()
        if value not in allowed:
            raise ValidationError(
                _("Invalid value '%(value)s' for %(field)s.")
                % {"value": value, "field": field_name}
            )
        return value

    @staticmethod
    def _number(value, field_name):
        if value in (None, "", False):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("%s must be numeric.", field_name)) from exc
        if number < 0:
            raise ValidationError(_("%s cannot be negative.", field_name))
        return number

    @staticmethod
    def _positive_int(value, field_name):
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("%s must be an integer.", field_name)) from exc
        if number <= 0:
            raise ValidationError(_("%s must be greater than zero.", field_name))
        return number

    @staticmethod
    def _date(value, field_name):
        if not value:
            return False
        try:
            return fields.Date.to_date(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("%s must be a valid date.", field_name)) from exc
