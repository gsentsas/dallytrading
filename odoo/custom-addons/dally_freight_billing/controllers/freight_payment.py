# -*- coding: utf-8 -*-
"""POST /api/v1/freight/payment — upsert a customer collection from the Sheet."""

from odoo import fields, _, http

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError


ALLOWED_FIELDS = frozenset({
    "request_uuid",
    "external_payment_key",
    "external_reference",
    "shipment_id",
    "amount",
    "currency_code",
    "payment_date",
    "payment_method",
    "collected_by",
    "source",
})
VALID_SOURCES = frozenset({"legacy_xlsx", "google_sheets", "backoffice"})
BILLING_GROUP = "dally_freight_billing.group_dally_freight_billing_api"


class DallyFreightPaymentController(DallyApiController):

    @http.route(
        "/api/v1/freight/payment",
        type="http",
        auth="none",
        readonly=False,
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def sync_payment(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/freight/payment",
            required_scope="freight:payment",
            handler=self._sync_payment,
        )

    def _sync_payment(self, env, payload, api_key):
        if not env.user.has_group(BILLING_GROUP):
            raise DallyApiError(
                403,
                "forbidden",
                _("This API user is not allowed to synchronise freight payments."),
            )

        unknown = sorted(set(payload) - ALLOWED_FIELDS)
        if unknown:
            raise DallyApiError(
                422,
                "unknown_fields",
                _("Unknown freight payment field(s): %s", ", ".join(unknown)),
            )
        self._require(
            payload,
            "external_payment_key",
            "amount",
            "currency_code",
            "payment_method",
        )

        shipment = self._resolve_shipment(env, payload)
        currency = env["res.currency"].search([
            ("name", "=", str(payload["currency_code"]).strip().upper()),
            ("active", "=", True),
        ], limit=1)
        if not currency:
            raise DallyApiError(422, "unknown_currency", _("Unknown or inactive currency."))

        try:
            amount = float(payload["amount"])
        except (TypeError, ValueError) as exc:
            raise DallyApiError(422, "invalid_amount", _("amount must be numeric.")) from exc
        if amount <= 0:
            raise DallyApiError(422, "invalid_amount", _("amount must be greater than zero."))

        payment_date = payload.get("payment_date") or fields.Date.context_today(env.user)
        try:
            payment_date = fields.Date.to_date(payment_date)
        except (TypeError, ValueError) as exc:
            raise DallyApiError(422, "invalid_payment_date", _("Invalid payment_date.")) from exc

        source = str(payload.get("source") or "google_sheets").strip()
        if source not in VALID_SOURCES:
            raise DallyApiError(422, "invalid_source", _("Invalid payment source."))

        collector_name = str(payload.get("collected_by") or "").strip()
        collector = self._resolve_collector(env, collector_name)
        values = {
            "external_payment_key": str(payload["external_payment_key"]).strip(),
            "shipment_id": shipment.id,
            "amount": amount,
            "currency_id": currency.id,
            "payment_date": payment_date,
            "source_method": str(payload["payment_method"]).strip(),
            "source": source,
            "collected_by_id": collector.id or False,
            "collected_by_name": collector_name or False,
        }
        collection, created = env["dally.freight.collection"].upsert_from_sync(values)

        invoice = shipment.invoice_id
        data = {
            "collection_id": collection.id,
            "external_payment_key": collection.external_payment_key,
            "created": created,
            "shipment_id": shipment.id,
            "external_reference": shipment.external_reference,
            "invoice_id": invoice.id or None,
            "invoice_number": invoice.name if invoice else None,
            "invoice_state": invoice.state if invoice else None,
            "invoice_payment_state": invoice.payment_state if invoice else None,
            "amount": collection.amount,
            "currency": collection.currency_id.name,
            "payment_method": collection.source_method,
            "collected_by_id": collection.collected_by_id.id or None,
            "collected_by": collection.collected_by_name,
            "collection_state": collection.state,
            "account_payment_id": collection.payment_id.id or None,
            "error_message": collection.error_message or None,
            "_record": collection,
        }
        return data, 201 if created else 200

    @staticmethod
    def _resolve_shipment(env, payload):
        Shipment = env["dally.shipment"].with_context(active_test=False)
        external_reference = str(payload.get("external_reference") or "").strip()
        shipment_id = payload.get("shipment_id")
        if not external_reference and not shipment_id:
            raise DallyApiError(
                422,
                "missing_shipment",
                _("Provide external_reference or shipment_id."),
            )
        if shipment_id:
            try:
                shipment_id = int(shipment_id)
            except (TypeError, ValueError) as exc:
                raise DallyApiError(
                    422, "invalid_shipment_id", _("shipment_id must be an integer."),
                ) from exc
            shipment = Shipment.search([
                ("id", "=", shipment_id),
                ("company_id", "=", env.company.id),
            ], limit=1)
        else:
            shipment = Shipment.search([
                ("company_id", "=", env.company.id),
                ("external_reference", "=", external_reference),
            ], limit=1)
        if not shipment:
            raise DallyApiError(404, "shipment_not_found", _("Freight shipment not found."))
        if external_reference and shipment.external_reference != external_reference:
            raise DallyApiError(
                409,
                "shipment_reference_mismatch",
                _("shipment_id and external_reference do not identify the same freight file."),
            )
        return shipment

    @staticmethod
    def _resolve_collector(env, name):
        if not name:
            return env["res.users"]
        Users = env["res.users"].with_context(active_test=False)
        exact_login = Users.search([
            ("share", "=", False),
            ("login", "=ilike", name),
        ], limit=2)
        if len(exact_login) == 1:
            return exact_login
        exact_name = Users.search([
            ("share", "=", False),
            ("name", "=ilike", name),
        ], limit=2)
        return exact_name if len(exact_name) == 1 else Users.browse()
