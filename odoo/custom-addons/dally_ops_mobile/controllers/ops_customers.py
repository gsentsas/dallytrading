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

    @classmethod
    def _requete_invalide(cls, message):
        return cls._json(
            {"success": False, "error": {"code": "invalid_request", "message": message}},
            status=400,
        )
