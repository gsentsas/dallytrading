# -*- coding: utf-8 -*-
"""GET /api/v1/references/<kind> — les référentiels dont le formulaire a besoin.

## Une route plutôt que quatre

Pays, subdivisions, lieux et incoterms posent la même question — « donne-moi la
liste » — avec la même authentification, le même scope, le même cache et la
même règle de projection. Quatre routes auraient quadruplé les endroits où
vérifier tout cela. Ajouter un référentiel se réduit ici à une ligne dans
`REFERENTIELS`, et la revue de sécurité reste au même endroit.

## Le scope réutilisé

`services:read` couvre déjà le catalogue public des services. Ces listes sont
de la même nature : publiques, identiques pour tout le monde, sans un seul
élément commercial. Créer un scope pour elles obligerait à reconfigurer les
clés existantes sans rien protéger de plus.

## Le cache

Cinq minutes, comme le catalogue des services. Un port n'ouvre pas deux fois
par jour, et le BFF n'a aucune raison de réinterroger Odoo à chaque visiteur
qui ouvre le formulaire.
"""

import logging

from odoo import http
from odoo.http import request

from odoo.addons.dally_api.controllers.main import (
    DallyApiController,
    DallyApiError,
)

_logger = logging.getLogger(__name__)


class DallyReferencesController(DallyApiController):

    #: Référentiel public → modèle, méthode de projection, et s'il prend un
    #: argument.
    #:
    #: Le nom de la méthode est écrit ici en toutes lettres : le `kind` de
    #: l'URL ne sert jamais à composer un nom d'attribut, sans quoi une URL
    #: bien choisie appellerait n'importe quelle méthode du modèle.
    #:
    #: L'argument s'appelle `q` quel que soit le référentiel — code pays pour
    #: les subdivisions, mode pour les lieux. Un nom unique évite que
    #: l'appelant ait à connaître une table de correspondance de plus ; ce que
    #: l'argument signifie est l'affaire de la projection.
    REFERENTIELS = {
        "countries": ("res.country", "_dally_public_countries", False),
        "states": ("res.country.state", "_dally_public_states", True),
        "locations": ("freight.port", "_dally_public_locations", True),
        "incoterms": ("account.incoterms", "_dally_public_incoterms", False),
    }

    @http.route(
        "/api/v1/references/<string:kind>",
        type="http",
        auth="none",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def list_references(self, kind, **kwargs):
        try:
            api_key, env = self._authenticate("services:read")
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        entree = self.REFERENTIELS.get(kind)
        if not entree:
            return self._error(
                404, "not_found",
                "Unknown reference '%s'." % kind[:40],
            )

        modele, methode, prend_argument = entree

        # Le paramètre est passé positionnellement à une méthode nommée par la
        # table ci-dessus : rien de ce que fournit l'appelant ne devient un nom.
        projection = getattr(env[modele], methode)
        if prend_argument:
            donnees = projection((kwargs.get("q") or "").strip()[:40])
        else:
            donnees = projection()

        api_key._register_use()

        return self._json_response(
            {"success": True, "data": {kind: donnees}},
            status=200,
            cache_control="public, max-age=300",
        )
