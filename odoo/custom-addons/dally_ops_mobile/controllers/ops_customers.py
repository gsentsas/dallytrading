# -*- coding: utf-8 -*-
"""POST /api/v1/ops/customers/search — retrouver un client, sans le feuilleter.

## Pourquoi POST et non GET

Un numéro de téléphone est une donnée personnelle. Placé dans une URL, il se
retrouve dans l'historique du navigateur, dans les journaux d'accès du proxy,
dans les en-têtes `Referer` et dans tout outil de mesure d'audience — des
endroits qui ne sont ni chiffrés au repos, ni purgés, ni soumis à la même
discipline que la base. Un corps de requête ne va nulle part de tout cela.

Ce n'est pas une route « qui écrit » : c'est une lecture dont l'argument ne
doit pas voyager en clair.

## Ce que ce contrôleur fait

Il authentifie, valide la forme, appelle le service, sérialise. Aucun `sudo`,
aucun domaine, aucune connaissance de `res.partner`.
"""

import json

from odoo import _, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_customer_service import DallyOpsConflit

from .ops_base import DallyOpsController


class DallyOpsCustomersController(DallyOpsController):

    @http.route(
        "/api/v1/ops/customers/search",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_customers_search(self, **kwargs):
        """Zéro, un, ou « plusieurs » — jamais le premier de deux.

        La route n'est pas `readonly` : trouver un client pose au passage sa
        référence Ops, et poser une référence est une écriture. C'est la seule
        de cette étape ; `res.partner` n'est jamais modifié.
        """
        if not self._a_un_role_ops():
            return self._refus_ops("ops/customers/search")

        try:
            corps = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return self._requete_invalide(_("Corps de requête illisible."))

        try:
            resultat = request.env["dally.ops.customer.service"].search_unique(corps)
        except UserError as erreur:
            # Le message d'un `UserError` de ce service décrit la *forme* de la
            # demande — jamais son contenu, ni ce que la base contient.
            return self._requete_invalide(str(erreur))
        except AccessError:
            return self._refus_ops("ops/customers/search")

        return self._json({"success": True, "data": resultat})

    @http.route(
        "/api/v1/ops/customers",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_customers_create(self, **kwargs):
        """Crée un client, ou retrouve celui qui existait déjà.

        « Existe déjà » n'est pas une erreur : c'est une issue normale, et
        souvent la bonne. Le logisticien a devant lui un client qui attend ; lui
        renvoyer un refus l'obligerait à recommencer une recherche qu'il vient
        de faire. La réponse porte donc `status: existing` avec la fiche
        retrouvée, et l'application enchaîne.

        Ce qui est refusé, en revanche, c'est l'ambiguïté : deux fiches, ou un
        téléphone et une adresse qui désignent des personnes différentes. Là,
        aucune identité ne sort — c'est un `409` et une phrase.
        """
        if not self._a_un_role_ops():
            return self._refus_ops("ops/customers")

        try:
            corps = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return self._requete_invalide(_("Corps de requête illisible."))

        try:
            resultat = request.env["dally.ops.customer.service"].create_customer(corps)
        except DallyOpsConflit as erreur:
            return self._conflit(erreur.code, str(erreur))
        except UserError as erreur:
            return self._requete_invalide(str(erreur))
        except AccessError:
            return self._refus_ops("ops/customers")

        return self._json({"success": True, "data": resultat})

    @classmethod
    def _conflit(cls, code, message):
        """409 : la demande est bien formée, mais la base dit autre chose."""
        return cls._json(
            {"success": False, "error": {"code": code, "message": message}},
            status=409,
        )

    @classmethod
    def _requete_invalide(cls, message):
        return cls._json(
            {"success": False, "error": {"code": "invalid_request", "message": message}},
            status=400,
        )
