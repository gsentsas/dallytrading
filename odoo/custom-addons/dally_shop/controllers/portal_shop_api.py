# -*- coding: utf-8 -*-
"""
`GET /api/v1/portal/shop/orders` — les commandes boutique du client connecté.
`GET /api/v1/portal/shop/orders/<reference>` — le détail de l'une d'elles.

## L'autorisation d'abord, et aucun `sudo()`

Les deux routes lisent avec `request.env`, sans `sudo()`. Ce n'est pas une
économie : c'est le seul dispositif qui fasse appliquer le cloisonnement par
Odoo plutôt que par nous.

L'audit a confirmé que tout est déjà en place côté natif :

* ACL `sale.order.portal` — le groupe portail a **read seul**, mesuré : `write`,
  `create` et `unlink` lèvent `AccessError` ;
* record rule `Portal Personal Quotations/Sales Orders` —
  `partner_id child_of user.commercial_partner_id.id`, c'est-à-dire exactement la
  règle demandée.

Aucune ACL ni règle n'est donc ajoutée. Un domaine `partner_id` écrit ici
n'ajouterait aucune sécurité et en déplacerait la responsabilité du mauvais côté
de la frontière — là où une erreur ne se voit pas.

## La référence ne suffit jamais à autoriser

`S00042` est la référence commerciale d'Odoo : lisible, séquentielle, imprimée sur
les documents. La connaître ne donne rien, parce que la recherche s'exécute sous
l'utilisateur du client : la commande d'un autre est simplement absente du
recordset, et la route répond 404.

Le navigateur ne fournit jamais `partner_id`, `commercial_partner_id`, ni un
identifiant technique de commande. Il n'y a rien à valider, parce qu'il n'y a
rien de reçu.

## Une commande invité n'apparaît jamais ici

Un contact invité n'a pas de compte : il n'est le `commercial_partner_id` de
personne, donc la record rule ne le fait apparaître dans aucun portail. Le
rattachement d'une commande invité à un compte demandera un processus explicite,
qui n'existe pas et que ce cycle ne construit pas — mais il est utile de noter
que l'absence n'est pas un oubli : elle tombe de la même règle que le reste.
"""

import logging

from odoo import http
from odoo.http import request

from odoo.addons.dally_portal.controllers.portal_api import DallyPortalController

_logger = logging.getLogger(__name__)

#: Commandes rendues par page.
#:
#: Bornée comme le catalogue : une route authentifiée est moins exposée qu'une
#: route publique, mais `?limit=100000` y coûterait tout autant.
LIMITE_MAX = 50


class DallyShopPortalController(DallyPortalController):

    @http.route(
        "/api/v1/portal/shop/orders",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
        readonly=True,
    )
    def shop_orders(self, **kwargs):
        client = self._portal_user_or_none()
        if not client:
            return self._error(403, "forbidden", "Accès refusé.")

        Commande = request.env["sale.order"]
        limite = self._borner(kwargs.get("limit"))
        # Sans `sudo()` : la record rule native fait le cloisonnement. Le tri par
        # date décroissante puis par identifiant garantit un ordre stable — sans
        # le second critère, deux commandes de la même seconde s'échangeraient de
        # place au gré du plan d'exécution, et une pagination deviendrait
        # incohérente.
        commandes = Commande.search(
            Commande._dally_shop_portal_domain(),
            order="date_order desc, id desc",
            limit=limite,
        )

        return self._json({
            "success": True,
            "data": {"orders": commandes._dally_shop_portal_list()},
        })

    @http.route(
        "/api/v1/portal/shop/orders/<string:reference>",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
        readonly=True,
    )
    def shop_order_detail(self, reference, **kwargs):
        client = self._portal_user_or_none()
        if not client:
            return self._error(403, "forbidden", "Accès refusé.")

        Commande = request.env["sale.order"]
        # La référence vient du réseau : ce n'est pas forcément une chaîne, et un
        # entier produirait une comparaison SQL sur un champ texte — donc une 500
        # au lieu d'un 404.
        if not isinstance(reference, str) or not reference:
            return self._not_found()

        commande = Commande.search(
            Commande._dally_shop_portal_domain() + [("name", "=", reference)],
            limit=1,
        )
        if not commande:
            # Une commande d'un autre client, une commande invité, une commande
            # non-boutique et une référence inventée arrivent toutes ici. Elles
            # produisent la même réponse : la distinction n'existe nulle part.
            return self._not_found()

        return self._json({
            "success": True,
            "data": {"order": commande._dally_shop_portal_detail()},
        })

    @staticmethod
    def _borner(brut):
        """Une limite entière dans [1, LIMITE_MAX], sans jamais lever.

        `?limit=abc` doit donner le comportement par défaut, pas une trace 500.
        """
        try:
            valeur = int(brut)
        except (TypeError, ValueError):
            return LIMITE_MAX
        return max(1, min(valeur, LIMITE_MAX))
