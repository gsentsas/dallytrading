# -*- coding: utf-8 -*-
"""Back-office operations for Freight customer notifications.

No delivery happens from the UI. Internal users get queue health/navigation,
and Managers may put a terminally failed row back into the durable outbox. The
regular cron remains the only SMTP delivery path.
"""

from odoo import fields, models
from odoo.exceptions import AccessError, UserError


class DallyShipmentNotificationOps(models.Model):
    _inherit = "dally.shipment.notification"

    manual_retry_count = fields.Integer(
        string="Relances manuelles",
        default=0,
        readonly=True,
        help="Nombre de fois où un Manager a remis cette notification en file.",
    )
    last_retry_at = fields.Datetime(
        string="Dernière relance manuelle",
        readonly=True,
    )

    def action_retry_delivery(self):
        """Reset eligible failed rows to pending, without sending from the UI."""
        if not self.env.user.has_group("dally_core.group_dally_manager"):
            raise AccessError("Seul un Manager peut relancer une notification Freight.")

        for notification in self:
            if notification.status != "failed":
                raise UserError(
                    "Seules les notifications en échec peuvent être relancées."
                )
            reason = notification._dally_delivery_skip_reason()
            if reason:
                raise UserError(
                    "La notification ne peut pas être relancée : %s" % reason
                )

        now = fields.Datetime.now()
        for notification in self:
            notification.write({
                "status": "pending",
                "attempts": 0,
                "last_error": False,
                "mail_id": False,
                "sent_at": False,
                "manual_retry_count": notification.manual_retry_count + 1,
                "last_retry_at": now,
            })
        return True


class DallyShipmentNotificationCounters(models.Model):
    _inherit = "dally.shipment"

    notification_count = fields.Integer(
        string="Notifications",
        compute="_compute_notification_counters",
        groups="dally_core.group_dally_readonly",
    )
    notification_pending_count = fields.Integer(
        string="Notifications en attente",
        compute="_compute_notification_counters",
        groups="dally_core.group_dally_readonly",
    )
    notification_failed_count = fields.Integer(
        string="Notifications en échec",
        compute="_compute_notification_counters",
        groups="dally_core.group_dally_readonly",
    )

    def _compute_notification_counters(self):
        for shipment in self:
            notifications = shipment.notification_ids
            shipment.notification_count = len(notifications)
            shipment.notification_pending_count = len(
                notifications.filtered(lambda n: n.status == "pending")
            )
            shipment.notification_failed_count = len(
                notifications.filtered(lambda n: n.status == "failed")
            )

    def _notification_action(self, extra_domain=None, context=None):
        self.ensure_one()
        action = self.env.ref(
            "dally_freight_notifications.dally_shipment_notification_action"
        ).read()[0]
        domain = [("shipment_id", "=", self.id)]
        if extra_domain:
            domain += list(extra_domain)
        action["domain"] = domain
        action["context"] = context or {}
        return action

    def action_view_notifications(self):
        return self._notification_action(context={"search_default_group_status": 1})

    def action_view_pending_notifications(self):
        return self._notification_action(
            extra_domain=[("status", "=", "pending")],
            context={"search_default_filter_pending": 1},
        )

    def action_view_failed_notifications(self):
        return self._notification_action(
            extra_domain=[("status", "=", "failed")],
            context={"search_default_filter_failed": 1},
        )
