# -*- coding: utf-8 -*-
"""API portail — exécutée sous l'identité du client, jamais sous une clé de service.

## La différence avec /api/v1/* du site public

Les endpoints publics de ``dally_api`` s'authentifient par clé d'API et agissent
sous un utilisateur d'intégration : c'est le contrôleur qui décide ce qui sort.
Ici, l'inverse. La requête s'exécute sous le ``res.users`` portail du client, et ce
sont les ACL et les record rules qui décident. Le contrôleur ne fait que projeter.

Conséquence pratique : si l'un des ``search`` ci-dessous oubliait un filtre, il ne
ramènerait **toujours** que les dossiers du client. Le contrôleur n'est pas la
barrière — c'est ce qui rend cette couche relativement sûre à faire évoluer.

## Aucune identité ne vient de la requête

Ni ``partner_id``, ni ``customer_id``, ni ``user_id`` ne sont lus depuis l'URL ou le
corps. L'identité est ``request.env.user``, point. Un domaine de sécurité construit
à partir d'une valeur envoyée par le navigateur serait une autorisation accordée par
l'attaquant lui-même.

## Pourquoi les utilisateurs internes sont refusés

Un salarié qui appellerait ces routes verrait, sous ses propres droits, bien plus
que ce que la projection prévoit — et la projection serait alors la seule barrière,
exactement ce qu'on refuse. Ces routes sont réservées aux utilisateurs ``share``.
Le personnel a l'interface Odoo.
"""

import logging

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

_logger = logging.getLogger(__name__)

#: Pagination : défaut raisonnable, plafond dur.
#:
#: Sans plafond, `?limit=100000` transforme un endpoint de consultation en outil
#: d'extraction — et en levier de déni de service, puisque chaque enregistrement
#: coûte une projection.
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

#: Tris autorisés, par nom logique.
#:
#: Une chaîne `order` transmise telle quelle à l'ORM est une injection : on peut y
#: glisser un champ protégé et l'utiliser comme oracle, en observant l'ordre des
#: résultats pour deviner une marge sans jamais la lire.
SORTS = {
    "recent": "create_date desc, id desc",
    "oldest": "create_date asc, id asc",
}

#: Les six ressources exposées, et comment on les atteint.
#:
#: Déclaré comme donnée : ajouter une ressource, c'est ajouter une ligne, et la
#: pagination, l'anti-énumération et la projection s'y appliquent automatiquement.
#: Un endpoint écrit à la main finirait par en oublier une.
RESOURCES = {
    "quotes": {"model": "dally.quote.request"},
    "sourcing": {"model": "dally.sourcing.request"},
    "trades": {"model": "dally.trade.opportunity"},
    "shipments": {"model": "dally.shipment"},
    "documents": {"model": "dally.portal.document"},
}


class DallyPortalController(http.Controller):

    # ─── Utilitaires ─────────────────────────────────────────────────

    @staticmethod
    def _json(body, status=200):
        """Réponse JSON, jamais mise en cache par un intermédiaire.

        `private, no-store` sur toutes les réponses sans exception : un proxy ou un
        CDN qui mettrait en cache la liste des devis du client A la servirait au
        client B. `no-store` est plus fort que `no-cache` — il interdit l'écriture,
        pas seulement la réutilisation sans revalidation.
        """
        return request.make_json_response(body, status=status, headers=[
            ("Cache-Control", "private, no-store, max-age=0"),
            ("Pragma", "no-cache"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
        ])

    @classmethod
    def _error(cls, status, code, message):
        return cls._json({"success": False, "error": {"code": code,
                                                      "message": message}}, status)

    @classmethod
    def _not_found(cls):
        """La seule réponse pour tout ce que le client ne doit pas atteindre.

        Référence inexistante, dossier d'un autre client, proposition en brouillon,
        document non publié : même statut, même corps, même formulation. Distinguer
        « n'existe pas » de « ne vous appartient pas » confirmerait à un attaquant
        que la référence est valide — c'est-à-dire lui apprendrait quelque chose.
        """
        return cls._error(404, "not_found", "Ressource introuvable.")

    @staticmethod
    def _portal_user_or_none():
        """L'appelant est-il bien un client ?

        `share` est ce qui distingue un utilisateur portail d'un salarié. Le tester
        plutôt que l'appartenance à `base.group_portal` couvre aussi le cas d'un
        futur groupe portail dérivé.
        """
        user = request.env.user
        return user if user and user.share else None

    @classmethod
    def _pagination(cls, kwargs):
        """Borne la pagination, en silence plutôt qu'en erreur.

        Une valeur hors bornes est ramenée dans les bornes : un client qui demande
        10 000 lignes n'attaque pas forcément, et lui renvoyer 100 est plus utile
        qu'un 422.
        """
        try:
            limit = int(kwargs.get("limit") or DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
        try:
            offset = int(kwargs.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)
        order = SORTS.get(str(kwargs.get("sort") or "recent"), SORTS["recent"])
        return limit, offset, order

    # ─── Identité ────────────────────────────────────────────────────

    @http.route("/api/v1/portal/me", type="http", auth="user",
                methods=["GET"], csrf=False, readonly=True)
    def me(self, **kwargs):
        """Qui suis-je, du point de vue du portail.

        Aucun `sudo` : les champs lus le sont sous l'identité de l'appelant, et la
        record rule native sur `res.partner` limite déjà ce qu'il voit de lui-même
        et de sa société.
        """
        user = self._portal_user_or_none()
        if not user:
            return self._error(403, "forbidden",
                               "Ces routes sont réservées aux comptes clients.")
        partner = user.partner_id
        company = partner.commercial_partner_id
        return self._json({"success": True, "data": {
            "name": partner.name,
            "email": partner.email or None,
            "phone": partner.phone or None,
            "company": company.name if company != partner else None,
            "city": partner.city or None,
            "country": partner.country_id.name or None,
        }})

    # ─── Tableau de bord ─────────────────────────────────────────────

    @http.route("/api/v1/portal/dashboard", type="http", auth="user",
                methods=["GET"], csrf=False, readonly=True)
    def dashboard(self, **kwargs):
        """Compteurs et derniers dossiers, bornés.

        Chaque `search_count` et chaque `search` s'exécute sous l'identité du
        client : les compteurs comptent ses dossiers, sans qu'aucun domaine ne le
        précise. Un `sudo` ici — tentant pour « compter plus vite » — compterait
        ceux de tout le monde.
        """
        if not self._portal_user_or_none():
            return self._error(403, "forbidden",
                               "Ces routes sont réservées aux comptes clients.")
        data = {"counters": {}, "recent": {}}
        for name, spec in RESOURCES.items():
            model = request.env[spec["model"]]
            data["counters"][name] = model.search_count([])
            data["recent"][name] = [
                record._dally_portal_payload()
                for record in model.search([], limit=5, order=SORTS["recent"])
            ]
        return self._json({"success": True, "data": data})

    # ─── Listes et détails ───────────────────────────────────────────

    def _list(self, resource, kwargs):
        if not self._portal_user_or_none():
            return self._error(403, "forbidden",
                               "Ces routes sont réservées aux comptes clients.")
        limit, offset, order = self._pagination(kwargs)
        model = request.env[RESOURCES[resource]["model"]]
        # Domaine vide : la record rule fournit le filtre de sécurité. Accepter un
        # domaine du client reviendrait à lui laisser écrire sa propre requête.
        total = model.search_count([])
        records = model.search([], limit=limit, offset=offset, order=order)
        return self._json({"success": True, "data": {
            "items": [record._dally_portal_payload() for record in records],
            "total": total, "limit": limit, "offset": offset,
        }})

    def _detail(self, resource, reference):
        if not self._portal_user_or_none():
            return self._error(403, "forbidden",
                               "Ces routes sont réservées aux comptes clients.")
        model = request.env[RESOURCES[resource]["model"]]
        field = "name" if resource == "documents" else "reference"
        try:
            record = model.search([(field, "=", reference)], limit=1)
        except (AccessError, ValueError):
            return self._not_found()
        if not record:
            return self._not_found()
        try:
            return self._json({"success": True,
                               "data": record._dally_portal_payload()})
        except (AccessError, MissingError):
            return self._not_found()

    @http.route("/api/v1/portal/quotes", type="http", auth="user",
                methods=["GET"], csrf=False, readonly=True)
    def quotes(self, **kwargs):
        return self._list("quotes", kwargs)

    @http.route("/api/v1/portal/quotes/<string:reference>", type="http",
                auth="user", methods=["GET"], csrf=False, readonly=True)
    def quote_detail(self, reference, **kwargs):
        return self._detail("quotes", reference)

    @http.route("/api/v1/portal/sourcing", type="http", auth="user",
                methods=["GET"], csrf=False, readonly=True)
    def sourcing(self, **kwargs):
        return self._list("sourcing", kwargs)

    @http.route("/api/v1/portal/sourcing/<string:reference>", type="http",
                auth="user", methods=["GET"], csrf=False, readonly=True)
    def sourcing_detail(self, reference, **kwargs):
        return self._detail("sourcing", reference)

    @http.route("/api/v1/portal/trades", type="http", auth="user",
                methods=["GET"], csrf=False, readonly=True)
    def trades(self, **kwargs):
        return self._list("trades", kwargs)

    @http.route("/api/v1/portal/trades/<string:reference>", type="http",
                auth="user", methods=["GET"], csrf=False, readonly=True)
    def trade_detail(self, reference, **kwargs):
        return self._detail("trades", reference)

    @http.route("/api/v1/portal/shipments", type="http", auth="user",
                methods=["GET"], csrf=False, readonly=True)
    def shipments(self, **kwargs):
        return self._list("shipments", kwargs)

    @http.route("/api/v1/portal/shipments/<string:reference>", type="http",
                auth="user", methods=["GET"], csrf=False, readonly=True)
    def shipment_detail(self, reference, **kwargs):
        return self._detail("shipments", reference)

    @http.route("/api/v1/portal/documents", type="http", auth="user",
                methods=["GET"], csrf=False, readonly=True)
    def documents(self, **kwargs):
        return self._list("documents", kwargs)

    # ─── Téléchargement ──────────────────────────────────────────────

    @http.route("/api/v1/portal/documents/<int:document_id>/download",
                type="http", auth="user", methods=["GET"], csrf=False)
    def document_download(self, document_id, **kwargs):
        """Le contrôle d'accès est refait ici, pas hérité de l'affichage.

        Le `search` ci-dessous passe par la record rule portail, qui exige à la fois
        l'appartenance au client et `published_to_portal`. Un identifiant deviné ne
        ramène donc rien, et la réponse est le même 404 que pour un document
        inexistant.

        L'identifiant numérique est accepté ici — et uniquement ici — parce qu'il ne
        confère aucun droit : il désigne une ligne que la record rule doit de toute
        façon laisser passer.
        """
        if not self._portal_user_or_none():
            return self._error(403, "forbidden",
                               "Ces routes sont réservées aux comptes clients.")
        document = request.env["dally.portal.document"].search([
            ("id", "=", document_id),
        ], limit=1)
        if not document:
            return self._not_found()
        try:
            attachment = document._dally_portal_readable_attachment()
        except Exception:  # noqa: BLE001
            # Toute défaillance devient un 404 : distinguer « non publié » de
            # « n'existe pas » renseignerait l'appelant.
            return self._not_found()
        if not attachment or not attachment.datas:
            return self._not_found()

        import base64
        content = base64.b64decode(attachment.datas)
        # Nom de fichier assaini : un nom contenant un saut de ligne ou un guillemet
        # permettrait d'injecter un en-tête supplémentaire dans la réponse.
        safe_name = "".join(
            char for char in (attachment.name or "document")
            if char.isalnum() or char in " ._-"
        ).strip() or "document"
        # Type MIME jamais repris tel quel : une valeur contrôlée par l'uploadeur
        # pourrait faire interpréter le fichier comme du HTML dans le navigateur.
        return request.make_response(content, headers=[
            ("Content-Type", "application/octet-stream"),
            ("Content-Disposition", f'attachment; filename="{safe_name}"'),
            ("Content-Length", str(len(content))),
            ("Cache-Control", "private, no-store, max-age=0"),
            ("X-Content-Type-Options", "nosniff"),
        ])
