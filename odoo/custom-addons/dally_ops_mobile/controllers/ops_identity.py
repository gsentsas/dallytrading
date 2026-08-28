# -*- coding: utf-8 -*-
"""GET /api/v1/ops/me — qui est connecté, et ce qu'il a le droit de faire.

## Pourquoi cette route n'a pas de clé d'API

Les points d'entrée Freight s'authentifient par clé et par portée : ils
servent le connecteur tableur, un automate de confiance qui écrit en masse.
L'application terrain, elle, doit dire **qui** saisit — et une clé ne le dit
pas. Elle s'appuie donc sur une session utilisateur ordinaire, `auth="user"`,
et l'identité vient d'Odoo.

C'est aussi ce qui permet de tenir la règle « aucun secret dans le
navigateur » : il n'y a pas de secret à cacher, seulement une session.

## Sur un compte non interne

Mesuré : un utilisateur portant le seul groupe Ops, sans `base.group_user`,
lit **zéro** modèle — contre 186 pour un compte interne et 41 pour un compte
portail. Il satisfait pourtant `auth="user"`, car la source d'Odoo ne rejette
que l'utilisateur inexistant ou public (`ir_http._auth_method_user`), et il
lit ses propres champs grâce au mécanisme d'auto-lecture de `res.users`.

Cette route n'a donc besoin d'aucun `sudo`.

## Ce qu'elle ne renvoie pas

Ni groupes Odoo, ni identifiant de session, ni portées d'API. Le frontend
demande « puis-je créer une réception », pas « suis-je dans tel groupe » :
sans cette indirection, ajouter un droit obligerait à rouvrir chaque écran.
"""

import json
import logging

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DallyOpsIdentityController(http.Controller):

    @staticmethod
    def _json(charge, status=200):
        """Réponse JSON, jamais mise en cache.

        `private, no-store` : l'identité et les droits d'un opérateur ne
        doivent pas séjourner dans un intermédiaire, qui les servirait au
        suivant. C'est la même règle que le portail applique déjà.
        """
        return request.make_response(
            json.dumps(charge),
            headers=[
                ("Content-Type", "application/json; charset=utf-8"),
                ("Cache-Control", "private, no-store, max-age=0"),
                ("X-Content-Type-Options", "nosniff"),
                ("Referrer-Policy", "no-referrer"),
            ],
            status=status,
        )

    @http.route(
        "/api/v1/ops/me",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_me(self, **kwargs):
        """L'identité de l'opérateur connecté.

        Un utilisateur authentifié mais sans rôle Ops reçoit un 403, et non un
        401 : il est bien identifié, c'est l'autorisation qui manque. Le
        message ne dit pas quel groupe lui manquerait — un refus n'a pas à
        renseigner sur la structure des droits.
        """
        if not request.env["res.users"]._dally_ops_role():
            _logger.info(
                "ops/me refuse a l'utilisateur %s : aucun role Ops.",
                request.env.uid)
            return self._json(
                {"success": False,
                 "error": {"code": "forbidden",
                           "message": _("Accès réservé aux opérateurs terrain.")}},
                status=403,
            )

        return self._json({
            "success": True,
            "data": request.env["res.users"]._dally_ops_identity(),
        })
