# -*- coding: utf-8 -*-
"""Durable freight notification outbox and delivery worker.

The business transition never sends mail. It only writes one durable outbox row
per automatic customer-visible event. A cron later claims pending rows with
``FOR UPDATE SKIP LOCKED`` and performs the SMTP send.

Concurrency is exactly-once at the database claim level, not at the SMTP
protocol level: if SMTP accepts a message and the worker dies before PostgreSQL
commits ``status='sent'``, a later retry can theoretically send the same message
again. SMTP does not provide an external idempotency key, so claiming more would
be incorrect.
"""

import re

from odoo import api, fields, models


MOTIF_NON_PUBLIE = "event_not_published"
MOTIF_POLITIQUE = "policy_no_notify"
MOTIF_SANS_GABARIT = "no_template"
MOTIF_SANS_ADRESSE = "no_email"
MOTIF_REFUS_CLIENT = "partner_opted_out"
MOTIF_SANS_DESTINATAIRE = "no_partner"

MAX_ATTEMPTS = 5
CRON_BATCH_SIZE = 100


class DallyShipmentNotification(models.Model):
    _name = "dally.shipment.notification"
    _description = "Notification client d'une expédition"
    _order = "created_at desc, id desc"
    _rec_name = "shipment_reference"

    # Rattachements techniques. Les templates ne doivent jamais naviguer vers
    # ces relations : leur contenu vient exclusivement du snapshot ci-dessous.
    shipment_id = fields.Many2one(
        "dally.shipment", string="Expédition", required=True,
        ondelete="cascade", index=True,
    )
    event_id = fields.Many2one(
        "dally.shipment.event", string="Événement", required=True,
        ondelete="cascade", index=True,
    )
    state = fields.Selection(
        related="event_id.status", string="État", store=True, index=True,
    )
    partner_id = fields.Many2one(
        "res.partner", string="Destinataire", ondelete="restrict", index=True,
    )
    email = fields.Char(
        string="Adresse",
        help="Adresse utilisée pour l'envoi. Initialisée lors de la mise en file "
             "et rafraîchie avec l'adresse courante du partenaire juste avant "
             "la livraison.",
    )
    language_code = fields.Char(
        string="Langue", readonly=True,
        help="Langue figée à la mise en file : langue du partenaire, puis de la "
             "société, puis fr_FR en dernier recours.",
    )

    status = fields.Selection(
        [
            ("pending", "En attente"),
            ("sent", "Envoyée"),
            ("failed", "Échec"),
            ("skipped", "Ignorée"),
        ],
        string="Statut", default="pending", required=True, index=True,
    )
    mail_id = fields.Many2one(
        "mail.mail", string="Courriel", ondelete="set null", readonly=True,
    )
    attempts = fields.Integer(string="Tentatives", default=0, readonly=True)
    last_error = fields.Char(
        string="Dernier motif", readonly=True,
        help="Motif d'abstention ou erreur de livraison nettoyée. Les URL et "
             "jetons de suivi n'y sont jamais conservés.",
    )
    created_at = fields.Datetime(
        string="Créée le", required=True, readonly=True,
        default=fields.Datetime.now,
    )
    sent_at = fields.Datetime(string="Envoyée le", readonly=True)

    # Snapshot client-safe. Les templates n'utilisent que ces colonnes.
    shipment_reference = fields.Char(string="Référence", readonly=True)
    customer_label = fields.Char(string="Libellé client", readonly=True)
    customer_message = fields.Char(string="Message client", readonly=True)
    origin_label = fields.Char(string="Origine", readonly=True)
    destination_label = fields.Char(string="Destination", readonly=True)
    event_date = fields.Datetime(string="Date de l'événement", readonly=True)
    tracking_url = fields.Char(string="Lien de suivi", readonly=True)

    _event_uniq = models.Constraint(
        "unique(event_id)", "Cet événement a déjà sa notification.")

    @api.model_create_multi
    def create(self, vals_list):
        """Freeze rendering language at enqueue time.

        The template itself never follows ``partner_id`` or ``shipment_id``.
        That keeps the rendered surface limited to the allowlisted snapshot.
        """
        Partner = self.env["res.partner"]
        Shipment = self.env["dally.shipment"]
        for vals in vals_list:
            if vals.get("language_code"):
                continue
            partner = Partner.browse(vals.get("partner_id") or []).exists()
            shipment = Shipment.browse(vals.get("shipment_id") or []).exists()
            company = shipment.company_id if shipment else self.env.company
            vals["language_code"] = (
                (partner.lang if partner else False)
                or company.partner_id.lang
                or self.env.context.get("lang")
                or "fr_FR"
            )
        return super().create(vals_list)

    def _dally_delivery_skip_reason(self):
        """Revalidate all customer-facing conditions immediately before send."""
        self.ensure_one()

        if not self.event_id or not self.event_id.visible_to_customer:
            return MOTIF_NON_PUBLIE

        policy = self.env["dally.freight.state.policy"]._dally_policy_for(self.state)
        if (
            not policy
            or not policy.visible_in_tracking
            or not policy.notify_customer
        ):
            return MOTIF_POLITIQUE
        if (
            not policy.email_template_id
            or policy.email_template_id.model != self._name
        ):
            return MOTIF_SANS_GABARIT
        if not self.partner_id:
            return MOTIF_SANS_DESTINATAIRE
        if not self.partner_id.dally_freight_notify:
            return MOTIF_REFUS_CLIENT
        if not self.partner_id.email or not self.email:
            return MOTIF_SANS_ADRESSE
        return False

    def _dally_sanitize_delivery_error(self, exc):
        """Keep diagnostics while removing URLs and query-string secrets."""
        self.ensure_one()
        text = str(exc or "delivery_failed")
        if self.tracking_url:
            text = text.replace(self.tracking_url, "[tracking-url-redacted]")
        text = re.sub(r"https?://[^\s<>\"']+", "[url-redacted]", text)
        text = re.sub(
            r"(?i)([?&](?:t|token|v)=)[^&\s<>\"']+",
            r"\1[redacted]",
            text,
        )
        text = text.replace("\r", " ").replace("\n", " ")
        return "%s: %s" % (exc.__class__.__name__, text[:1500])

    def _dally_mark_skipped(self, reason):
        self.ensure_one()
        self.sudo().write({"status": "skipped", "last_error": reason})

    def _dally_deliver_one(self):
        """Deliver one claimed pending row without affecting the shipment state."""
        self.ensure_one()
        if self.status != "pending":
            return False

        reason = self._dally_delivery_skip_reason()
        if reason:
            self._dally_mark_skipped(reason)
            return False

        # Revalidate the actual destination. If the customer corrected their
        # address after enqueue, use the current address and retain the address
        # that was effectively used in the outbox audit row.
        current_email = (self.partner_id.email or "").strip()
        if current_email != (self.email or "").strip():
            self.sudo().write({"email": current_email})

        policy = self.env["dally.freight.state.policy"]._dally_policy_for(self.state)
        template = policy.email_template_id
        attempt_no = self.attempts + 1

        try:
            with self.env.cr.savepoint():
                mail_id = template.with_context(
                    lang=self.language_code or "fr_FR",
                ).send_mail(
                    self.id,
                    force_send=True,
                    raise_exception=True,
                )
                self.sudo().write({
                    "status": "sent",
                    "mail_id": mail_id or False,
                    "attempts": attempt_no,
                    "sent_at": fields.Datetime.now(),
                    "last_error": False,
                })
            return True
        except Exception as exc:  # SMTP/provider errors must not escape the cron.
            self.sudo().write({
                "attempts": attempt_no,
                "last_error": self._dally_sanitize_delivery_error(exc),
                "status": "failed" if attempt_no >= MAX_ATTEMPTS else "pending",
            })
            return False

    @api.model
    def _cron_process_pending_notifications(self):
        """Deliver at most one bounded batch, committing each claimed row.

        A row is claimed with ``FOR UPDATE SKIP LOCKED``. Only one row is locked
        at a time; after delivery, Odoo 19's cron progress API commits that row
        before the next claim. This means a worker crash can at worst reopen the
        SMTP ambiguity window for the single message being processed, not the
        whole batch.
        """
        processed = 0
        Cron = self.env["ir.cron"]

        while processed < CRON_BATCH_SIZE:
            self.env.cr.execute(
                """
                SELECT id
                  FROM dally_shipment_notification
                 WHERE status = 'pending'
                   AND attempts < %s
                 ORDER BY created_at, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
                """,
                (MAX_ATTEMPTS,),
            )
            row = self.env.cr.fetchone()
            if not row:
                break

            self.browse(row[0])._dally_deliver_one()
            processed += 1

            # In a real ir.cron run this records progress and commits. When
            # called manually, Odoo 19 documents that it simply commits.
            Cron._commit_progress(processed=1)

        return processed
