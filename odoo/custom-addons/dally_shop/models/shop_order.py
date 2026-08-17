# -*- coding: utf-8 -*-
"""
La commande boutique : `sale.order` et rien d'autre.

## Aucun modèle de commande parallèle

`sale.order` est la seule source de vérité. Ce fichier n'ajoute que ce qu'Odoo ne
sait pas dire : que cette commande vient de la boutique, et quelle clé
d'idempotence l'a produite.

L'origine est **structurée** — un booléen et un mode de remise — et non une
chaîne dans `origin`. `origin` est un champ libre que d'autres modules écrivent ;
y chercher « boutique » par sous-chaîne marcherait jusqu'au jour où quelqu'un
nommerait un client « Boutique du Port ».

## Le prix n'est jamais écrit

`sale.order.line.price_unit` est calculé et stocké, avec pour dépendances
`product_id`, `product_uom_id` et `product_uom_qty` (audité :
`sale/models/sale_order_line.py:586`). Créer une ligne **sans** `price_unit` fait
donc calculer Odoo, via `_get_display_price()` et le tarif de la commande.

Ce n'est pas seulement plus propre : c'est la seule façon sûre. Le calcul
commence par `has_manual_price(line)`, qui compare `price_unit` à
`technical_price_unit` et **abandonne** si les deux diffèrent — un prix passé à
la création est traité comme saisi à la main et n'est jamais recalculé. Écrire un
prix, même juste, gèlerait la ligne.

Aucune formule de tarif n'existe donc ni ici ni dans Next.

## Idempotence, et le piège du REPEATABLE READ

Quatre barrières, dont la dernière vient d'une mesure faite au cycle fret :

1. la relecture par `dally_shop_cart_uuid` avant toute création ;
2. l'index unique sur ce champ, évalué par PostgreSQL ;
3. le même dispositif sur le contact invité, par `dally_shop_guest_cart_uuid` ;
4. la conversion de la course perdue en `SerializationFailure`.

La barrière 1 ne suffit pas en concurrence réelle. Odoo force `REPEATABLE READ`
au niveau de la connexion (`odoo/sql_db.py`) : la transaction perdante travaille
sur l'instantané pris à son ouverture et **ne voit pas** la commande que la
gagnante vient de committer. Sa relecture ne trouve rien, elle crée, et l'index
unique la rejette par `UniqueViolation` — qui n'appartient pas à
`PG_CONCURRENCY_EXCEPTIONS_TO_RETRY` et n'est donc **pas** rejouée : l'appelant
recevrait une 500 sur une opération parfaitement légitime.

D'où la barrière 4. `SerializationFailure` est rejouée jusqu'à cinq fois par
Odoo ; la nouvelle transaction ouvre un instantané frais, y trouve la commande de
la gagnante, et rend le même résultat. Aucun rejeu maison, aucune boucle
d'attente : c'est le mécanisme d'Odoo qui travaille.
"""

import logging

from psycopg2.errors import SerializationFailure, UniqueViolation

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

#: Modes de remise proposés au MVP.
#:
#: `pickup` — le client vient chercher. Aucun frais, aucune ambiguïté.
#: `delivery_to_confirm` — livraison souhaitée, tarif **non calculé**.
#:
#: Le second nom est verbeux exprès. Un simple `delivery` laisserait croire qu'un
#: tarif existe quelque part ; il n'en existe aucun, et inventer un montant
#: « à titre indicatif » serait pire que ne rien afficher.
MODES_REMISE = [
    ("pickup", "Retrait sur place"),
    ("delivery_to_confirm", "Livraison — tarif à confirmer"),
]


class PortalAccountExists(Exception):
    """L'adresse fournie appartient à un compte portail : il faut se connecter.

    Une exception dédiée et non un code glissé dans un `UserError` : l'appelant
    doit distinguer ce cas de toutes les autres erreurs métier, et le distinguer
    en comparant un message serait fragile — un message est traduit.
    """


class SaleOrder(models.Model):
    _inherit = "sale.order"

    dally_shop_order = fields.Boolean(
        string="Commande boutique",
        default=False,
        index=True,
        copy=False,
        help="Origine structurée. Un booléen plutôt qu'un texte dans `origin` : "
             "ce dernier est un champ libre, et y chercher « boutique » par "
             "sous-chaîne casserait le jour où un client s'appellerait ainsi.",
    )
    dally_shop_cart_uuid = fields.Char(
        string="Identifiant de panier",
        index=True,
        copy=False,
        help="Clé d'idempotence de la commande. Deux envois portant le même "
             "identifiant produisent une seule commande.",
    )
    dally_shop_delivery_mode = fields.Selection(
        selection=MODES_REMISE,
        string="Mode de remise",
        copy=False,
    )
    dally_shop_guest = fields.Boolean(
        string="Commande invité",
        default=False,
        copy=False,
        help="La commande a été passée sans compte. Le contact rattaché a été "
             "créé pour elle, et n'a jamais été rapproché d'un contact existant "
             "sur la seule égalité d'adresse e-mail.",
    )

    _shop_cart_uuid_unique = models.Constraint(
        "UNIQUE (dally_shop_cart_uuid)",
        "Une commande existe déjà pour cet identifiant de panier.",
    )

    @api.constrains("dally_shop_order", "dally_shop_cart_uuid", "dally_shop_delivery_mode")
    def _check_shop_order_complete(self):
        """Une commande boutique porte sa clé et son mode de remise.

        Le contrôle est ici et non dans le contrôleur : une commande boutique
        sans clé d'idempotence serait invisible à la relecture, donc dupliquable
        au premier rejeu — et la cause serait introuvable.
        """
        for commande in self:
            if not commande.dally_shop_order:
                continue
            if not commande.dally_shop_cart_uuid:
                raise ValidationError(
                    _("Une commande boutique doit porter un identifiant de panier.")
                )
            if not commande.dally_shop_delivery_mode:
                raise ValidationError(
                    _("Une commande boutique doit porter un mode de remise.")
                )

    # ------------------------------------------------------------------
    # Création
    # ------------------------------------------------------------------

    @api.model
    def _dally_shop_find_by_cart(self, cart_uuid):
        """La commande déjà produite pour ce panier, ou un ensemble vide."""
        if not cart_uuid or not isinstance(cart_uuid, str):
            return self.browse()
        return self.sudo().search(
            [("dally_shop_cart_uuid", "=", cart_uuid), ("dally_shop_order", "=", True)],
            limit=1,
        )

    @api.model
    def dally_shop_place_order(self, cart_uuid, partner, lignes, mode_remise, invite=False):
        """Crée la commande boutique, ou rend celle qui existe déjà.

        `lignes` est une liste de couples `(product.template, quantité)` déjà
        revalidés par l'appelant : publiés, actifs, vendables. Cette méthode ne
        revérifie pas la publication — non par confiance, mais parce qu'un second
        contrôle au même endroit donnerait deux vérités sur la même question. Le
        contrôle vit dans `_dally_shop_resolve_lines`, et lui seul.
        """
        existante = self._dally_shop_find_by_cart(cart_uuid)
        if existante:
            # Rejeu séquentiel : deux envois l'un après l'autre, un double clic,
            # une reprise réseau. Rien n'est créé, la même commande est rendue.
            return existante

        try:
            with self.env.cr.savepoint():
                return self._dally_shop_create_order(
                    cart_uuid, partner, lignes, mode_remise, invite
                )
        except UniqueViolation as course_perdue:
            if course_perdue.diag.constraint_name != "sale_order_shop_cart_uuid_unique":
                raise
            # Course réelle. La transaction PostgreSQL est déjà avortée : rien ne
            # peut être rattrapé sur place. La seule sortie correcte est de faire
            # rejouer la requête entière, ce qu'Odoo sait faire pour
            # `SerializationFailure` — cinq tentatives, attente exponentielle. Au
            # tour suivant l'instantané est frais, et la relecture ci-dessus
            # trouve la commande de la gagnante.
            _logger.info(
                "Course de commande boutique perdue sur le panier %s : rejeu demandé.",
                cart_uuid,
            )
            raise SerializationFailure(
                "Concurrent shop checkout for cart %s" % cart_uuid
            ) from course_perdue

    @api.model
    def _dally_shop_create_order(self, cart_uuid, partner, lignes, mode_remise, invite):
        """La création elle-même. Aucun prix, aucune taxe, aucune remise écrite."""
        tarif = self.env["product.template"]._dally_shop_pricelist()

        commande = self.sudo().create({
            "partner_id": partner.id,
            # Le tarif est celui de la boutique, décidé par la configuration —
            # jamais celui que le partenaire porte par défaut, et jamais quelque
            # chose que le navigateur aurait pu suggérer.
            "pricelist_id": tarif.id,
            "dally_shop_order": True,
            "dally_shop_cart_uuid": cart_uuid,
            "dally_shop_delivery_mode": mode_remise,
            "dally_shop_guest": invite,
            # Brouillon. Confirmer produirait des mouvements de stock et une
            # obligation commerciale sur la seule foi d'un formulaire public.
            "state": "draft",
            "order_line": [
                (0, 0, {
                    "product_id": produit.product_variant_id.id,
                    "product_uom_qty": quantite,
                    # Ni `price_unit`, ni `discount`, ni `tax_ids`. Les trois sont
                    # calculés et stockés ; les écrire ici ferait traiter le prix
                    # comme saisi à la main, et il ne serait plus jamais recalculé.
                })
                for produit, quantite in lignes
            ],
        })

        # Recalcul explicite juste avant de rendre la commande.
        #
        # Les lignes ont déjà été tarifées à la création par le champ calculé.
        # Ce second passage n'est pas une redondance : `_recompute_prices` remet
        # la remise à zéro puis la recalcule depuis la règle de tarif, et il
        # s'exécute sous `force_price_recomputation`, donc sans l'échappatoire
        # « prix saisi à la main ». C'est le point unique où l'on peut affirmer
        # que le montant rendu au client vient d'Odoo et de maintenant.
        commande._recompute_prices()

        _logger.info(
            "Commande boutique %s creee pour le panier %s (%s lignes, invite=%s).",
            commande.name, cart_uuid, len(lignes), invite,
        )
        return commande

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def _dally_shop_projection(self):
        """Ce que le client peut voir de sa commande.

        Liste blanche explicite, comme pour le catalogue. Une `sale.order` porte
        la marge, le vendeur, les conditions de paiement, la position fiscale et
        l'historique de messagerie ; une projection par exclusion laisserait
        passer le prochain champ ajouté par un module tiers.

        `name` est la référence client-visible d'Odoo (`S00042`) : ce n'est pas un
        identifiant de base, elle est déjà imprimée sur les documents commerciaux,
        et le client en a besoin pour parler de sa commande.
        """
        self.ensure_one()
        return {
            "reference": self.name,
            "status": self.state,
            "deliveryMode": self.dally_shop_delivery_mode,
            "deliveryModeLabel": dict(MODES_REMISE).get(
                self.dally_shop_delivery_mode, ""
            ),
            "currency": self.currency_id.name,
            "amountUntaxed": self.amount_untaxed,
            "amountTax": self.amount_tax,
            "amountTotal": self.amount_total,
            "lines": [
                {
                    "reference": ligne.product_id.product_tmpl_id.dally_shop_slug,
                    "name": ligne.product_id.product_tmpl_id.display_name,
                    "quantity": ligne.product_uom_qty,
                    "unitPrice": ligne.price_unit,
                    "subtotal": ligne.price_subtotal,
                }
                for ligne in self.order_line
            ],
        }


class ResPartner(models.Model):
    _inherit = "res.partner"

    dally_shop_guest_cart_uuid = fields.Char(
        string="Panier invité d'origine",
        index=True,
        copy=False,
        help="Panier pour lequel ce contact invité a été créé. Unique : c'est ce "
             "qui empêche un rejeu ou une course de produire deux contacts pour "
             "la même commande.",
    )

    _shop_guest_cart_uuid_unique = models.Constraint(
        "UNIQUE (dally_shop_guest_cart_uuid)",
        "Un contact invité existe déjà pour cet identifiant de panier.",
    )

    @api.model
    def _dally_shop_guest_for_cart(self, cart_uuid):
        """Le contact invité déjà créé pour ce panier, ou un ensemble vide."""
        if not cart_uuid or not isinstance(cart_uuid, str):
            return self.browse()
        return self.sudo().search(
            [("dally_shop_guest_cart_uuid", "=", cart_uuid)], limit=1
        )

    @api.model
    def _dally_shop_has_portal_account(self, email):
        """Cette adresse appartient-elle à un compte portail existant ?

        Le contrôle porte sur l'existence d'un `res.users`, pas sur celle d'un
        contact. La distinction est le cœur de la règle : un contact créé par le
        personnel pour un devis n'est pas un compte, et rattacher une commande
        invité à ce contact sur la seule égalité d'adresse serait une usurpation
        — n'importe qui connaissant l'adresse d'un client obtiendrait ses
        commandes.

        Un compte portail, lui, peut se connecter. On lui demande donc de le
        faire, ce qui est la seule façon de prouver que c'est bien lui.
        """
        if not email:
            return False
        # `active_test=False` : un compte désactivé reste un compte. L'ignorer
        # laisserait créer une commande invité sur l'adresse d'un client dont
        # l'accès a été suspendu, ce qui est exactement le cas où il faut
        # s'arrêter et parler à un humain.
        return bool(
            self.env["res.users"].sudo().with_context(active_test=False).search_count(
                [("login", "=ilike", email)]
            )
        )

    @api.model
    def _dally_shop_create_guest(self, cart_uuid, identite):
        """Crée le contact d'une commande invité, ou rend celui du même panier.

        Jamais de rapprochement par adresse e-mail. Un contact portant la même
        adresse peut être n'importe qui : un homonyme, une adresse de service
        partagée, une saisie du personnel. Le rattachement automatique
        transformerait la connaissance d'une adresse en accès à un dossier.
        """
        existant = self._dally_shop_guest_for_cart(cart_uuid)
        if existant:
            return existant

        if self._dally_shop_has_portal_account(identite.get("email")):
            # Refus explicite, remonté à l'appelant qui demandera la connexion.
            raise PortalAccountExists(identite.get("email"))

        valeurs = self._dally_shop_guest_values(cart_uuid, identite)

        # Le même piège que pour la commande, et il a fallu le mesurer pour le
        # voir : sous dix requêtes HTTP simultanées, ce `create` heurtait
        # `res_partner_shop_guest_cart_uuid_unique`. Le contact était bien unique
        # — l'invariant tenait — mais trois appelants recevaient 500 et six 422,
        # selon le moment où PostgreSQL évaluait la contrainte.
        #
        # Le point de bascule est le flush. Dans un savepoint explicitement
        # flushé, la violation sort toujours sous la même forme, `UniqueViolation`,
        # au lieu d'apparaître tantôt brute tantôt traduite par Odoo en
        # `ValidationError`. Un seul cas à traiter, donc, et non deux.
        #
        # Relire après le rollback du savepoint ne servirait à rien : sous
        # `REPEATABLE READ`, l'instantané ne contient pas la ligne que la gagnante
        # vient de committer. La seule sortie correcte reste de faire rejouer la
        # requête entière.
        try:
            with self.env.cr.savepoint():
                return self.sudo().create(valeurs)
        except UniqueViolation as course_perdue:
            if course_perdue.diag.constraint_name != "res_partner_shop_guest_cart_uuid_unique":
                # Une autre contrainte : ce n'est pas une course, et la masquer
                # en conflit de sérialisation ferait rejouer cinq fois une erreur
                # qui ne peut pas se résoudre.
                raise
            _logger.info(
                "Course de contact invite perdue sur le panier %s : rejeu demande.",
                cart_uuid,
            )
            raise SerializationFailure(
                "Concurrent guest contact for cart %s" % cart_uuid
            ) from course_perdue

    @api.model
    def _dally_shop_guest_values(self, cart_uuid, identite):
        """Les valeurs du contact invité, liste blanche explicite."""
        valeurs = {
            "name": identite["name"],
            "email": identite["email"],
            "phone": identite.get("phone") or False,
            "street": identite.get("street") or False,
            "city": identite.get("city") or False,
            "zip": identite.get("zip") or False,
            "dally_shop_guest_cart_uuid": cart_uuid,
            # Ni `user_ids`, ni groupe portail : un contact invité n'est pas un
            # compte. Lui en donner un ouvrirait un accès que personne n'a
            # demandé et que rien n'a vérifié.
        }
        if identite.get("country_code"):
            pays = self.env["res.country"].search(
                [("code", "=", identite["country_code"].upper())], limit=1
            )
            if pays:
                valeurs["country_id"] = pays.id
        return valeurs
