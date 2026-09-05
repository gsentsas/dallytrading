# -*- coding: utf-8 -*-
"""Freight payment endpoints used by the trusted Google Sheet connector."""

from odoo import fields, _, http

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError


ALLOWED_FIELDS = frozenset({
    "request_uuid",
    "external_payment_key",
    # Facultatif. Absent, la cible reste la facture principale du dossier —
    # exactement le comportement historique. Present, il est valide piece par
    # piece dans `_resolve_target_invoice`.
    "invoice_id",
    "external_reference",
    "shipment_id",
    "amount",
    "currency_code",
    "payment_date",
    "payment_method",
    "collected_by",
    "source",
})
RECONCILE_FIELDS = frozenset({
    "request_uuid",
    "external_reference",
    "shipment_id",
    "active_payment_keys",
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

    @http.route(
        "/api/v1/freight/payment/reconcile",
        type="http",
        auth="none",
        readonly=False,
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def reconcile_payments(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/freight/payment/reconcile",
            required_scope="freight:payment",
            handler=self._reconcile_payments,
        )

    def _check_group(self, env):
        if not env.user.has_group(BILLING_GROUP):
            raise DallyApiError(
                403,
                "forbidden",
                _("This API user is not allowed to synchronise freight payments."),
            )

    def _sync_payment(self, env, payload, api_key):
        self._check_group(env)

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

        source = self._source(payload.get("source"))
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
        # Trois etats, pas deux. `upsert_from_sync` lit l'ABSENCE de la cle
        # comme « ne touche pas a la cible existante » ; envoyer la cle a False
        # dit au contraire « reviens a la principale ». Confondre les deux
        # laisserait un rejeu conserver un complement que le classeur vient
        # justement de retirer, et l'encaissement irait sur la mauvaise piece
        # des qu'il deviendrait comptabilisable.
        if "invoice_id" in payload:
            cible = self._resolve_target_invoice(env, shipment, payload)
            values["target_invoice_id"] = cible.id or False
        collection, created = env["dally.freight.collection"].upsert_from_sync(values)

        # La reponse expose la piece REELLEMENT soldee, pas celle du dossier :
        # le classeur doit pouvoir verifier qu'il a vise la bonne.
        invoice = collection.target_invoice_id or collection.invoice_id
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

    def _reconcile_payments(self, env, payload, api_key):
        """Align Sheet-managed pending collections with the current Sheet set.

        Missing legacy/google-sheet collections are cancelled only while they
        have no native ``account.payment``. Back-office collections are never
        touched. Registered accounting payments are returned as blocked so the
        caller can request a proper accounting correction instead of silently
        rewriting history.
        """
        self._check_group(env)
        unknown = sorted(set(payload) - RECONCILE_FIELDS)
        if unknown:
            raise DallyApiError(
                422,
                "unknown_fields",
                _("Unknown freight payment reconcile field(s): %s", ", ".join(unknown)),
            )

        shipment = self._resolve_shipment(env, payload)
        active_keys = payload.get("active_payment_keys")
        if not isinstance(active_keys, list):
            raise DallyApiError(
                422,
                "invalid_active_payment_keys",
                _("active_payment_keys must be an array."),
            )
        clean_keys = []
        seen = set()
        for item in active_keys:
            key = str(item or "").strip()
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            clean_keys.append(key)

        source = self._source(payload.get("source"))
        managed_sources = [source]
        if source == "google_sheets":
            managed_sources.append("legacy_xlsx")

        collections = env["dally.freight.collection"].search([
            ("shipment_id", "=", shipment.id),
            ("source", "in", managed_sources),
        ])
        active_set = set(clean_keys)
        cancelled = []
        already_cancelled = []
        blocked_registered = []

        for collection in collections:
            if collection.external_payment_key in active_set:
                continue
            if collection.payment_id:
                blocked_registered.append(collection.external_payment_key)
                continue
            if collection.state == "cancelled":
                already_cancelled.append(collection.external_payment_key)
                continue
            collection.action_cancel_from_sync(
                _("Removed from the current Google Sheets payment set.")
            )
            cancelled.append(collection.external_payment_key)

        data = {
            "shipment_id": shipment.id,
            "external_reference": shipment.external_reference,
            "active_payment_keys": clean_keys,
            "cancelled_payment_keys": cancelled,
            "already_cancelled_payment_keys": already_cancelled,
            "blocked_registered_payment_keys": blocked_registered,
            "_record": shipment,
        }
        return data, 200

    @staticmethod
    def _resolve_target_invoice(env, shipment, payload):
        """La facture visee, si le classeur en nomme une.

        Absente, on ne decide rien : le moteur solde la facture principale,
        exactement comme avant. Presente, elle est verifiee sur quatre points —
        nature, societe, client, appartenance au dossier — parce qu'un
        encaissement dirige vers la mauvaise piece est un ecart comptable que
        rien ne rattrape automatiquement.

        L'appartenance se lit par les lignes : une facture complementaire ne
        porte pas `dally_freight_shipment_id`, et l'exiger la rejetterait
        toujours.
        """
        brut = payload.get("invoice_id")
        if brut in (None, "", False):
            return env["account.move"].browse()
        try:
            invoice_id = int(brut)
        except (TypeError, ValueError) as exc:
            raise DallyApiError(
                422, "invalid_invoice_id", _("invoice_id must be an integer.")) from exc

        invoice = env["account.move"].browse(invoice_id).exists()
        if not invoice:
            raise DallyApiError(404, "invoice_not_found", _("Invoice not found."))
        if invoice.move_type != "out_invoice":
            raise DallyApiError(
                422, "invalid_invoice_type", _("Only a customer invoice can be targeted."))
        # `draft` reste accepte : un encaissement peut precede la
        # comptabilisation du complement, la collection attend, et
        # `action_post` la reveille. `cancel` n'a pas cette issue — la piece ne
        # sera jamais comptabilisee, et la collection resterait `pending` pour
        # toujours en donnant l'illusion d'un paiement pris en compte.
        if invoice.state == "cancel":
            raise DallyApiError(
                422, "invoice_cancelled", _("A cancelled invoice cannot be targeted."))
        if invoice.company_id != shipment.company_id:
            raise DallyApiError(
                409, "invoice_company_mismatch", _("Invoice belongs to another company."))
        if invoice.partner_id != shipment.partner_id:
            raise DallyApiError(
                409, "invoice_partner_mismatch", _("Invoice belongs to another customer."))

        if invoice == shipment.invoice_id:
            return invoice
        # `sudo` : l'utilisateur d'integration ne lit pas `sale.order.line`.
        # Sans cela la traversee rend une liste vide et TOUTE facture
        # complementaire serait rejetee comme etrangere au dossier.
        rattachee = invoice.sudo().invoice_line_ids.mapped(
            "sale_line_ids.dally_freight_package_id.shipment_id")
        if shipment not in rattachee:
            raise DallyApiError(
                409,
                "invoice_shipment_mismatch",
                _("Invoice does not belong to this freight file."))
        return invoice

    @staticmethod
    def _source(value):
        source = str(value or "google_sheets").strip()
        if source not in VALID_SOURCES:
            raise DallyApiError(422, "invalid_source", _("Invalid payment source."))
        return source

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
