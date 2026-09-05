# -*- coding: utf-8 -*-
"""Freight collection ledger and safe promotion to native Odoo payments."""

import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


COLLECTION_STATES = [
    ("pending", "Pending invoice/configuration"),
    ("registered", "Registered in accounting"),
    ("error", "Registration error"),
    ("cancelled", "Cancelled from source"),
]


class DallyFreightPaymentChannel(models.Model):
    _name = "dally.freight.payment.channel"
    _description = "DallyTrading Freight Payment Channel"
    _order = "name, currency_id, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one("res.currency", required=True, index=True)
    journal_id = fields.Many2one(
        "account.journal",
        required=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash', 'credit'))]",
        check_company=True,
    )
    payment_method_line_id = fields.Many2one(
        "account.payment.method.line",
        string="Inbound Payment Method",
        required=True,
        domain="[('journal_id', '=', journal_id), ('payment_type', '=', 'inbound')]",
        check_company=True,
    )

    _channel_unique = models.Constraint(
        "UNIQUE(company_id, code, currency_id)",
        "A freight payment channel code can be configured only once per company and currency.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code"):
                vals["code"] = self._normalize_code(vals["code"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("code"):
            vals["code"] = self._normalize_code(vals["code"])
        return super().write(vals)

    @api.constrains("journal_id", "payment_method_line_id", "currency_id")
    def _check_payment_channel(self):
        for channel in self:
            if channel.payment_method_line_id.journal_id != channel.journal_id:
                raise ValidationError(_("The payment method must belong to the selected journal."))
            journal_currency = channel.journal_id.currency_id
            if journal_currency and journal_currency != channel.currency_id:
                raise ValidationError(
                    _("A currency-specific journal must use the same currency as the channel.")
                )

    @staticmethod
    def _normalize_code(value):
        return "_".join(str(value or "").strip().lower().split())

    @api.model
    def _find_channel(self, company, currency, source_code):
        code = self._normalize_code(source_code)
        if not code:
            return self.browse()
        return self.search([
            ("active", "=", True),
            ("company_id", "=", company.id),
            ("currency_id", "=", currency.id),
            ("code", "=", code),
        ], limit=1)


class DallyFreightCollection(models.Model):
    _name = "dally.freight.collection"
    _description = "DallyTrading Freight Customer Collection"
    _inherit = ["mail.thread"]
    _order = "payment_date desc, id desc"

    external_payment_key = fields.Char(required=True, index=True, copy=False)
    company_id = fields.Many2one(
        related="shipment_id.company_id",
        store=True,
        index=True,
        readonly=True,
    )
    shipment_id = fields.Many2one(
        "dally.shipment",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    invoice_id = fields.Many2one(
        "account.move",
        related="shipment_id.invoice_id",
        store=True,
        readonly=True,
    )
    target_invoice_id = fields.Many2one(
        "account.move",
        string="Facture ciblee",
        copy=False,
        index=True,
        ondelete="restrict",
        help=(
            "La piece que cet encaissement solde. Vide, il solde la facture "
            "principale du dossier ; renseignee, une facture complementaire."
        ),
    )
    partner_id = fields.Many2one(
        "res.partner",
        related="shipment_id.partner_id",
        store=True,
        readonly=True,
    )
    amount = fields.Monetary(required=True, currency_field="currency_id", tracking=True)
    currency_id = fields.Many2one("res.currency", required=True, index=True)
    payment_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    source_method = fields.Char(required=True, tracking=True)
    source = fields.Selection(
        [("legacy_xlsx", "Legacy Excel"), ("google_sheets", "Google Sheets"), ("backoffice", "Back Office")],
        default="google_sheets",
        required=True,
    )
    collected_by_id = fields.Many2one(
        "res.users",
        string="Collected By",
        domain=[("share", "=", False)],
        copy=False,
    )
    collected_by_name = fields.Char(copy=False)
    state = fields.Selection(COLLECTION_STATES, default="pending", required=True, index=True, copy=False)
    payment_id = fields.Many2one("account.payment", readonly=True, copy=False, ondelete="restrict")
    error_message = fields.Char(readonly=True, copy=False)
    last_attempt_at = fields.Datetime(readonly=True, copy=False)

    _external_payment_key_unique = models.Constraint(
        "UNIQUE(external_payment_key)",
        "The external freight payment key must be unique.",
    )

    @api.constrains("amount")
    def _check_positive_amount(self):
        for collection in self:
            if collection.amount <= 0:
                raise ValidationError(_("A freight collection amount must be greater than zero."))

    @api.model
    def upsert_from_sync(self, values):
        """Business-idempotent collection upsert from the trusted Sheet.

        A cancelled, non-accounted collection can be reactivated by sending the
        same business key again. Once a native ``account.payment`` exists, the
        collection remains immutable and must be corrected through accounting.
        """
        key = str(values.get("external_payment_key") or "").strip()
        if not key:
            raise ValidationError(_("external_payment_key is required."))

        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ["freight-payment:%s" % key],
        )
        existing = self.search([("external_payment_key", "=", key)], limit=1)
        if existing and existing.payment_id:
            immutable = {
                "shipment_id": values.get("shipment_id"),
                "amount": values.get("amount"),
                "currency_id": values.get("currency_id"),
                "payment_date": values.get("payment_date"),
                "source_method": values.get("source_method"),
            }
            # La cible ne se compare que si l'appelant en exprime une. Absente
            # du payload, rien n'est demande et rien ne change — c'est le
            # comportement historique. Presente et differente, la refuser ici
            # est la SEULE protection : la sortie anticipee ci-dessous
            # n'ecrit rien, donc la garde ORM ne verrait jamais passer le
            # champ et l'API repondrait 200 sans avoir redirige quoi que ce
            # soit. Le classeur croirait la redirection faite.
            if "target_invoice_id" in values:
                immutable["target_invoice_id"] = values.get("target_invoice_id")
            for field_name, new_value in immutable.items():
                current = existing[field_name]
                current_value = current.id if hasattr(current, "id") else current
                if field_name == "payment_date":
                    new_value = fields.Date.to_date(new_value)
                if current_value != new_value:
                    raise UserError(
                        _("Registered payment %s is immutable; create a corrective payment instead.", key)
                    )
            return existing, False

        values = dict(values)
        values.update({"state": "pending", "error_message": False})

        if existing:
            if values.get("shipment_id") and existing.shipment_id.id != values["shipment_id"]:
                raise ValidationError(_("The payment key already belongs to another freight shipment."))
            existing.write(values)
            collection = existing
            created = False
        else:
            collection = self.create(values)
            created = True

        collection._try_register_native_payment()
        return collection, created

    def action_cancel_from_sync(self, reason=None):
        """Cancel a Sheet-managed collection that has not reached accounting."""
        now = fields.Datetime.now()
        for collection in self:
            if collection.payment_id:
                raise UserError(
                    _(
                        "Registered payment %s cannot be cancelled from Google Sheets; "
                        "create an accounting correction instead.",
                        collection.external_payment_key,
                    )
                )
            collection.write({
                "state": "cancelled",
                "error_message": reason or _("Cancelled by source reconciliation."),
                "last_attempt_at": now,
            })
        return True

    def _try_register_native_payment(self):
        """Register/reconcile when the invoice is posted and mapping is ready.

        Configuration or business failures do not roll back the collection. They
        are surfaced on the record so the cash entry is never lost merely because
        accounting configuration is incomplete.
        """
        for collection in self:
            if collection.state == "cancelled":
                continue
            if collection.payment_id:
                collection.write({"state": "registered", "error_message": False})
                continue

            # La cible explicite prime. Un complement ne se rattache pas au
            # dossier — s'en tenir a `invoice_id` solderait la facture
            # principale avec l'argent d'une autre piece.
            invoice = collection.target_invoice_id or collection.invoice_id
            if not invoice or invoice.state != "posted":
                collection.write({
                    "state": "pending",
                    "error_message": _("Waiting for the customer invoice to be posted."),
                    "last_attempt_at": fields.Datetime.now(),
                })
                continue

            channel = self.env["dally.freight.payment.channel"]._find_channel(
                collection.company_id,
                collection.currency_id,
                collection.source_method,
            )
            if not channel:
                collection.write({
                    "state": "pending",
                    "error_message": _(
                        "No payment channel is configured for %(method)s / %(currency)s.",
                        method=collection.source_method,
                        currency=collection.currency_id.name,
                    ),
                    "last_attempt_at": fields.Datetime.now(),
                })
                continue

            try:
                with self.env.cr.savepoint():
                    wizard = self.env["account.payment.register"].with_context(
                        active_model="account.move",
                        active_ids=invoice.ids,
                    ).create({
                        "payment_date": collection.payment_date,
                        "amount": collection.amount,
                        "currency_id": collection.currency_id.id,
                        "journal_id": channel.journal_id.id,
                        "payment_method_line_id": channel.payment_method_line_id.id,
                        "communication": collection.external_payment_key,
                        "group_payment": True,
                    })
                    payments = wizard._create_payments()
                    payment = payments[:1]
                    if not payment:
                        raise UserError(_("Odoo did not create a payment."))
                    payment.write({
                        "dally_external_payment_key": collection.external_payment_key,
                        "dally_collected_by_id": collection.collected_by_id.id or False,
                        "dally_freight_shipment_id": collection.shipment_id.id,
                    })
                collection.write({
                    "payment_id": payment.id,
                    "state": "registered",
                    "error_message": False,
                    "last_attempt_at": fields.Datetime.now(),
                })
            except (UserError, ValidationError, AccessError) as exc:
                collection.write({
                    "state": "error",
                    "error_message": str(exc)[:500],
                    "last_attempt_at": fields.Datetime.now(),
                })
            except Exception:  # accounting extension failure must not lose cash intake
                _logger.exception(
                    "Unexpected error registering freight collection %s",
                    collection.external_payment_key,
                )
                collection.write({
                    "state": "error",
                    "error_message": _("Unexpected accounting error; see server logs."),
                    "last_attempt_at": fields.Datetime.now(),
                })
        return True


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_post(self):
        result = super().action_post()
        sorties = self.filtered(lambda move: move.move_type == "out_invoice")
        if sorties:
            # Une facture complementaire ne porte pas `dally_freight_shipment_id` :
            # filtrer dessus laisserait ses encaissements en attente pour
            # toujours. On reveille donc tout ce qui vise CETTE piece, par le
            # lien historique comme par la cible explicite.
            collections = self.env["dally.freight.collection"].search([
                "&",
                ("payment_id", "=", False),
                "&",
                ("state", "!=", "cancelled"),
                "|",
                ("target_invoice_id", "in", sorties.ids),
                "&",
                ("target_invoice_id", "=", False),
                ("invoice_id", "in", sorties.ids),
            ])
            if collections:
                collections._try_register_native_payment()
        return result
