# -*- coding: utf-8 -*-
"""La barrière qui empêche un autre site de parler à l'API Ops avec le cookie
de l'opérateur.

## Ce qui était ouvert

Chaque route ``/api/v1/ops/`` porte ``csrf=False``, et c'est délibéré : le
jeton CSRF d'Odoo est fabriqué par un gabarit QWeb, or aucune de ces routes
n'est servie par un gabarit — elles répondent à la passerelle Next.js, qui
n'en reçoit jamais.

Mais ``csrf=False`` ne dit pas « cette route est sûre ». Il dit « ne cherche
pas de jeton ». Il ne restait donc plus rien, et le montage a trois propriétés
qui, réunies, rendaient la falsification possible :

1. Odoo pose ``session_id`` **sans attribut ``SameSite``** — vérifié sur cette
   version : ``set_cookie('session_id', …, httponly=True)``. Le navigateur
   applique alors sa valeur par défaut, qui n'est pas la même partout :
   ``Lax`` sur Chrome, **absente sur Firefox de série**. Là où elle est
   absente, le cookie part sur une requête POST inter-site.
2. Les routes lisent le corps brut — ``json.loads(request.httprequest
   .get_data())`` — **sans regarder le ``Content-Type``**. Un formulaire HTML
   en ``enctype="text/plain"`` livre donc un corps JSON valide.
3. Un formulaire de ce type est une « requête simple » au sens CORS : aucun
   pré-vol, donc aucune politique CORS à franchir — et il n'y en a d'ailleurs
   aucune de déclarée.

Une page hostile visitée par quelqu'un connecté au CRM dans son navigateur
pouvait ainsi créer un dossier, encaisser, ou ajouter un colis.

## Ce qui distingue un appel légitime

La passerelle Next.js n'est pas un navigateur. Elle appelle Odoo depuis Node,
en construisant ses en-têtes une par une : ``X-Request-ID``, ``Content-Type``,
et le ``Cookie`` de session qu'elle tient de son propre magasin. Elle n'émet
donc **ni ``Origin`` ni ``Sec-Fetch-Site``** — un navigateur, lui, en émet
toujours sur une requête inter-origine, et ne laisse aucun script les
fabriquer : ce sont des en-têtes interdits.

D'où les trois règles ci-dessous. Aucune ne demande de jeton, aucune ne touche
au navigateur, et la passerelle les satisfait déjà sans être modifiée.

## Pourquoi ici et pas route par route

Vingt-trois routes mutantes sur neuf contrôleurs. Une protection recopiée
vingt-trois fois est une protection qui manquera à la vingt-quatrième. Le
contrôle vit donc au point de passage obligé, ``ir.http._pre_dispatch``, et
s'applique avant que le corps de la requête ne soit seulement lu.
"""

import logging
from urllib.parse import urlparse

import werkzeug.exceptions

from odoo import models
from odoo.http import request

_logger = logging.getLogger(__name__)

#: La surface protégée : les routes authentifiées par le cookie de session.
#:
#: ``/api/v1/freight/`` en est volontairement exclu — ces routes-là sont en
#: ``auth="none"`` et s'authentifient par clé d'API. Un navigateur ne peut pas
#: joindre une clé d'API à une requête inter-site sans pré-vol, donc il n'y a
#: rien à falsifier : aucun identifiant ambiant n'est en jeu.
PREFIXE_OPS = "/api/v1/ops/"

#: Les méthodes qui changent l'état. ``GET`` et ``HEAD`` restent libres : sans
#: politique CORS, une page hostile ne peut pas lire ce qu'elles répondent.
METHODES_MUTANTES = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Le seul ``Content-Type`` accepté pour une mutation JSON.
#:
#: C'est la règle qui ferme la faille : ``application/json`` ne fait pas partie
#: des types qu'un formulaire HTML sait émettre — un navigateur ne connaît que
#: ``application/x-www-form-urlencoded``, ``multipart/form-data`` et
#: ``text/plain``. L'exiger force donc un script inter-origine à passer par un
#: pré-vol CORS, qu'aucune politique n'autorise ici.
TYPE_JSON = "application/json"

#: L'envoi de fichier, qui ne peut pas être discriminé par son type — un
#: formulaire HTML sait l'émettre. Ce sont les règles ``Origin`` et
#: ``Sec-Fetch-Site`` qui protègent ces deux routes.
TYPE_FICHIER = "multipart/form-data"

#: Les contextes de navigation admis. ``none`` est la saisie directe dans la
#: barre d'adresse, ``same-origin`` et ``same-site`` viennent du domaine.
#: ``cross-site`` est précisément le cas à refuser.
CONTEXTES_ADMIS = frozenset({"same-origin", "same-site", "none"})


class RefusOrigineCroisee(werkzeug.exceptions.Forbidden):
    """Un 403 qui parle JSON, comme le reste de l'API.

    ``_pre_dispatch`` ne peut pas rendre de réponse : il ne peut que lever.
    Une ``HTTPException`` werkzeug est elle-même une application WSGI, et
    redéfinir son corps suffit à lui faire rendre la forme d'erreur que la
    passerelle sait déjà lire — plutôt que la page HTML par défaut.
    """

    #: Le motif ne descend pas au client. Dire « il manquait le Content-Type »
    #: à un attaquant, c'est lui dire quoi corriger.
    def get_body(self, environ=None, scope=None):
        return (
            '{"success": false, "error": {"code": "cross_origin_refused", '
            '"message": "Requete refusee."}}'
        )

    def get_headers(self, environ=None, scope=None):
        return [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Cache-Control", "private, no-store, max-age=0"),
            ("X-Content-Type-Options", "nosniff"),
        ]


class DallyOpsHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _pre_dispatch(cls, rule, args):
        """Refuse la requête inter-origine avant que son corps ne soit lu.

        Le contrôle passe **avant** ``super()`` : rien ne justifie d'analyser
        la charge d'une requête qu'on s'apprête à refuser.
        """
        cls._dally_ops_verifier_origine(rule)
        return super()._pre_dispatch(rule, args)

    # ------------------------------------------------------------------

    @classmethod
    def _dally_ops_verifier_origine(cls, rule):
        """Les trois règles, dans l'ordre du plus sûr au plus général.

        Lève ``RefusOrigineCroisee`` ; ne rend rien. Hors de la surface Ops et
        hors des méthodes mutantes, ne fait rien du tout.
        """
        requete = request.httprequest
        if requete.method not in METHODES_MUTANTES:
            return
        if not requete.path.startswith(PREFIXE_OPS):
            return

        # 1. `Origin`. Un navigateur l'émet toujours sur une requête mutante,
        #    et aucun script ne peut le falsifier : c'est un en-tête interdit.
        #    La passerelle, elle, n'en émet pas — d'où « présent ET étranger »
        #    plutôt que « obligatoire ».
        origine = requete.headers.get("Origin")
        if origine and not cls._dally_ops_meme_origine(origine, requete.host):
            cls._dally_ops_refuser(rule, "origine étrangère")

        # 2. `Sec-Fetch-Site`. Même nature d'en-tête, et il couvre le cas où
        #    un navigateur omettrait `Origin`.
        contexte = requete.headers.get("Sec-Fetch-Site")
        if contexte and contexte not in CONTEXTES_ADMIS:
            cls._dally_ops_refuser(rule, "contexte de navigation croisé")

        # 3. Le `Content-Type`. C'est la règle qui ferme le formulaire HTML,
        #    seul vecteur qui n'a besoin ni de CORS ni de JavaScript.
        type_recu = (requete.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if type_recu == TYPE_FICHIER:
            return
        if type_recu != TYPE_JSON:
            cls._dally_ops_refuser(rule, "type de contenu non JSON")

    @staticmethod
    def _dally_ops_meme_origine(origine, hote):
        """Compare l'origine annoncée à l'hôte servi.

        La comparaison porte sur l'autorité — hôte et port — et non sur le
        schéma : derrière un proxy, le schéma vu par Odoo est celui du saut
        interne, pas celui du navigateur, et exiger leur égalité refuserait du
        trafic légitime pour une raison qui n'a rien à voir avec l'attaque.
        """
        return urlparse(origine).netloc.lower() == (hote or "").lower()

    @classmethod
    def _dally_ops_refuser(cls, rule, motif):
        """Journalise puis lève.

        Le journal retient le **motif de route** — ``/api/v1/ops/intakes/
        <string:reference>/lines`` — et jamais le chemin concret : celui-ci
        porte une référence de dossier, donc une donnée métier, qui n'a rien à
        faire dans un journal d'infrastructure.
        """
        _logger.warning(
            "Ops refuse une mutation inter-origine sur %s : %s.",
            getattr(rule, "rule", "?"), motif)
        raise RefusOrigineCroisee()
