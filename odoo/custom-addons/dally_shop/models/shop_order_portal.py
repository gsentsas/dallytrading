# -*- coding: utf-8 -*-
"""Projections portail des commandes boutique.

Le portail ne publie jamais ``sale.order.state`` comme vérité métier. E-commerce
Pro possède désormais un état boutique distinct : une validation commerciale ne
confirme pas encore la vente native et ne déclenche donc ni picking, ni facture,
ni autre effet réservé aux lots suivants.

Les projections restent des listes blanches explicites. Le motif publié est le
champ client-safe du workflow ; les notes internes, coûts, marges et identités du
personnel n'ont aucun chemin vers le portail.
"""

from odoo import api, models

from .shop_order import MODES_REMISE
from .shop_order_workflow import SHOP_WORKFLOW_CLIENT_LABELS

# Compatibilité de repli pour une ancienne commande qui n'aurait pas encore été
# initialisée par la migration du Lot B. Cette table couvre toujours les états
# natifs actuels, mais elle n'est plus la source principale du statut client.
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
            # La clé historique `state` est conservée pour le contrat BFF, mais sa
            # valeur devient l'état métier client-safe, jamais `sale.order.state`.
            "state": self.dally_shop_workflow_state or "received",
            "stateLabel": self._dally_shop_state_label(),
            "stateReason": self._dally_shop_customer_reason(),
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
        """Nom du produit autorisé après autorisation de la commande.

        Le portail n'a pas d'ACL produit. Le ``sudo()`` est donc limité au seul
        ``display_name`` du produit déjà désigné par une ligne d'une commande que
        la record rule native Sale a autorisée pour le client.
        """
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

    def _dally_shop_customer_reason(self):
        self.ensure_one()
        if self.dally_shop_workflow_state not in {"rejected", "cancelled"}:
            return None
        return self.dally_shop_customer_reason or None

    def _dally_shop_state_label(self):
        """Libellé client du workflow, avec repli pour les anciennes données."""
        self.ensure_one()
        if self.dally_shop_workflow_state:
            return SHOP_WORKFLOW_CLIENT_LABELS.get(
                self.dally_shop_workflow_state, ETAT_INCONNU
            )
        return ETATS_CLIENT.get(self.state, ETAT_INCONNU)
