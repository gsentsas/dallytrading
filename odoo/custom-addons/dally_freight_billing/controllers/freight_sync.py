# -*- coding: utf-8 -*-
"""POST /api/v1/freight/sync — trusted Google Sheets / legacy import upsert."""

from odoo import _, http

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError


TOP_LEVEL_FIELDS = frozenset({
    "request_uuid",
    "external_reference",
    "partner_id",
    "transport_mode",
    "direction",
    "source",
    "goods_received_on",
    "customer_segment",
    "state",
    "dossier_fee_eur",
    "other_fees_eur",
    "client",
    "origin",
    "destination",
    "lines",
})

CLIENT_FIELDS = frozenset({"name", "email", "phone", "address"})
PLACE_FIELDS = frozenset({"country_code", "city", "location"})
LINE_FIELDS = frozenset({
    "external_line_key",
    "package_type",
    "description",
    "goods_category",
    "quantity",
    "announced_weight_kg",
    "exact_weight_kg",
    "length_cm",
    "width_cm",
    "height_cm",
    "unit_volume_cbm",
    "total_volume_cbm",
    "billing_method",
    "tariff_family_code",
    "manual_unit_price_eur",
    "pricing_type",
    "pricing_reason",
    "customs_value_xof",
})

MAX_LINES_PER_REQUEST = 200


class DallyFreightSyncController(DallyApiController):

    @http.route(
        "/api/v1/freight/sync",
        type="http",
        auth="none",
        readonly=False,
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def sync_freight(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/freight/sync",
            required_scope="freight:write",
            handler=self._sync_freight,
        )

    def _sync_freight(self, env, payload, api_key):
        clean = self._clean_payload(payload)
        self._require(clean, "external_reference", "transport_mode", "direction")

        data, shipment = env["dally.freight.sync.service"].upsert(clean)
        status = 201 if data.get("shipment_created") else 200
        data["_record"] = shipment
        return data, status

    @classmethod
    def _clean_payload(cls, payload):
        unknown = sorted(set(payload) - TOP_LEVEL_FIELDS)
        if unknown:
            raise DallyApiError(
                422,
                "unknown_fields",
                _("Unknown freight sync field(s): %s", ", ".join(unknown)),
            )

        clean = {}
        for name in (
            "request_uuid",
            "external_reference",
            "transport_mode",
            "direction",
            "source",
            "goods_received_on",
            "customer_segment",
            "state",
            "dossier_fee_eur",
            "other_fees_eur",
        ):
            if name in payload:
                clean[name] = cls._scalar(payload.get(name), name)

        if "partner_id" in payload:
            partner_id = payload.get("partner_id")
            if partner_id not in (None, "", False):
                try:
                    partner_id = int(partner_id)
                except (TypeError, ValueError) as exc:
                    raise DallyApiError(
                        422, "invalid_partner_id", _("partner_id must be an integer."),
                    ) from exc
                if partner_id <= 0:
                    raise DallyApiError(
                        422, "invalid_partner_id", _("partner_id must be positive."),
                    )
                clean["partner_id"] = partner_id

        if "client" in payload:
            clean["client"] = cls._clean_object(
                payload.get("client"), CLIENT_FIELDS, "client"
            )
        if "origin" in payload:
            clean["origin"] = cls._clean_object(
                payload.get("origin"), PLACE_FIELDS, "origin"
            )
        if "destination" in payload:
            clean["destination"] = cls._clean_object(
                payload.get("destination"), PLACE_FIELDS, "destination"
            )

        if "lines" in payload:
            lines = payload.get("lines")
            if not isinstance(lines, list):
                raise DallyApiError(422, "invalid_lines", _("lines must be an array."))
            if len(lines) > MAX_LINES_PER_REQUEST:
                raise DallyApiError(
                    422,
                    "too_many_lines",
                    _("A freight sync request can contain at most %s lines.", MAX_LINES_PER_REQUEST),
                )
            clean["lines"] = [
                cls._clean_line(line, index)
                for index, line in enumerate(lines, start=1)
            ]

        return clean

    @classmethod
    def _clean_line(cls, line, index):
        if not isinstance(line, dict):
            raise DallyApiError(
                422,
                "invalid_line",
                _("Freight line %s must be an object.", index),
            )
        unknown = sorted(set(line) - LINE_FIELDS)
        if unknown:
            raise DallyApiError(
                422,
                "unknown_line_fields",
                _(
                    "Unknown field(s) on freight line %(index)s: %(fields)s",
                    index=index,
                    fields=", ".join(unknown),
                ),
            )

        clean = {}
        for name, value in line.items():
            if isinstance(value, (dict, list, tuple, set)):
                raise DallyApiError(
                    422,
                    "invalid_line_field_type",
                    _("Field '%s' on a freight line must be scalar.", name),
                )
            clean[name] = value.strip() if isinstance(value, str) else value
        return clean

    @classmethod
    def _clean_object(cls, value, allowlist, field_name):
        if value in (None, False):
            return {}
        if not isinstance(value, dict):
            raise DallyApiError(
                422,
                "invalid_object",
                _("%s must be an object.", field_name),
            )
        unknown = sorted(set(value) - allowlist)
        if unknown:
            raise DallyApiError(
                422,
                "unknown_nested_fields",
                _(
                    "Unknown %(object)s field(s): %(fields)s",
                    object=field_name,
                    fields=", ".join(unknown),
                ),
            )
        return {
            name: cls._scalar(item, "%s.%s" % (field_name, name))
            for name, item in value.items()
        }

    @staticmethod
    def _scalar(value, field_name):
        if value is None:
            return None
        if not isinstance(value, (str, int, float, bool)):
            raise DallyApiError(
                422,
                "invalid_field_type",
                _("Field '%s' must be scalar.", field_name),
            )
        if isinstance(value, str):
            value = value.strip()
            if len(value) > 5000:
                raise DallyApiError(
                    422,
                    "field_too_long",
                    _("Field '%s' is too long.", field_name),
                )
        return value
