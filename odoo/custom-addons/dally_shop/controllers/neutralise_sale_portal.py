# -*- coding: utf-8 -*-
"""
Fermeture du portail client natif de `sale` — pour les commandes boutique, et
seulement pour elles.

## Ce que l'audit a mesuré

`sale` est installé et expose un portail client complet. Sur la pile de
développement, connecté comme client portail :

* `/my/orders` et `/my/quotes` répondent 200. Ils étaient **vides** pour nos
  commandes, parce que leurs domaines natifs filtrent `state = 'sale'` et
  `state = 'sent'` : un brouillon n'y figure pas. Cette protection est
  accidentelle — elle disparaît dès qu'une commande boutique est confirmée ;
* `/my/orders/<id>` était **atteignable** pour sa propre commande, brouillon
  compris : 44 899 octets montrant référence, article et montants. Aucun canari
  n'y fuyait, et une commande d'un autre client était bien refusée ;
* `/my/orders/<id>/accept` **a confirmé la commande**. Mesuré : `draft` → `sale`,
  signature enregistrée, et **un transfert de stock créé**.

Ce dernier point est le motif de ce fichier. Le MVP interdit la confirmation
automatique et la création de transferts ; il ne servirait à rien de la refuser
côté Next.js si le client peut la déclencher lui-même par une route qu'Odoo ouvre
par défaut. Et un second portail où le client verrait les mêmes commandes, sous
une autre présentation et avec des boutons que nous n'avons pas décidés, est
exactement ce que ce cycle doit éviter.

## Portée volontairement étroite

La fermeture ne vise **que** les enregistrements portant `dally_shop_order`.
Les devis ordinaires, eux, doivent continuer de passer par ce portail : le
personnel envoie une offre par courriel, et le lien de cette offre est
précisément `/my/orders/<id>?access_token=…`. Fermer la route en bloc casserait
un usage commercial réel pour se protéger d'un risque qui ne concerne pas ces
enregistrements.

## Un seul point d'étranglement

Les six routes concernées — la fiche, `accept`, `decline`, `document`,
`download_edi`, `transaction` — passent toutes par `_document_check_access`.
Surcharger cette seule méthode les ferme ensemble.

Six surcharges séparées auraient le même effet aujourd'hui et divergeraient
demain : il suffirait qu'une montée de version ajoute une septième route, ou
qu'une seule des six oublie le contrôle. Ici, une route nouvelle qui suit la
convention d'Odoo est fermée sans que nous ayons à y penser.

Le refus prend la forme d'un `MissingError`, celle qu'Odoo produit déjà pour un
enregistrement inexistant. Les appelants natifs la traitent tous — redirection
vers `/my` pour les pages, `{'error': 'Invalid order.'}` pour `accept`. Une
commande boutique devient donc, vue du portail natif, indiscernable d'une
commande qui n'existe pas.
"""

import logging

from odoo import _
from odoo.exceptions import MissingError
from odoo.http import request

from odoo.addons.sale.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


class DallyNeutralisedSalePortal(CustomerPortal):
    """Retire les commandes boutique du portail natif, sans toucher au reste."""

    def _document_check_access(self, model_name, document_id, access_token=None):
        """Refuse l'accès natif à une commande boutique.

        L'ordre compte : on délègue **d'abord** au contrôle natif, et on n'examine
        l'enregistrement qu'ensuite. Inverser reviendrait à lire la commande de
        quelqu'un d'autre pour décider si on a le droit de la lire — et à
        transformer ce refus en oracle d'existence, puisque la réponse
        différerait selon que l'identifiant désigne une commande boutique ou une
        commande inexistante.

        Avec cet ordre, un identifiant appartenant à un autre client produit le
        refus natif, et un identifiant de commande boutique produit un refus
        identique à celui d'une commande absente.
        """
        document_sudo = super()._document_check_access(
            model_name, document_id, access_token=access_token
        )
        if model_name != "sale.order":
            return document_sudo
        if not document_sudo.dally_shop_order:
            return document_sudo

        # Journalisé en information et non en avertissement : ce n'est pas
        # forcément une attaque. Un client qui a reçu un ancien lien, ou qui a
        # gardé un onglet ouvert, arrive ici légitimement.
        _logger.info(
            "Portail natif : acces refuse a la commande boutique %s (uid=%s)",
            document_sudo.id, request.env.uid,
        )
        raise MissingError(_("This document does not exist."))

    def _prepare_quotations_domain(self, partner):
        """Écarte les commandes boutique de la liste des devis."""
        return super()._prepare_quotations_domain(partner) + [
            ("dally_shop_order", "=", False)
        ]

    def _prepare_orders_domain(self, partner):
        """Écarte les commandes boutique de la liste des commandes.

        Le domaine natif filtre déjà `state = 'sale'`, ce qui suffit tant que rien
        ne confirme une commande boutique. On ne s'en contente pas : cette
        protection est un effet de bord d'un filtre écrit pour autre chose, et
        elle tomberait au premier flux qui confirme — c'est-à-dire au moment où
        deux portails se mettraient à montrer les mêmes commandes.
        """
        return super()._prepare_orders_domain(partner) + [
            ("dally_shop_order", "=", False)
        ]
