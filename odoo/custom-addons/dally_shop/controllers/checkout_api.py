# -*- coding: utf-8 -*-
"""
Les deux routes qui créent une commande — et pourquoi il en faut deux.

    POST /api/v1/shop/checkout          invité, clé `shop:checkout`
    POST /api/v1/portal/shop/checkout   client connecté, session portail

## Pourquoi pas une seule route

La tentation est forte : une route, un drapeau `guest`, un `if`. Elle produit
exactement le bug qu'on veut rendre impossible.

Dans cette architecture, une route à clé d'API s'exécute sous un **utilisateur
d'intégration** : `request.env.user` y est cet utilisateur de service, jamais le
client. Lire `env.user.partner_id` sur cette route rattacherait toutes les
commandes au partenaire de l'intégration. Et l'alternative — accepter un
`partner_id` dans le corps — transformerait un artefact de transport en
autorisation : la valeur serait authentiquement transmise et n'aurait rien prouvé.

L'identité d'un client connecté vit dans sa session portail, comme pour toutes les
autres mutations du portail. La séparation est donc celle des transports :

* route invité — clé `shop:checkout`, **exige** un bloc `customer`, et le refuse
  si l'appelant est en réalité authentifié ;
* route connectée — `auth="user"`, identité **uniquement**
  `request.env.user.partner_id`, et **refuse** tout bloc `customer`.

Aucune des deux ne peut produire le comportement de l'autre, et cela ne dépend
d'aucun `if` sur une valeur fournie par le navigateur.

## Ce que le navigateur ne fournit jamais

Une liste blanche : références, quantités, mode de remise, et pour un invité son
identité. Les champs de `sale.order` et `sale.order.line` qui décideraient d'un
prix, d'une remise, d'une taxe, d'un tarif, d'une identité, d'une société ou d'un
état sont **refusés** s'ils apparaissent — pas ignorés.

Refuser plutôt qu'ignorer, parce que ce sont deux messages différents. Ignorer
dit « ce champ ne sert à rien » ; refuser dit « quelque chose essaie de décider un
prix depuis le navigateur », ce qu'on veut lire dans les journaux plutôt que
perdre.
"""

import logging
import re

from psycopg2.errors import SerializationFailure

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError

from ..models.shop_order import MODES_REMISE, PortalAccountExists

_logger = logging.getLogger(__name__)

#: Champs que le navigateur n'a pas le droit de nommer.
#:
#: Chacun est un champ réel de `sale.order` ou `sale.order.line` dont l'écriture
#: depuis le public poserait un problème distinct.
#:
#: `tax_ids` **et** `tax_id` figurent dans la liste : l'audit montre que le champ
#: s'appelle `tax_ids` en Odoo 19, mais le nom historique reste celui qu'on
#: essaierait, et le refuser coûte un mot.
CHAMPS_INTERDITS = frozenset({
    "price_unit", "price_subtotal", "price_total", "discount",
    "tax_id", "tax_ids", "pricelist_id", "partner_id", "partner_invoice_id",
    "partner_shipping_id", "company_id", "state", "order_id", "order_line",
    "amount_total", "amount_untaxed", "amount_tax", "currency_id",
    "fiscal_position_id", "payment_term_id", "user_id", "team_id",
})

#: Bornes, alignées sur celles du panier scellé côté BFF.
MAX_LIGNES = 20
MAX_QUANTITE = 999

#: Longueurs maximales des champs d'identité.
#:
#: Un champ texte sans borne est une invitation : un `name` de 10 Mo remplit une
#: colonne, un journal, et une page d'administration.
LONGUEURS_MAX = {
    "name": 128,
    "email": 254,      # RFC 5321
    "phone": 32,
    "street": 200,
    "city": 100,
    "zip": 20,
    "country_code": 2,
}

#: Contrôle d'adresse volontairement permissif.
#:
#: Il écarte l'absurde — pas d'arobase, un espace, un retour à la ligne — sans
#: prétendre valider une adresse. Une expression stricte refuse des adresses
#: valides, et la seule preuve qu'une adresse existe est qu'un message y arrive.
_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$")

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class DallyShopCheckout(DallyApiController):
    """Le tronc commun. Les deux routes n'en diffèrent que par l'identité."""

    # ------------------------------------------------------------------
    # Route invité
    # ------------------------------------------------------------------

    @http.route(
        "/api/v1/shop/checkout",
        type="http",
        auth="none",
        readonly=False,
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def checkout_guest(self, **kwargs):
        try:
            api_key, env = self._authenticate("shop:checkout")
            payload = self._read_json_body()
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        api_key._register_use()

        refus = self._refuser_champs_interdits(payload)
        if refus:
            return refus

        try:
            demande = self._lire_demande(payload, invite=True)
        except ValueError as invalide:
            return self._error(422, "invalid_checkout", str(invalide))

        # Idempotence avant tout travail : un rejeu ne doit ni créer de contact,
        # ni relire le catalogue, ni produire un journal différent.
        existante = env["sale.order"]._dally_shop_find_by_cart(demande["cart_uuid"])
        if existante:
            return self._succes(existante, rejeu=True)

        try:
            partner = env["res.partner"]._dally_shop_create_guest(
                demande["cart_uuid"], demande["customer"]
            )
        except PortalAccountExists:
            # Décision explicite du propriétaire : on annonce qu'un compte existe
            # et on demande la connexion. C'est une divulgation d'existence de
            # compte, assumée — l'alternative, créer une seconde identité en
            # silence, dédoublerait le client dans l'ERP et laisserait ses
            # commandes hors de son espace client.
            return self._error(
                409, "portal_account_exists",
                "An account already exists for this email. Please sign in.",
            )

        return self._placer(env, demande, partner, invite=True)

    # ------------------------------------------------------------------
    # Route connectée
    # ------------------------------------------------------------------

    @http.route(
        "/api/v1/portal/shop/checkout",
        type="http",
        auth="user",
        readonly=False,
        methods=["POST"],
        csrf=False,
    )
    def checkout_connected(self, **kwargs):
        """Commande d'un client connecté.

        Aucune clé d'API n'intervient : le transport est la session portail, et
        `request.env.user` est le client lui-même. C'est la seule construction dans
        laquelle « l'identité vient d'Odoo » est littéralement vraie.
        """
        utilisateur = self._client_connecte()
        if not utilisateur:
            return self._error(403, "forbidden", "Not allowed.")

        try:
            payload = self._read_json_body()
        except DallyApiError as error:
            return self._error(error.status, error.code, error.message)

        refus = self._refuser_champs_interdits(payload)
        if refus:
            return refus

        try:
            demande = self._lire_demande(payload, invite=False)
        except ValueError as invalide:
            return self._error(422, "invalid_checkout", str(invalide))

        env = request.env
        existante = env["sale.order"]._dally_shop_find_by_cart(demande["cart_uuid"])
        if existante:
            return self._succes(existante, rejeu=True)

        # L'unique source d'identité. Rien du corps n'intervient — pas même le
        # nom, qui appartient au profil du client.
        return self._placer(env, demande, utilisateur.partner_id, invite=False)

    @staticmethod
    def _client_connecte():
        """L'appelant est-il bien un client du portail ?

        Les deux propriétés sont exigées, comme dans `dally_portal` : `share`
        exclut le personnel, et l'appartenance au groupe portail exclut un autre
        type d'utilisateur partagé. Un membre du personnel qui passerait par cette
        route créerait une commande à son propre nom — inoffensif mais absurde, et
        surtout impossible à distinguer d'une vraie commande client par la suite.
        """
        utilisateur = request.env.user
        if not utilisateur or utilisateur._is_public():
            return None
        if not (utilisateur.share and utilisateur.has_group("base.group_portal")):
            return None
        return utilisateur if utilisateur.partner_id else None

    # ------------------------------------------------------------------
    # Tronc commun
    # ------------------------------------------------------------------

    def _placer(self, env, demande, partner, invite):
        """Revalide le panier, crée la commande, rend la projection.

        L'ordre compte : le panier est revalidé **avant** la création, parce qu'un
        produit dépublié depuis la mise au panier doit faire échouer la commande
        et non produire une ligne qu'il faudrait ensuite retirer à la main.
        """
        try:
            lignes = env["product.template"]._dally_shop_resolve_lines(demande["lines"])
        except ValueError as refus:
            code, _sep, detail = str(refus).partition(":")
            if code == "empty_cart":
                return self._error(422, "empty_cart", "The cart is empty.")
            # Le détail nomme les références indisponibles. Ce n'est pas une
            # fuite : le client les a lui-même mises au panier, et sans elles il
            # ne saurait pas quoi corriger.
            return self._error(
                409, "unavailable_products",
                "Some products are no longer available: %s" % detail,
            )
        except UserError as pas_de_tarif:
            _logger.error("Checkout sans tarif boutique : %s", pas_de_tarif)
            return self._error(503, "shop_unavailable", "Shop is not configured.")

        try:
            commande = env["sale.order"].dally_shop_place_order(
                demande["cart_uuid"], partner, lignes,
                demande["delivery_mode"], invite=invite,
            )
        except SerializationFailure:
            # Course réelle. Laissée remonter : Odoo rejoue la requête entière et
            # le tour suivant trouve la commande de la gagnante. Un rejeu maison
            # ici ferait deux mécanismes de reprise concurrents.
            raise
        except ValidationError as invalide:
            _logger.error("Checkout boutique invalide : %s", invalide)
            return self._error(
                422, "invalid_checkout", "The order could not be created."
            )
        except AccessError:
            return self._error(403, "forbidden", "Not allowed.")

        return self._succes(commande, rejeu=False)

    def _refuser_champs_interdits(self, payload):
        """Balaie la charge à toute profondeur. Rend une réponse d'erreur ou None.

        La profondeur importe : un `price_unit` glissé dans une ligne est le cas
        intéressant, et un balayage de surface le manquerait.
        """
        intrus = self._champs_interdits(payload)
        if not intrus:
            return None
        _logger.warning(
            "Checkout boutique refuse : champs interdits %s", sorted(intrus)
        )
        return self._error(
            422, "forbidden_fields",
            "These fields cannot be provided: %s" % ", ".join(sorted(intrus)),
        )

    @classmethod
    def _champs_interdits(cls, charge, trouves=None):
        trouves = set() if trouves is None else trouves
        if isinstance(charge, dict):
            for clef, valeur in charge.items():
                if clef in CHAMPS_INTERDITS:
                    trouves.add(clef)
                cls._champs_interdits(valeur, trouves)
        elif isinstance(charge, list):
            for element in charge:
                cls._champs_interdits(element, trouves)
        return trouves

    @classmethod
    def _lire_demande(cls, payload, invite):
        """Liste blanche stricte. Toute anomalie lève `ValueError`."""
        cart_uuid = payload.get("cartId")
        if not isinstance(cart_uuid, str) or not _UUID.match(cart_uuid):
            raise ValueError("A valid cart identifier is required.")

        mode = payload.get("deliveryMode")
        if mode not in dict(MODES_REMISE):
            raise ValueError("A valid delivery mode is required.")

        lignes_brutes = payload.get("lines")
        if not isinstance(lignes_brutes, list) or not lignes_brutes:
            raise ValueError("At least one cart line is required.")
        if len(lignes_brutes) > MAX_LIGNES:
            raise ValueError("Too many cart lines.")

        lignes = []
        vues = set()
        for brute in lignes_brutes:
            if not isinstance(brute, dict):
                raise ValueError("Each line must be an object.")
            reference = brute.get("reference")
            quantite = brute.get("quantity")
            if not isinstance(reference, str) or not _SLUG.match(reference or ""):
                raise ValueError("A line reference is invalid.")
            if isinstance(quantite, bool) or not isinstance(quantite, int):
                raise ValueError("A line quantity must be an integer.")
            if quantite < 1 or quantite > MAX_QUANTITE:
                raise ValueError("A line quantity is out of range.")
            if reference in vues:
                # Deux lignes pour la même référence : impossible de décider
                # laquelle l'emporte, et ce n'est pas au serveur de choisir.
                raise ValueError("A reference appears twice.")
            vues.add(reference)
            lignes.append((reference, quantite))

        brut_client = payload.get("customer")
        if invite:
            if brut_client is None:
                raise ValueError("Customer details are required for a guest order.")
            client = cls._lire_identite(brut_client)
        else:
            # Un client connecté qui enverrait une identité essaie de commander
            # au nom d'un autre, ou de modifier son profil par une route qui n'est
            # pas faite pour ça. Refus, pas silence.
            if brut_client is not None:
                raise ValueError(
                    "Customer details cannot be provided for a signed-in order."
                )
            client = None

        return {
            "cart_uuid": cart_uuid,
            "delivery_mode": mode,
            "lines": lignes,
            "customer": client,
        }

    @classmethod
    def _lire_identite(cls, brut):
        """L'identité d'un invité, bornée champ par champ."""
        if not isinstance(brut, dict):
            raise ValueError("Customer details must be an object.")

        inconnus = set(brut) - set(LONGUEURS_MAX)
        if inconnus:
            raise ValueError(
                "Unknown customer fields: %s" % ", ".join(sorted(inconnus))
            )

        identite = {}
        for champ, longueur in LONGUEURS_MAX.items():
            valeur = brut.get(champ)
            if valeur is None or valeur == "":
                identite[champ] = ""
                continue
            if not isinstance(valeur, str):
                raise ValueError("Customer field '%s' must be text." % champ)
            valeur = valeur.strip()
            if len(valeur) > longueur:
                raise ValueError("Customer field '%s' is too long." % champ)
            identite[champ] = valeur

        if not identite["name"]:
            raise ValueError("A customer name is required.")
        if not _EMAIL.match(identite["email"]):
            raise ValueError("A valid customer email is required.")
        return identite

    # ------------------------------------------------------------------
    # Réponse
    # ------------------------------------------------------------------

    def _succes(self, commande, rejeu):
        """La commande, projetée pour le client.

        `replayed` dit au BFF qu'il n'a rien créé cette fois — ce dont il a besoin
        pour ne pas faire tourner deux fois l'identifiant de panier. Ce n'est pas
        une information sensible : le client sait qu'il a cliqué deux fois.
        """
        projection = commande._dally_shop_projection()
        projection["replayed"] = rejeu
        return self._json_response(
            {"success": True, "data": {"order": projection}},
            status=200,
            cache_control="no-store",
        )
