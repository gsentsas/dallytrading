# -*- coding: utf-8 -*-
"""Projections portail des commandes boutique, incluant la remise Lot C."""

from odoo import api, models

from .shop_order import MODES_REMISE
from .shop_order_workflow import SHOP_WORKFLOW_CLIENT_LABELS
from .shop_delivery import FULFILLMENT_CLIENT_LABELS

ETATS_CLIENT = {
    "draft": "Commande reçue — en attente de validation",
    "sent": "Commande reçue — en attente de validation",
    "sale": "Commande validée",
    "cancel": "Commande annulée",
}

ETAT_INCONNU = "Commande en cours de traitement"


class SaleOrderPortal(models.Model):
    _inherit = "sale.order"

    @api.model
    def _dally_shop_portal_domain(self):
        return [("dally_shop_order", "=", True)]

    def _dally_shop_portal_list(self):
        return [commande._dally_shop_portal_list_item() for commande in self]

    def _dally_shop_portal_list_item(self):
        self.ensure_one()
        mode, label = self._dally_shop_public_delivery_method()
        fee_status, fee_amount = self._dally_shop_public_fee()
        return {
            "reference": self.name,
            "date": self.date_order.isoformat() if self.date_order else None,
            "stateLabel": self._dally_shop_state_label(),
            "currency": self.currency_id.name,
            "amountUntaxed": self.amount_untaxed,
            "amountTax": self.amount_tax,
            "amountTotal": self.amount_total,
            "deliveryMode": mode,
            "deliveryModeLabel": label,
            "deliveryFeeStatus": fee_status,
            "deliveryFee": fee_amount,
            "grandTotal": self._dally_shop_delivery_grand_total()
            if self.dally_shop_delivery_method_id else self.amount_total,
            "fulfillmentState": self.dally_shop_fulfillment_state or "pending",
            "fulfillmentLabel": FULFILLMENT_CLIENT_LABELS.get(
                self.dally_shop_fulfillment_state or "pending", ""
            ),
            "itemCount": int(sum(self.order_line.mapped("product_uom_qty"))),
        }

    def _dally_shop_portal_detail(self):
        self.ensure_one()
        mode, label = self._dally_shop_public_delivery_method()
        fee_status, fee_amount = self._dally_shop_public_fee()
        return {
            "reference": self.name,
            "date": self.date_order.isoformat() if self.date_order else None,
            "state": self.dally_shop_workflow_state or "received",
            "stateLabel": self._dally_shop_state_label(),
            "deliveryMode": mode,
            "deliveryModeLabel": label,
            "currency": self.currency_id.name,
            "amountUntaxed": self.amount_untaxed,
            "amountTax": self.amount_tax,
            "amountTotal": self.amount_total,
            "deliveryFeeStatus": fee_status,
            "deliveryFee": fee_amount,
            "grandTotal": self._dally_shop_delivery_grand_total()
            if self.dally_shop_delivery_method_id else self.amount_total,
            "fulfillmentState": self.dally_shop_fulfillment_state or "pending",
            "fulfillmentLabel": FULFILLMENT_CLIENT_LABELS.get(
                self.dally_shop_fulfillment_state or "pending", ""
            ),
            "lines": [
                {
                    "productName": self._dally_shop_line_label(ligne),
                    "quantity": ligne.product_uom_qty,
                    "unitPrice": ligne.price_unit,
                    "subtotal": ligne.price_subtotal,
                }
                for ligne in self.order_line
            ],
            "deliveryAddress": self._dally_shop_portal_address(),
        }

    def _dally_shop_public_delivery_method(self):
        self.ensure_one()
        method = self.dally_shop_delivery_method_id
        if method:
            return method.code, method.name
        return (
            self.dally_shop_delivery_mode or None,
            dict(MODES_REMISE).get(self.dally_shop_delivery_mode, ""),
        )

    def _dally_shop_public_fee(self):
        self.ensure_one()
        if not self.dally_shop_delivery_method_id:
            return None, None
        state = self.dally_shop_delivery_fee_state or "pending_quote"
        amount = None if state == "pending_quote" else self.dally_shop_delivery_fee
        return state, amount

    @staticmethod
    def _dally_shop_line_label(ligne):
        return ligne.sudo().product_id.product_tmpl_id.display_name

    def _dally_shop_portal_address(self):
        self.ensure_one()
        method = self.dally_shop_delivery_method_id
        if method and not method.requires_address:
            return None
        if method and method.requires_address:
            country = None
            if self.dally_shop_shipping_country_code:
                country_record = self.env["res.country"].sudo().search(
                    [("code", "=", self.dally_shop_shipping_country_code)], limit=1
                )
                country = country_record.name or self.dally_shop_shipping_country_code
            return {
                "name": self.dally_shop_shipping_name or self.partner_id.name,
                "street": self.dally_shop_shipping_street or None,
                "city": self.dally_shop_shipping_city or None,
                "zip": self.dally_shop_shipping_zip or None,
                "country": country,
            }

        # Compatibilité pendant l'upgrade avant migration Lot C.
        partenaire = self.partner_id
        return {
            "name": partenaire.name,
            "street": partenaire.street or None,
            "city": partenaire.city or None,
            "zip": partenaire.zip or None,
            "country": partenaire.country_id.name or None,
        }

    def _dally_shop_state_label(self):
        self.ensure_one()
        if self.state and self.state not in ETATS_CLIENT:
            return ETAT_INCONNU

        workflow_state = self.dally_shop_workflow_state
        if workflow_state:
            label = SHOP_WORKFLOW_CLIENT_LABELS.get(workflow_state, ETAT_INCONNU)
            if workflow_state in {"rejected", "cancelled"}:
                reason = (self.dally_shop_customer_reason or "").strip()
                if reason:
                    return f"{label} — {reason}"
            return label

        return ETATS_CLIENT.get(self.state, ETAT_INCONNU)
