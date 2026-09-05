# -*- coding: utf-8 -*-
"""POST /api/v1/freight/invoice — create/retrieve the native draft invoice."""

from odoo import _, http

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError


ALLOWED_FIELDS = frozenset({"request_uuid", "external_reference", "shipment_id"})
BILLING_GROUP = "dally_freight_billing.group_dally_freight_billing_api"


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
        if not env.user.has_group(BILLING_GROUP):
            raise DallyApiError(
                403,
                "forbidden",
                _("This API user is not allowed to prepare freight invoices."),
            )

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

        invoice, created, kind = shipment._prepare_freight_invoice()

        # La commande rendue doit etre celle qui a produit CETTE facture. Rendre
        # la commande principale pour un complement enverrait le classeur ecrire
        # une reference qui ne couvre pas les lignes qu'il vient de facturer.
        order = invoice.sudo().invoice_line_ids.mapped("sale_line_ids.order_id")[:1]
        if not order:
            order = shipment.sale_order_id

        data = {
            "shipment_id": shipment.id,
            "shipment_reference": shipment.reference,
            "external_reference": shipment.external_reference,
            "sale_order_id": order.id,
            "sale_order_reference": order.name,
            "invoice_id": invoice.id,
            "invoice_number": invoice.name,
            "invoice_state": invoice.state,
            "invoice_kind": kind,
            "covered_line_keys": shipment._invoice_covered_line_keys(invoice),
            "currency": invoice.currency_id.name,
            "amount_untaxed": invoice.amount_untaxed,
            "amount_tax": invoice.amount_tax,
            "amount_total": invoice.amount_total,
            "billing_locked": shipment.billing_locked,
            "created": created,
            "_record": invoice,
        }
        return data, 201 if created else 200
