# -*- coding: utf-8 -*-
"""Projections portail des commandes boutique.

Le portail ne publie jamais ``sale.order.state`` comme vérité métier. E-commerce
Pro possède un état boutique distinct : une validation commerciale ne confirme
pas encore la vente native et ne déclenche donc ni picking, ni facture, ni autre
effet réservé aux lots suivants.

Le contrat JSON reste stable : le motif client d'un refus ou d'une annulation est
intégré au libellé d'état au lieu d'ajouter silencieusement une nouvelle clé que
le BFF strict pourrait refuser.
"""

from odoo import api, models

from .shop_order import MODES_REMISE
from .shop_order_workflow import SHOP_WORKFLOW_CLIENT_LABELS

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
        return [
            {
                "reference": commande.name,
                "date": commande.date_order.isoformat() if commande.date_order else None,
                "stateLabel": commande._dally_shop_state_label(),
                "currency": commande.currency_id.name,
                "amountUntaxed": commande.amount_untaxed,
                "amountTax": commande.amount_tax,
                "amountTotal": commande.amount_total,
                "deliveryMode": commande.dally_shop_delivery_mode,
                "deliveryModeLabel": dict(MODES_REMISE).get(
                    commande.dally_shop_delivery_mode, ""
                ),
                "itemCount": int(sum(commande.order_line.mapped("product_uom_qty"))),
            }
            for commande in self
        ]

    def _dally_shop_portal_detail(self):
        self.ensure_one()
        return {
            "reference": self.name,
            "date": self.date_order.isoformat() if self.date_order else None,
            # Clé conservée pour le contrat existant ; valeur désormais métier.
            "state": self.dally_shop_workflow_state or "received",
            "stateLabel": self._dally_shop_state_label(),
            "deliveryMode": self.dally_shop_delivery_mode,
            "deliveryModeLabel": dict(MODES_REMISE).get(
                self.dally_shop_delivery_mode, ""
            ),
            "currency": self.currency_id.name,
            "amountUntaxed": self.amount_untaxed,
            "amountTax": self.amount_tax,
            "amountTotal": self.amount_total,
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

    @staticmethod
    def _dally_shop_line_label(ligne):
        return ligne.sudo().product_id.product_tmpl_id.display_name

    def _dally_shop_portal_address(self):
        self.ensure_one()
        partenaire = self.partner_id
        return {
            "name": partenaire.name,
            "street": partenaire.street or None,
            "city": partenaire.city or None,
            "zip": partenaire.zip or None,
            "country": partenaire.country_id.name or None,
        }

    def _dally_shop_state_label(self):
        """Libellé client du workflow, sans jamais exposer une note interne."""
        self.ensure_one()

        # Si un module tiers introduit un état sale.order que nous ne connaissons
        # pas, on préfère un libellé générique plutôt que de prétendre comprendre
        # la situation native sous-jacente.
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
