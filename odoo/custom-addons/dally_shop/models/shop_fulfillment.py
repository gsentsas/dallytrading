# -*- coding: utf-8 -*-
"""Autorisation de préparation et suivi de remise du Lot C.

Une validation commerciale Lot B ne confirme toujours pas la vente Odoo. La
confirmation native devient possible uniquement via
``action_dally_shop_authorize_fulfillment`` et seulement si :

* la commande boutique est commercialement ``validated`` ;
* la méthode de remise est connue ;
* les frais ne sont plus ``pending_quote`` ;
* l'adresse nécessaire a été figée.

Cette action est explicite, gardée par le rôle Boutique, idempotente et journalise
le passage à la préparation. Le Lot D pourra plus tard automatiser cette
autorisation après paiement ; le Lot C ne prétend pas qu'un paiement existe.
"""

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class SaleOrderShopFulfillment(models.Model):
    _inherit = "sale.order"

    dally_shop_fulfillment_event_ids = fields.One2many(
        comodel_name="dally.shop.fulfillment.event",
        inverse_name="order_id",
        string="Historique de remise",
        readonly=True,
    )

    def _dally_shop_transition(self, target_state, reason=None):
        """Empêche un état métier annulé avec une vente déjà engagée.

        Le Lot B autorisait ``validated -> cancelled`` parce qu'aucune vente
        native n'était encore confirmée. Dès que la préparation est autorisée,
        une annulation doit aussi traiter picking/stock. Ce flux n'existe pas dans
        le Lot C ; on ferme donc explicitement la transition au lieu de produire
        deux vérités contradictoires.
        """
        for order in self:
            if target_state == "cancelled" and order.dally_shop_fulfillment_authorized:
                raise ValidationError(
                    _(
                        "Cette commande est déjà engagée en préparation. "
                        "L'annulation logistique doit être traitée avant de l'annuler."
                    )
                )
        return super()._dally_shop_transition(target_state, reason)

    def action_dally_shop_open_delivery_fee(self):
        self.ensure_one()
        self._dally_shop_require_workflow_operator()
        if self.dally_shop_workflow_state not in ("received", "validated"):
            raise ValidationError(_("Les frais ne peuvent plus être confirmés pour cette commande."))
        if not self.dally_shop_delivery_method_id:
            raise ValidationError(_("Aucune méthode de remise n'est associée à cette commande."))
        if self.dally_shop_delivery_fee_state != "pending_quote":
            raise ValidationError(_("Les frais de remise sont déjà déterminés."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Confirmer les frais de remise"),
            "res_model": "dally.shop.delivery.fee.wizard",
            "view_mode": "form",
            "view_id": self.env.ref("dally_shop.view_dally_shop_delivery_fee_wizard").id,
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    def _dally_shop_set_delivery_fee(self, amount):
        self.ensure_one()
        self._dally_shop_require_workflow_operator()
        if self.dally_shop_workflow_state not in ("received", "validated"):
            raise ValidationError(_("Les frais ne peuvent plus être confirmés pour cette commande."))
        if not self.dally_shop_delivery_method_id:
            raise ValidationError(_("Aucune méthode de remise n'est associée à cette commande."))
        if self.dally_shop_delivery_method_id.fee_policy != "quote":
            raise ValidationError(_("Cette méthode de remise n'attend pas de cotation de frais."))
        if self.dally_shop_delivery_fee_state == "quoted":
            if float_compare(
                self.dally_shop_delivery_fee,
                amount,
                precision_rounding=self.currency_id.rounding,
            ) == 0:
                return True
            raise ValidationError(_("Les frais de remise ont déjà été confirmés."))
        if self.dally_shop_delivery_fee_state != "pending_quote":
            raise ValidationError(_("L'état des frais de remise ne permet pas cette action."))
        if amount < 0:
            raise ValidationError(_("Les frais de remise ne peuvent pas être négatifs."))

        self.sudo().write({
            "dally_shop_delivery_fee_state": "quoted",
            "dally_shop_delivery_fee": amount,
        })
        self._dally_shop_queue_delivery_notification(
            _("Frais de remise confirmés"),
            _(
                "Les frais de remise de la commande %(reference)s sont confirmés à %(amount)s %(currency)s.",
                reference=self.name,
                amount=amount,
                currency=self.currency_id.name,
            ),
        )
        return True

    def _dally_shop_fulfillment_preconditions(self):
        self.ensure_one()
        self._dally_shop_require_workflow_operator()
        if self.dally_shop_workflow_state != "validated":
            raise ValidationError(_("La commande doit d'abord être validée commercialement."))
        if not self.dally_shop_delivery_method_id:
            raise ValidationError(_("Aucune méthode de remise n'est associée à cette commande."))
        if self.dally_shop_delivery_fee_state == "pending_quote":
            raise ValidationError(_("Les frais de remise doivent d'abord être confirmés."))
        if self.dally_shop_delivery_method_id.requires_address:
            if not (self.dally_shop_shipping_name and self.dally_shop_shipping_street and self.dally_shop_shipping_city):
                raise ValidationError(_("L'adresse de livraison est incomplète."))

    def action_dally_shop_authorize_fulfillment(self):
        """Seul point Lot C autorisé à appeler ``sale.order.action_confirm()``."""
        for order in self:
            order._dally_shop_fulfillment_preconditions()
            if order.dally_shop_fulfillment_authorized:
                continue
            if order.state not in ("draft", "sent"):
                raise ValidationError(
                    _("La vente Odoo a déjà été modifiée hors du workflow de préparation.")
                )

            # Le savepoint englobe confirmation native + drapeau + journal. Une
            # erreur de stock ne peut donc pas laisser une demi-autorisation.
            with order.env.cr.savepoint():
                secured = order.sudo()
                secured.action_confirm()
                secured.write({
                    "dally_shop_fulfillment_authorized": True,
                    "dally_shop_fulfillment_authorized_at": fields.Datetime.now(),
                    "dally_shop_fulfillment_authorized_by_id": order.env.user.id,
                    "dally_shop_fulfillment_state": "preparing",
                })
                secured.with_env(order.env)._dally_shop_log_fulfillment("pending", "preparing")
                secured.with_env(order.env)._dally_shop_queue_delivery_notification(
                    _("Commande en préparation"),
                    _("La commande %(reference)s est entrée en préparation.", reference=order.name),
                )
        return True

    def action_dally_shop_mark_ready(self):
        for order in self:
            order._dally_shop_set_fulfillment_state("ready")
        return True

    def action_dally_shop_dispatch(self):
        for order in self:
            if not order.dally_shop_delivery_method_id or order.dally_shop_delivery_method_id.kind != "delivery":
                raise ValidationError(_("Seule une livraison peut être mise en cours de livraison."))
            order._dally_shop_set_fulfillment_state("out_for_delivery")
        return True

    def action_dally_shop_complete_fulfillment(self):
        for order in self:
            method = order.dally_shop_delivery_method_id
            if not method:
                raise ValidationError(_("Aucune méthode de remise n'est associée à cette commande."))
            target = "picked_up" if method.kind == "pickup" else "delivered"
            order._dally_shop_set_fulfillment_state(target)
        return True

    def _dally_shop_set_fulfillment_state(self, target):
        self.ensure_one()
        self._dally_shop_require_workflow_operator()
        if not self.dally_shop_fulfillment_authorized:
            raise ValidationError(_("La préparation n'a pas été autorisée."))

        method = self.dally_shop_delivery_method_id
        current = self.dally_shop_fulfillment_state or "pending"
        allowed = {
            "pickup": {
                "preparing": {"ready"},
                "ready": {"picked_up"},
                "picked_up": set(),
            },
            "delivery": {
                "preparing": {"ready"},
                "ready": {"out_for_delivery"},
                "out_for_delivery": {"delivered"},
                "delivered": set(),
            },
        }
        if target == current:
            return True
        if not method or target not in allowed.get(method.kind, {}).get(current, set()):
            raise ValidationError(
                _(
                    "Transition de remise interdite : %(source)s → %(target)s.",
                    source=current,
                    target=target,
                )
            )

        self.sudo().write({"dally_shop_fulfillment_state": target})
        self._dally_shop_log_fulfillment(current, target)
        self._dally_shop_queue_delivery_notification(
            _("Mise à jour de votre commande"),
            _(
                "La remise de la commande %(reference)s est maintenant : %(state)s.",
                reference=self.name,
                state=dict(self._fields["dally_shop_fulfillment_state"].selection).get(target, target),
            ),
        )
        return True

    def _dally_shop_log_fulfillment(self, from_state, to_state):
        self.ensure_one()
        return self.env["dally.shop.fulfillment.event"].sudo().create({
            "order_id": self.id,
            "from_state": from_state or False,
            "to_state": to_state,
            "changed_by_id": self.env.user.id,
        })

    def _dally_shop_queue_delivery_notification(self, subject, text):
        self.ensure_one()
        recipient = (self.partner_id.email or "").strip()
        if not recipient:
            return False
        sender = (
            (self.company_id.email or "").strip()
            or (self.env.user.email or "").strip()
            or "noreply@dallytrading.com"
        )
        self.env["mail.mail"].sudo().create({
            "subject": subject,
            "body_html": "<p>%s</p><p>DallyTrading</p>" % escape(text),
            "email_from": sender,
            "email_to": recipient,
            "auto_delete": True,
        })
        return True


class DallyShopFulfillmentEvent(models.Model):
    _name = "dally.shop.fulfillment.event"
    _description = "Événement de remise boutique"
    _order = "changed_at desc, id desc"

    order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Commande",
        required=True,
        index=True,
        ondelete="cascade",
    )
    from_state = fields.Selection(
        selection=lambda self: self.env["sale.order"]._fields["dally_shop_fulfillment_state"].selection,
        string="État précédent",
        readonly=True,
    )
    to_state = fields.Selection(
        selection=lambda self: self.env["sale.order"]._fields["dally_shop_fulfillment_state"].selection,
        string="Nouvel état",
        required=True,
        readonly=True,
    )
    changed_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    changed_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Par",
        required=True,
        readonly=True,
        ondelete="restrict",
    )


class DallyShopDeliveryFeeWizard(models.TransientModel):
    _name = "dally.shop.delivery.fee.wizard"
    _description = "Confirmation des frais de remise"

    order_id = fields.Many2one("sale.order", string="Commande", required=True, readonly=True)
    currency_id = fields.Many2one(related="order_id.currency_id", readonly=True)
    amount = fields.Monetary(
        string="Frais de remise",
        currency_field="currency_id",
        required=True,
    )

    @api.constrains("amount")
    def _check_amount(self):
        for wizard in self:
            if wizard.amount < 0:
                raise ValidationError(_("Les frais de remise ne peuvent pas être négatifs."))

    def action_apply(self):
        self.ensure_one()
        self.order_id._dally_shop_set_delivery_fee(self.amount)
        return {"type": "ir.actions.act_window_close"}
