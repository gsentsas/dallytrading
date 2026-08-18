# -*- coding: utf-8 -*-
"""
Routes de lecture de la boutique.

`GET /api/v1/shop/products` — le catalogue publié.
`GET /api/v1/shop/products/<reference>` — une fiche.
`POST /api/v1/shop/cart/resolve` — les prix d'un panier, calculés ici.

## Le panier est résolu côté serveur

Le navigateur détient un panier scellé qui ne contient que des références et des
quantités : aucun prix. Il faut donc bien que quelqu'un calcule le montant, et
ce quelqu'un ne peut être que le serveur. `cart/resolve` prend des références,
rend des lignes tarifées, et ignore tout le reste de ce qu'on lui envoie.

C'est aussi le point où la non-publication est vérifiée à nouveau. Un panier
survit à la dépublication d'un produit : le cookie a une durée de vie, la
décision de retirer un article de la vente est immédiate. Une ligne dont le
produit n'est plus publié disparaît du panier résolu — elle ne devient pas une
erreur, sinon le client se retrouve avec un panier qu'il ne peut plus ni voir ni
vider.

## Le contrat de discrétion

Une référence inconnue et une référence non publiée reçoivent la même réponse :
404, même code, même message. La distinction n'existe nulle part dans ce fichier
— pas dans les journaux, pas dans un compteur, pas dans une durée de traitement
qui dépendrait du cas.
"""

import logging

from odoo import http
from odoo.http import Response

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError

from ..models.product_template import ShopPricelistInvalid, ShopPricelistMissing

_logger = logging.getLogger(__name__)

#: Nombre maximal de produits rendus en une fois.
#:
#: Le catalogue du MVP est petit, mais une route publique sans borne est une
#: invitation : sans plafond, `?limit=100000` transforme une vitrine en export.
LIMITE_MAX = 60

#: Bornes du panier, dupliquées côté BFF.
#:
#: Les deux côtés vérifient, parce qu'ils protègent deux choses différentes : le
#: BFF protège la taille du cookie, le serveur protège le coût de la requête. Le
#: jour où l'un est contourné, l'autre tient encore.
MAX_LIGNES_PANIER = 20
MAX_QUANTITE_LIGNE = 999


class DallyShopController(DallyApiController):

    # ------------------------------------------------------------------
    # Tarif : deux échecs, deux codes
    # ------------------------------------------------------------------

    def _refus_tarif(self, api_key, erreur):
        """Traduit un échec de résolution du tarif en réponse HTTP.

        Deux codes, parce que les deux situations n'appellent pas le même écran :

        * `shop_pricelist_missing` — aucun tarif n'est configuré. La boutique n'a
          pas été ouverte ; le visiteur doit lire « en préparation », pas
          « momentanément indisponible ». Journalisé en **information** : c'est un
          état voulu, et le noter en erreur remplirait les journaux d'une alarme
          permanente que personne ne lirait plus ;
        * `shop_unavailable` — un tarif est configuré mais introuvable. Quelqu'un a
          décidé d'ouvrir et la configuration est cassée. Journalisé en **erreur**,
          parce que cela doit se voir et se réparer.

        Le statut reste 503 dans les deux cas : la boutique ne peut pas servir de
        prix, et c'est bien un état du serveur. C'est le code qui porte la nuance.
        """
        api_key._register_use()
        if isinstance(erreur, ShopPricelistMissing):
            _logger.info(
                "Boutique fermee : aucun tarif configure (%s). Etat attendu "
                "tant que la boutique n'est pas ouverte.", erreur,
            )
            return self._error(
                503, "shop_pricelist_missing", "Shop is not open yet."
            )
        _logger.error(
            "Boutique mal configuree : le tarif %s est introuvable.", erreur
        )
        return self._error(503, "shop_unavailable", "Shop is not configured.")

    # ------------------------------------------------------------------
    # Catalogue
    # ------------------------------------------------------------------

    @http.route(
        "/api/v1/shop/products",
        type="http",
        auth="none",
        readonly=False,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def list_products(self, **kwargs):
        try:
            api_key, env = self._authenticate("shop:read")
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        limite = self._borner(kwargs.get("limit"), defaut=LIMITE_MAX)
        categorie = kwargs.get("category") or None

        Produit = env["product.template"]
        try:
            tarif = Produit._dally_shop_pricelist()
        except (ShopPricelistMissing, ShopPricelistInvalid) as erreur:
            return self._refus_tarif(api_key, erreur)

        produits = Produit._dally_shop_search(
            categorie_slug=categorie, limite=limite
        )
        api_key._register_use()

        return self._json_response(
            {
                "success": True,
                "data": {
                    "products": produits._dally_shop_projection(tarif=tarif),
                    "categories": self._categories(env),
                },
            },
            status=200,
            # Même raisonnement que le catalogue de services : identique pour
            # tous les appelants, donc cachable. Court, pour qu'une dépublication
            # se propage en minutes et non en heures.
            cache_control="public, max-age=120",
        )

    @http.route(
        "/api/v1/shop/products/<string:reference>",
        type="http",
        auth="none",
        readonly=False,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def product_detail(self, reference, **kwargs):
        try:
            api_key, env = self._authenticate("shop:read")
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        Produit = env["product.template"]
        try:
            tarif = Produit._dally_shop_pricelist()
        except (ShopPricelistMissing, ShopPricelistInvalid) as erreur:
            return self._refus_tarif(api_key, erreur)

        produit = Produit._dally_shop_find(reference)
        api_key._register_use()

        if not produit:
            # Inconnu ou non publié : une seule réponse pour les deux.
            return self._error(404, "not_found", "Product not found.")

        projection = produit._dally_shop_projection(tarif=tarif, detail=True)[0]
        return self._json_response(
            {"success": True, "data": {"product": projection}},
            status=200,
            cache_control="public, max-age=120",
        )

    # ------------------------------------------------------------------
    # Image
    # ------------------------------------------------------------------

    @http.route(
        "/api/v1/shop/products/<string:reference>/image",
        type="http",
        auth="none",
        readonly=False,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def product_image(self, reference, **kwargs):
        """Les octets de l'image d'un produit publié.

        ## Une adresse publique, pas une adresse technique

        Odoo sert déjà les images par `/web/image/product.template/<id>/image_1920`.
        Cette route existe pour ne pas s'en servir : l'adresse générique publie le
        nom du modèle et l'identifiant de base, c'est-à-dire exactement les deux
        choses que la boutique s'interdit de laisser franchir la frontière depuis
        le premier jour. Elle ouvrirait aussi une énumération — les identifiants
        se suivent — et servirait l'image d'un produit **non publié** à qui
        devine son numéro.

        Ici la clé est le slug, et la publication est vérifiée à chaque appel.

        ## La galerie ne prend pas d'identifiant

        `?gallery=<jeton>` désigne une photo supplémentaire. Le jeton est
        l'empreinte du contenu de la photo, jamais son identifiant de base : le
        modèle le compare aux empreintes qu'il vient de calculer **pour ce
        produit**, si bien qu'aucune valeur venue du navigateur n'est utilisée
        comme clé de recherche. Un jeton valide pour un autre produit ne trouve
        rien, et un entier n'a aucune chance de ressembler à une empreinte.

        Sans `gallery`, c'est la photo principale — `image_1920` du produit.

        ## Le refus est le même pour tout le monde

        Inconnu, non publié, sans image, image d'un type refusé, jeton de
        galerie inconnu ou appartenant à un autre produit : un seul 404, même
        code, même corps. Le modèle rend `None` sans dire lequel des cas
        s'applique, et ce contrôleur n'a donc rien à divulguer même par
        inadvertance.

        ## Le cache ne s'applique qu'à ce qui est publié

        Une image publiée est identique pour tous les visiteurs : elle est
        cachable, et l'en-tête le dit. Un 404 passe par `_error`, qui pose
        `no-store` — sans quoi la non-publication d'aujourd'hui serait servie
        depuis un cache intermédiaire après la publication de demain.
        """
        try:
            api_key, env = self._authenticate("shop:read")
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        Produit = env["product.template"]
        try:
            resultat = Produit._dally_shop_image(
                reference, kwargs.get("size"), kwargs.get("gallery")
            )
        except (ShopPricelistMissing, ShopPricelistInvalid) as erreur:
            # La visibilité de l'image suit celle du catalogue, tarif compris :
            # une boutique fermée ne sert pas plus d'images que de prix.
            return self._refus_tarif(api_key, erreur)

        api_key._register_use()

        if resultat is None:
            return self._error(404, "not_found", "Product not found.")

        octets, mimetype = resultat
        return Response(
            octets,
            status=200,
            headers=[
                ("Content-Type", mimetype),
                ("Content-Length", str(len(octets))),
                # `inline` : l'image s'affiche dans la page. Sans en-tête, un
                # navigateur peut choisir de la télécharger.
                ("Content-Disposition", "inline"),
                ("Cache-Control", "public, max-age=120"),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )

    # ------------------------------------------------------------------
    # Résolution du panier
    # ------------------------------------------------------------------

    @http.route(
        "/api/v1/shop/cart/resolve",
        type="http",
        auth="none",
        readonly=False,
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def resolve_cart(self, **kwargs):
        """Tarifie un panier sans rien écrire.

        `POST` alors que la route ne modifie aucune donnée métier : le panier
        voyage dans le corps de la requête, et une liste de références dans une
        URL finirait dans les journaux d'accès et dans l'historique du navigateur.

        `readonly=False` comme les autres routes de lecture de l'API, et pour la
        même raison : `_register_use` incrémente le compteur d'usage de la clé.
        Sur un curseur en lecture seule cette écriture échouerait, et comme la
        télémétrie avale ses exceptions par conception, elle échouerait sans que
        personne le voie — les routes boutique n'auraient simplement jamais de
        compteur. Rien d'autre n'écrit ici.
        """
        try:
            api_key, env = self._authenticate("shop:read")
            payload = self._read_json_body()
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        lignes_demandees = payload.get("lines")
        if not isinstance(lignes_demandees, list):
            return self._error(422, "invalid_cart", "Field 'lines' must be a list.")
        if len(lignes_demandees) > MAX_LIGNES_PANIER:
            return self._error(422, "cart_too_large", "Too many cart lines.")

        demandes = []
        for ligne in lignes_demandees:
            if not isinstance(ligne, dict):
                return self._error(422, "invalid_cart", "Each line must be an object.")
            reference = ligne.get("reference")
            quantite = ligne.get("quantity")
            if not isinstance(reference, str) or not reference:
                return self._error(422, "invalid_cart", "Line reference is required.")
            if not isinstance(quantite, int) or isinstance(quantite, bool):
                return self._error(422, "invalid_cart", "Line quantity must be an integer.")
            if quantite < 1 or quantite > MAX_QUANTITE_LIGNE:
                return self._error(422, "invalid_cart", "Line quantity is out of range.")
            demandes.append((reference, quantite))

        Produit = env["product.template"]
        try:
            tarif = Produit._dally_shop_pricelist()
        except (ShopPricelistMissing, ShopPricelistInvalid) as erreur:
            return self._refus_tarif(api_key, erreur)

        # Une seule recherche pour toutes les références. Une boucle d'appels à
        # `_dally_shop_find` produirait une requête par ligne, et le panier est
        # relu à chaque affichage de page.
        references = {reference for reference, _q in demandes}
        publies = Produit.sudo().search(
            Produit._dally_shop_domain()
            + [("dally_shop_slug", "in", list(references))]
        )
        par_reference = {p.dally_shop_slug: p for p in publies}
        projections = {
            p["reference"]: p
            for p in publies._dally_shop_projection(tarif=tarif)
        }

        lignes = []
        retirees = []
        total = 0.0
        for reference, quantite in demandes:
            produit = par_reference.get(reference)
            if not produit:
                # Dépublié depuis la mise au panier, ou jamais publié. Dans les
                # deux cas la ligne s'efface, et le client en est informé sans
                # apprendre laquelle des deux situations s'applique.
                retirees.append(reference)
                continue
            projection = dict(projections[reference])
            prix = projection["price"]
            sous_total = prix * quantite
            total += sous_total
            projection.update({"quantity": quantite, "subtotal": sous_total})
            lignes.append(projection)

        api_key._register_use()

        return self._json_response(
            {
                "success": True,
                "data": {
                    "lines": lignes,
                    "removed": retirees,
                    "itemCount": sum(ligne["quantity"] for ligne in lignes),
                    "subtotal": total,
                    "currency": tarif.currency_id.name,
                    # Ni frais de livraison ni taxes : aucun des deux n'est
                    # décidé, et un montant inventé serait pire qu'un montant
                    # absent. Le total affiché est donc explicitement partiel.
                    "total": total,
                },
            },
            status=200,
            # Dépend du corps de la requête : jamais mis en cache.
            cache_control="no-store",
        )

    # ------------------------------------------------------------------
    # Interne
    # ------------------------------------------------------------------

    @staticmethod
    def _borner(brut, defaut):
        """Une limite entière dans [1, LIMITE_MAX], sans jamais lever.

        Un paramètre d'URL est du texte arbitraire : `?limit=abc` doit donner le
        comportement par défaut, pas une trace 500.
        """
        try:
            valeur = int(brut)
        except (TypeError, ValueError):
            return defaut
        return max(1, min(valeur, LIMITE_MAX))

    @staticmethod
    def _categories(env):
        categories = env["dally.shop.category"].sudo().search(
            [("published", "=", True)]
        )
        return [
            {
                "reference": categorie.slug,
                "name": categorie.name,
                "productCount": categorie.product_count,
            }
            for categorie in categories
        ]
