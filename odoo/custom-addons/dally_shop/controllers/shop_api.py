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
from odoo.exceptions import UserError

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError

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
        except UserError as erreur:
            # La boutique n'a pas de tarif. C'est une erreur de configuration du
            # serveur, pas une erreur du client : 503, et le message reste
            # générique côté public.
            _logger.error("boutique sans tarif configure: %s", erreur)
            api_key._register_use()
            return self._error(503, "shop_unavailable", "Shop is not configured.")

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
        except UserError as erreur:
            _logger.error("boutique sans tarif configure: %s", erreur)
            api_key._register_use()
            return self._error(503, "shop_unavailable", "Shop is not configured.")

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
        except UserError as erreur:
            _logger.error("boutique sans tarif configure: %s", erreur)
            api_key._register_use()
            return self._error(503, "shop_unavailable", "Shop is not configured.")

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
