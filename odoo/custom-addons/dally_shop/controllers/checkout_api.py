# -*- coding: utf-8 -*-
"""Checkout boutique : invité par clé dédiée, client connecté par session portail.

Le navigateur transmet uniquement le code public d'une méthode de remise, les
références/quantités déjà scellées par le BFF, et éventuellement une adresse de
livraison. Aucun prix, identifiant Odoo ni état métier n'est accepté.
"""

import logging
import re

from psycopg2.errors import SerializationFailure

from odoo import http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError

from ..models.product_template import ShopPricelistInvalid, ShopPricelistMissing
from ..models.shop_order import PortalAccountExists

_logger = logging.getLogger(__name__)

CHAMPS_INTERDITS = frozenset({
    "price_unit", "price_subtotal", "price_total", "discount",
    "tax_id", "tax_ids", "pricelist_id", "partner_id", "partner_invoice_id",
    "partner_shipping_id", "company_id", "state", "order_id", "order_line",
    "amount_total", "amount_untaxed", "amount_tax", "currency_id",
    "fiscal_position_id", "payment_term_id", "user_id", "team_id",
    "dally_shop_delivery_fee", "dally_shop_delivery_fee_state",
    "dally_shop_fulfillment_state", "dally_shop_fulfillment_authorized",
})

MAX_LIGNES = 20
MAX_QUANTITE = 999

LONGUEURS_MAX = {
    "name": 128,
    "email": 254,
    "phone": 32,
    "street": 200,
    "city": 100,
    "zip": 20,
    "country_code": 2,
}

LIVRAISON_LONGUEURS = {
    "name": 128,
    "phone": 32,
    "street": 200,
    "street2": 200,
    "city": 100,
    "zip": 20,
    "country_code": 2,
}

_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_METHOD_CODE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


class DallyShopCheckout(DallyApiController):

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

        existante = env["sale.order"]._dally_shop_find_by_cart(demande["cart_uuid"])
        if existante:
            return self._succes(existante, rejeu=True)

        try:
            partner = env["res.partner"]._dally_shop_create_guest(
                demande["cart_uuid"], demande["customer"]
            )
        except PortalAccountExists:
            return self._error(
                409,
                "portal_account_exists",
                "An account already exists for this email. Please sign in.",
            )

        return self._placer(env, demande, partner, invite=True)

    @http.route(
        "/api/v1/portal/shop/checkout",
        type="http",
        auth="user",
        readonly=False,
        methods=["POST"],
        csrf=False,
    )
    def checkout_connected(self, **kwargs):
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

        return self._placer(env, demande, utilisateur.partner_id, invite=False)

    @staticmethod
    def _client_connecte():
        utilisateur = request.env.user
        if not utilisateur or utilisateur._is_public():
            return None
        if not (utilisateur.share and utilisateur.has_group("base.group_portal")):
            return None
        return utilisateur if utilisateur.partner_id else None

    def _placer(self, env, demande, partner, invite):
        try:
            lignes = env["product.template"]._dally_shop_resolve_lines(demande["lines"])
        except ValueError as refus:
            code, _sep, detail = str(refus).partition(":")
            if code == "empty_cart":
                return self._error(422, "empty_cart", "The cart is empty.")
            return self._error(
                409,
                "unavailable_products",
                "Some products are no longer available: %s" % detail,
            )
        except ShopPricelistMissing as ferme:
            _logger.info("Checkout refuse : boutique fermee (%s).", ferme)
            return self._error(503, "shop_pricelist_missing", "Shop is not open yet.")
        except ShopPricelistInvalid as casse:
            _logger.error("Checkout impossible : tarif boutique introuvable (%s).", casse)
            return self._error(503, "shop_unavailable", "Shop is not configured.")

        try:
            commande = env["sale.order"].dally_shop_place_order(
                demande["cart_uuid"],
                partner,
                lignes,
                demande["delivery_mode"],
                invite=invite,
                shipping=demande["shipping"],
            )
        except SerializationFailure:
            raise
        except ValidationError as invalide:
            _logger.info("Checkout boutique refuse : %s", invalide)
            return self._error(
                422,
                "invalid_checkout",
                "The order could not be created with these delivery details.",
            )
        except AccessError:
            return self._error(403, "forbidden", "Not allowed.")

        return self._succes(commande, rejeu=False)

    def _refuser_champs_interdits(self, payload):
        intrus = self._champs_interdits(payload)
        if not intrus:
            return None
        _logger.warning("Checkout boutique refuse : champs interdits %s", sorted(intrus))
        return self._error(
            422,
            "forbidden_fields",
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
        if not isinstance(payload, dict):
            raise ValueError("Checkout payload must be an object.")

        autorises = {"cartId", "deliveryMode", "lines", "customer", "shipping"}
        inconnus = set(payload) - autorises
        if inconnus:
            raise ValueError("Unknown checkout fields are not allowed.")

        cart_uuid = payload.get("cartId")
        if not isinstance(cart_uuid, str) or not _UUID.match(cart_uuid):
            raise ValueError("A valid cart identifier is required.")

        mode = payload.get("deliveryMode")
        if not isinstance(mode, str) or not _METHOD_CODE.match(mode):
            raise ValueError("A valid delivery method code is required.")

        lignes_brutes = payload.get("lines")
        if not isinstance(lignes_brutes, list) or not lignes_brutes:
            raise ValueError("At least one cart line is required.")
        if len(lignes_brutes) > MAX_LIGNES:
            raise ValueError("Too many cart lines.")

        lignes = []
        vues = set()
        for brute in lignes_brutes:
            if not isinstance(brute, dict) or set(brute) != {"reference", "quantity"}:
                raise ValueError("Each line must contain only reference and quantity.")
            reference = brute.get("reference")
            quantite = brute.get("quantity")
            if not isinstance(reference, str) or not _SLUG.match(reference or ""):
                raise ValueError("A line reference is invalid.")
            if isinstance(quantite, bool) or not isinstance(quantite, int):
                raise ValueError("A line quantity must be an integer.")
            if quantite < 1 or quantite > MAX_QUANTITE:
                raise ValueError("A line quantity is out of range.")
            if reference in vues:
                raise ValueError("A reference appears twice.")
            vues.add(reference)
            lignes.append((reference, quantite))

        brut_client = payload.get("customer")
        if invite:
            if brut_client is None:
                raise ValueError("Customer details are required for a guest order.")
            client = cls._lire_identite(brut_client)
        else:
            if brut_client is not None:
                raise ValueError(
                    "Customer details cannot be provided for a signed-in order."
                )
            client = None

        shipping = cls._lire_livraison(payload.get("shipping"))

        return {
            "cart_uuid": cart_uuid,
            "delivery_mode": mode,
            "lines": lignes,
            "customer": client,
            "shipping": shipping,
        }

    @classmethod
    def _lire_identite(cls, brut):
        if not isinstance(brut, dict):
            raise ValueError("Customer details must be an object.")
        inconnus = set(brut) - set(LONGUEURS_MAX)
        if inconnus:
            raise ValueError("Unknown customer fields are not allowed.")

        identite = {}
        for champ, longueur in LONGUEURS_MAX.items():
            valeur = brut.get(champ)
            if valeur is None or valeur == "":
                identite[champ] = ""
                continue
            if not isinstance(valeur, str):
                raise ValueError("Customer fields must be text.")
            valeur = valeur.strip()
            if len(valeur) > longueur:
                raise ValueError("A customer field is too long.")
            identite[champ] = valeur

        if not identite["name"]:
            raise ValueError("A customer name is required.")
        if not _EMAIL.match(identite["email"]):
            raise ValueError("A valid customer email is required.")
        if identite["country_code"]:
            identite["country_code"] = identite["country_code"].upper()
            if not re.match(r"^[A-Z]{2}$", identite["country_code"]):
                raise ValueError("Customer country code must contain two letters.")
        return identite

    @classmethod
    def _lire_livraison(cls, brut):
        if brut is None:
            return None
        if not isinstance(brut, dict):
            raise ValueError("Shipping address must be an object.")
        inconnus = set(brut) - set(LIVRAISON_LONGUEURS)
        if inconnus:
            raise ValueError("Unknown shipping fields are not allowed.")

        adresse = {}
        for champ, longueur in LIVRAISON_LONGUEURS.items():
            valeur = brut.get(champ)
            if valeur is None or valeur == "":
                adresse[champ] = ""
                continue
            if not isinstance(valeur, str):
                raise ValueError("Shipping fields must be text.")
            valeur = valeur.strip()
            if len(valeur) > longueur:
                raise ValueError("A shipping field is too long.")
            adresse[champ] = valeur

        if adresse["country_code"]:
            adresse["country_code"] = adresse["country_code"].upper()
            if not re.match(r"^[A-Z]{2}$", adresse["country_code"]):
                raise ValueError("Shipping country code must contain two letters.")
        return adresse

    def _succes(self, commande, rejeu):
        projection = commande._dally_shop_projection()
        projection["replayed"] = rejeu
        return self._json_response(
            {"success": True, "data": {"order": projection}},
            status=200,
            cache_control="no-store",
        )
