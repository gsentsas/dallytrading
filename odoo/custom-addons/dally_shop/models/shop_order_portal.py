# -*- coding: utf-8 -*-
"""
Projections portail des commandes boutique.

## Ce que le client lit, et l'état qu'on lui montre

Une commande boutique reste en `draft` : rien ne la confirme automatiquement au
MVP. Mais « Brouillon » est un mot d'outil de gestion, pas une information pour
un client — il suggère quelque chose d'inachevé de son côté, alors que ce qui
reste à faire est de notre côté.

D'où un libellé explicite, `Commande reçue — en attente de validation`, et une
table de correspondance plutôt qu'un `if`. La table dit aussi ce qu'on ne dira
pas : aucun état ne se traduit par « payée » ou « expédiée », parce qu'aucun
paiement n'existe et qu'aucune expédition n'est déclenchée.

## Aucun modèle parallèle

`sale.order` reste la seule source. Ces méthodes sont des projections : elles
lisent et n'écrivent rien.

## L'autorisation ne vit pas ici

Ces méthodes supposent que l'appelant a le droit de lire les enregistrements
qu'il leur passe. C'est vrai parce qu'elles sont appelées sur un recordset obtenu
**sans** `sudo()`, donc filtré par la record rule native
`Portal Personal Quotations/Sales Orders` — `partner_id child_of
user.commercial_partner_id.id`. Le cloisonnement est celui d'Odoo, pas un domaine
que nous aurions ajouté du mauvais côté de la frontière.
"""

from odoo import api, models

from .shop_order import MODES_REMISE

#: Ce que chaque état de `sale.order` raconte à un client de la boutique.
#:
#: Les libellés ne promettent que ce qui est vrai. `draft` ne dit pas « en
#: préparation » — rien n'est préparé ; il dit que nous avons la commande et que
#: la balle est dans notre camp. `sale` ne dit pas « payée » : la confirmation
#: d'une commande et son règlement sont deux choses, et le MVP n'en gère qu'une.
#:
#: Une table plutôt qu'une suite de conditions, pour que l'ensemble des messages
#: possibles se lise d'un coup d'œil — c'est la seule façon de vérifier qu'aucun
#: n'affirme quelque chose de faux.
ETATS_CLIENT = {
    "draft": "Commande reçue — en attente de validation",
    "sent": "Commande reçue — en attente de validation",
    "sale": "Commande validée",
    "cancel": "Commande annulée",
}

#: Libellé de repli.
#:
#: Un état inconnu ne doit pas produire une étiquette vide, qui laisserait le
#: client devant un blanc. Il ne doit pas non plus être deviné : « en cours de
#: traitement » est vrai de n'importe quel état, et n'affirme rien de faux.
ETAT_INCONNU = "Commande en cours de traitement"


class SaleOrderPortal(models.Model):
    _inherit = "sale.order"

    @api.model
    def _dally_shop_portal_domain(self):
        """Le domaine des commandes boutique.

        Volontairement réduit à ce seul critère : le cloisonnement par client est
        appliqué par la record rule d'Odoo, et l'ajouter ici en ferait une
        décision de sécurité prise à deux endroits — donc une à oublier.
        """
        return [("dally_shop_order", "=", True)]

    def _dally_shop_portal_list(self):
        """Projection de liste. Liste blanche stricte.

        Ni coût, ni marge, ni fournisseur, ni note interne, ni identifiant
        technique. Ces champs ne sont pas « filtrés » : ils n'ont pas de place où
        atterrir, et un champ ajouté demain par un module tiers n'apparaîtra pas
        tout seul.
        """
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
                # Le nombre d'articles, pas le nombre de lignes : c'est ce que le
                # client a mis au panier, et c'est ce qu'il reconnaîtra.
                "itemCount": int(sum(commande.order_line.mapped("product_uom_qty"))),
            }
            for commande in self
        ]

    def _dally_shop_portal_detail(self):
        """Projection de détail.

        Pas de `paymentStatusLabel` : aucun paiement en ligne n'existe, et un
        champ nommé ainsi serait lu comme la promesse qu'il en existe un. Le
        message de la page dit ce qu'il faut — nous recontactons le client — sans
        emprunter le vocabulaire d'un règlement.
        """
        self.ensure_one()
        return {
            "reference": self.name,
            "date": self.date_order.isoformat() if self.date_order else None,
            "state": self.state,
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
        """Le nom de l'article d'une ligne, lu sous `sudo()`.

        ## Pourquoi un `sudo()` ici, alors qu'il n'y en a nulle part ailleurs

        Mesuré, et non supposé : un utilisateur portail n'a **aucun droit de
        lecture sur `product.product`**. Lire `ligne.product_id` sous son identité
        lève `AccessError` — c'est-à-dire une 500 sur la page de détail de sa
        propre commande. Le test
        `test_la_projection_marche_sous_lutilisateur_du_client` a produit
        exactement cette trace, et c'est la raison de son existence.

        ## Pourquoi il est sûr

        L'ordre est celui qu'impose la règle du dépôt : **l'autorisation d'abord,
        le `sudo()` ensuite, et sur le seul enregistrement déjà autorisé.**

        Quand cette méthode est appelée, la commande est déjà dans un recordset
        obtenu sans `sudo()` — donc la record rule native
        `partner_id child_of user.commercial_partner_id.id` l'a laissée passer.
        Le client a le droit de voir cette commande ; il a donc le droit de savoir
        ce qu'il a commandé.

        ## Sa portée

        Un seul champ, `display_name`, sur un produit désigné par une ligne de sa
        propre commande. Ni le coût, ni la marge, ni le fournisseur : ils ne sont
        pas lus, donc il n'y a rien à filtrer ensuite.

        Le nom vient de la ligne et non d'une recherche : c'est le produit retenu
        au moment de la commande, et il reste juste même si le catalogue change.
        """
        return ligne.sudo().product_id.product_tmpl_id.display_name

    def _dally_shop_portal_address(self):
        """L'adresse du client, telle qu'il l'a lui-même fournie.

        Utile pour qu'il vérifie ce que nous avons enregistré. Elle ne contient
        rien qu'il ne connaisse déjà : ce sont ses propres coordonnées, et aucun
        identifiant ne l'accompagne.
        """
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
        """Le libellé client de l'état, jamais le mot d'Odoo."""
        self.ensure_one()
        return ETATS_CLIENT.get(self.state, ETAT_INCONNU)
