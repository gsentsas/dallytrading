# -*- coding: utf-8 -*-
"""POST /api/v1/freight/invoice — create/retrieve the native draft invoice."""

from odoo import _, http

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError


ALLOWED_FIELDS = frozenset({"request_uuid", "external_reference", "shipment_id"})


class DallyFreightInvoiceController(DallyApiController):

    @http.route(
        "/api/v1/freight/invoice",
        type="http",
        auth="none",
        readonly=False,
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def prepare_invoice(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/freight/invoice",
            required_scope="freight:invoice",
            handler=self._prepare_invoice,
        )

    def _prepare_invoice(self, env, payload, api_key):
        unknown = sorted(set(payload) - ALLOWED_FIELDS)
        if unknown:
            raise DallyApiError(
                422,
                "unknown_fields",
                _("Unknown freight invoice field(s): %s", ", ".join(unknown)),
            )

        external_reference = str(payload.get("external_reference") or "").strip()
        shipment_id = payload.get("shipment_id")
        if not external_reference and not shipment_id:
            raise DallyApiError(
                422,
                "missing_shipment",
                _("Provide external_reference or shipment_id."),
            )

        Shipment = env["dally.shipment"].with_context(active_test=False)
        domain = []
        if shipment_id:
            try:
                shipment_id = int(shipment_id)
            except (TypeError, ValueError) as exc:
                raise DallyApiError(
                    422, "invalid_shipment_id", _("shipment_id must be an integer."),
                ) from exc
            domain = [("id", "=", shipment_id)]
        else:
            domain = [
                ("company_id", "=", env.company.id),
                ("external_reference", "=", external_reference),
            ]

        shipment = Shipment.search(domain, limit=1)
        if not shipment:
            raise DallyApiError(404, "shipment_not_found", _("Freight shipment not found."))
        if external_reference and shipment.external_reference != external_reference:
            raise DallyApiError(
                409,
                "shipment_reference_mismatch",
                _("shipment_id and external_reference do not identify the same freight file."),
            )

        existed = bool(shipment.invoice_id)
        invoice = shipment.action_prepare_native_freight_invoice()
        data = {
            "shipment_id": shipment.id,
            "shipment_reference": shipment.reference,
            "external_reference": shipment.external_reference,
            "sale_order_id": shipment.sale_order_id.id,
            "sale_order_reference": shipment.sale_order_id.name,
            "invoice_id": invoice.id,
            "invoice_number": invoice.name,
            "invoice_state": invoice.state,
            "currency": invoice.currency_id.name,
            "amount_untaxed": invoice.amount_untaxed,
            "amount_tax": invoice.amount_tax,
            "amount_total": invoice.amount_total,
            "billing_locked": shipment.billing_locked,
            "created": not existed,
            "_record": invoice,
        }
        return data, 200 if existed else 201
