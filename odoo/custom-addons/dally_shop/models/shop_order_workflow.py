# -*- coding: utf-8 -*-
"""Workflow commercial des commandes boutique.

Le checkout public crée toujours une ``sale.order`` en brouillon. Ce fichier
ajoute un état métier distinct de ``sale.order.state`` afin qu'un opérateur puisse
accepter ou refuser une demande sans déclencher prématurément les effets natifs de
``action_confirm`` (picking, engagement stock, etc.).

Les transitions passent exclusivement par des méthodes métier : l'opérateur
boutique conserve des ACL de lecture seule sur ``sale.order``. Les écritures sont
faites sous ``sudo()`` seulement après vérification explicite du rôle et du fait
qu'il s'agit bien d'une commande boutique.
"""

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


SHOP_WORKFLOW_STATES = [
    ("received", "Commande reçue"),
    ("validated", "Commande validée"),
    ("rejected", "Commande refusée"),
    ("cancelled", "Commande annulée"),
]

SHOP_WORKFLOW_CLIENT_LABELS = {
    "received": "Commande reçue — en attente de validation",
    "validated": "Commande validée",
    "rejected": "Commande refusée",
    "cancelled": "Commande annulée",
}

_ALLOWED_TRANSITIONS = {
    "received": {"validated", "rejected"},
    "validated": {"cancelled"},
    "rejected": set(),
    "cancelled": set(),
}

_REASON_REQUIRED = {"rejected", "cancelled"}


class SaleOrderShopWorkflow(models.Model):
    _inherit = "sale.order"

    dally_shop_workflow_state = fields.Selection(
        selection=SHOP_WORKFLOW_STATES,
        string="État boutique",
        copy=False,
        index=True,
        readonly=True,
        help=(
            "État métier de la commande boutique. Il est volontairement séparé "
            "de l'état natif de sale.order afin qu'une validation commerciale ne "
            "déclenche pas encore les effets de confirmation Vente."
        ),
    )
    dally_shop_customer_reason = fields.Text(
        string="Motif communiqué au client",
        copy=False,
        readonly=True,
        help=(
            "Motif client-safe utilisé uniquement pour un refus ou une annulation. "
            "Ne pas y placer de note interne, coût, marge ou information fournisseur."
        ),
    )
    dally_shop_transition_ids = fields.One2many(
        comodel_name="dally.shop.order.transition",
        inverse_name="order_id",
        string="Historique boutique",
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for values in vals_list:
            values = dict(values)
            if values.get("dally_shop_order"):
                values.setdefault("dally_shop_workflow_state", "received")
            prepared.append(values)

        orders = super().create(prepared)
        for order in orders.filtered("dally_shop_order"):
            if order.dally_shop_workflow_state == "received":
                transition = order._dally_shop_log_transition(False, "received")
                order._dally_shop_queue_workflow_notification(transition)
        return orders

    def _dally_shop_require_workflow_operator(self):
        self.ensure_one()
        if not self.dally_shop_order:
            raise ValidationError(_("Cette action est réservée aux commandes boutique."))

        if self.env.su:
            return

        allowed = (
            self.env.user.has_group("dally_shop.group_dally_shop_operations")
            or self.env.user.has_group("dally_core.group_dally_manager")
        )
        if not allowed:
            raise AccessError(_("Vous n'êtes pas autorisé à gérer cette commande boutique."))

    def _dally_shop_log_transition(self, from_state, to_state, reason=None):
        self.ensure_one()
        return self.env["dally.shop.order.transition"].sudo().create({
            "order_id": self.id,
            "from_state": from_state or False,
            "to_state": to_state,
            "reason": reason or False,
            "changed_by_id": self.env.user.id,
        })

    def _dally_shop_queue_workflow_notification(self, transition):
        """Met l'e-mail dans la file Odoo, sans aucun envoi synchrone.

        La transaction qui écrit la transition crée également ``mail.mail``. Si
        elle est annulée, l'e-mail disparaît avec elle ; si elle commit, le cron
        standard d'Odoo l'enverra ensuite. Aucun ``send()`` n'est appelé ici.
        """
        self.ensure_one()
        recipient = (self.partner_id.email or "").strip()
        if not recipient:
            return False

        state = transition.to_state
        label = SHOP_WORKFLOW_CLIENT_LABELS.get(state)
        if not label:
            return False

        reference = escape(self.name or "")
        label_html = escape(label)
        reason = (transition.reason or "").strip()
        reason_html = ""
        if reason:
            reason_html = "<p><strong>Motif :</strong> %s</p>" % escape(reason)

        body_html = (
            "<p>Bonjour,</p>"
            "<p>La commande <strong>%s</strong> est maintenant : "
            "<strong>%s</strong>.</p>%s"
            "<p>DallyTrading</p>"
        ) % (reference, label_html, reason_html)

        sender = (
            (self.company_id.email or "").strip()
            or (self.env.user.email or "").strip()
            or "noreply@dallytrading.com"
        )

        self.env["mail.mail"].sudo().create({
            "subject": _("DallyTrading — commande %s", self.name),
            "body_html": body_html,
            "email_from": sender,
            "email_to": recipient,
            "auto_delete": True,
        })
        transition.sudo().write({"notification_queued": True})
        return True

    def _dally_shop_transition(self, target_state, reason=None):
        self.ensure_one()
        self._dally_shop_require_workflow_operator()

        current = self.dally_shop_workflow_state or "received"
        if current == target_state:
            return True

        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        if target_state not in allowed:
            raise ValidationError(
                _(
                    "Transition boutique interdite : %(source)s → %(target)s.",
                    source=current,
                    target=target_state,
                )
            )

        cleaned_reason = (reason or "").strip()
        if target_state in _REASON_REQUIRED and not cleaned_reason:
            raise ValidationError(_("Un motif destiné au client est obligatoire."))
        if target_state not in _REASON_REQUIRED:
            cleaned_reason = ""

        order = self.sudo()
        order.write({
            "dally_shop_workflow_state": target_state,
            "dally_shop_customer_reason": cleaned_reason or False,
        })
        transition = order.with_env(self.env)._dally_shop_log_transition(
            current, target_state, cleaned_reason
        )
        order.with_env(self.env)._dally_shop_queue_workflow_notification(transition)
        return True

    def action_dally_shop_validate(self):
        for order in self:
            order._dally_shop_transition("validated")
        return True

    def _dally_shop_reason_wizard_action(self, target_state):
        self.ensure_one()
        self._dally_shop_require_workflow_operator()
        return {
            "type": "ir.actions.act_window",
            "name": _("Motif de la transition"),
            "res_model": "dally.shop.order.transition.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "dally_shop.view_dally_shop_order_transition_wizard"
            ).id,
            "target": "new",
            "context": {
                "default_order_id": self.id,
                "default_target_state": target_state,
            },
        }

    def action_dally_shop_open_reject(self):
        self.ensure_one()
        if (self.dally_shop_workflow_state or "received") != "received":
            raise ValidationError(_("Seule une commande reçue peut être refusée."))
        return self._dally_shop_reason_wizard_action("rejected")

    def action_dally_shop_open_cancel(self):
        self.ensure_one()
        if self.dally_shop_workflow_state != "validated":
            raise ValidationError(_("Seule une commande validée peut être annulée."))
        return self._dally_shop_reason_wizard_action("cancelled")


class DallyShopOrderTransition(models.Model):
    _name = "dally.shop.order.transition"
    _description = "Transition de commande boutique"
    _order = "changed_at desc, id desc"

    order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Commande",
        required=True,
        index=True,
        ondelete="cascade",
    )
    from_state = fields.Selection(
        selection=SHOP_WORKFLOW_STATES,
        string="État précédent",
        readonly=True,
    )
    to_state = fields.Selection(
        selection=SHOP_WORKFLOW_STATES,
        string="Nouvel état",
        required=True,
        readonly=True,
    )
    reason = fields.Text(string="Motif client", readonly=True)
    changed_at = fields.Datetime(
        string="Date",
        default=fields.Datetime.now,
        required=True,
        readonly=True,
    )
    changed_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Par",
        required=True,
        readonly=True,
        ondelete="restrict",
    )
    notification_queued = fields.Boolean(
        string="Notification mise en file",
        default=False,
        readonly=True,
    )


class DallyShopOrderTransitionWizard(models.TransientModel):
    _name = "dally.shop.order.transition.wizard"
    _description = "Motif de transition boutique"

    order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Commande",
        required=True,
        readonly=True,
    )
    target_state = fields.Selection(
        selection=[
            ("rejected", "Refuser la commande"),
            ("cancelled", "Annuler la commande"),
        ],
        string="Action",
        required=True,
        readonly=True,
    )
    reason = fields.Text(
        string="Motif communiqué au client",
        required=True,
    )

    def action_apply(self):
        self.ensure_one()
        self.order_id._dally_shop_transition(self.target_state, self.reason)
        return {"type": "ir.actions.act_window_close"}
