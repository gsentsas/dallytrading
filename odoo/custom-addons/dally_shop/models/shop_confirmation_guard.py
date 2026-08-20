# -*- coding: utf-8 -*-
"""Verrou global sur la confirmation native des commandes boutique.

Le Lot C introduit volontairement UN passage vers ``sale.order.action_confirm`` :
l'autorisation explicite de préparation. Le simple fait de masquer le bouton Vente
ne suffit pas, car un autre menu, une automatisation ou un appel RPC pourrait
encore invoquer la méthode native.

Ce fichier ferme donc la frontière au niveau du modèle : toute confirmation native
d'une commande boutique est refusée, sauf l'appel interne effectué sous ``sudo``
par ``action_dally_shop_authorize_fulfillment``. Le contexte seul n'est pas une
autorisation : il doit être combiné à ``env.su`` afin qu'un utilisateur ne puisse
pas fabriquer le drapeau depuis un RPC.
"""

from odoo import _, fields, models
from odoo.exceptions import ValidationError


_CONFIRM_CONTEXT_KEY = "_dally_shop_fulfillment_authorization"


class SaleOrderShopConfirmationGuard(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        shop_orders = self.filtered("dally_shop_order")
        if shop_orders and not (
            self.env.su and self.env.context.get(_CONFIRM_CONTEXT_KEY) is True
        ):
            raise ValidationError(
                _(
                    "Une commande boutique ne peut être confirmée que par "
                    "l'autorisation explicite de préparation."
                )
            )
        return super().action_confirm()

    def action_dally_shop_authorize_fulfillment(self):
        """Autorise puis confirme la vente dans une transaction indivisible.

        Cette surcharge durcit l'implémentation du Lot C : le garde global ci-dessus
        rend désormais impossible un ``action_confirm()`` direct. L'action métier
        réutilise les préconditions, le journal et les notifications du module de
        fulfillment, mais signe explicitement son appel natif par le contexte
        interne + ``sudo``.
        """
        for order in self:
            order._dally_shop_fulfillment_preconditions()
            if order.dally_shop_fulfillment_authorized:
                continue
            if order.state not in ("draft", "sent"):
                raise ValidationError(
                    _("La vente Odoo a déjà été modifiée hors du workflow de préparation.")
                )

            with order.env.cr.savepoint():
                secured = order.sudo()
                secured.with_context(**{_CONFIRM_CONTEXT_KEY: True}).action_confirm()
                secured.write({
                    "dally_shop_fulfillment_authorized": True,
                    "dally_shop_fulfillment_authorized_at": fields.Datetime.now(),
                    "dally_shop_fulfillment_authorized_by_id": order.env.user.id,
                    "dally_shop_fulfillment_state": "preparing",
                })
                secured.with_env(order.env)._dally_shop_log_fulfillment(
                    "pending", "preparing"
                )
                secured.with_env(order.env)._dally_shop_queue_delivery_notification(
                    _("Commande en préparation"),
                    _(
                        "La commande %(reference)s est entrée en préparation.",
                        reference=order.name,
                    ),
                )
        return True
