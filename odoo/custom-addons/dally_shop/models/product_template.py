# -*- coding: utf-8 -*-
"""
Extension boutique de `product.template`.

## Aucun modèle produit parallèle

Un `dally.shop.product` qui recopierait nom, prix et stock créerait deux vérités
sur le même objet, et la question « lequel des deux a raison » n'aurait pas de
réponse. `product.template` reste donc l'autorité ; ce fichier n'ajoute que ce
qu'Odoo ne sait pas : est-ce publié, où, dans quel ordre, et comment le stock se
comporte à la commande.

## La publication est fermée par défaut

L'audit de la production le rend indispensable : sur les cinq produits existants,
quatre sont des lignes de frais créées par `tk_freight` — *Freight Charges*,
*Policy Charges*, *Route Charges*, *Freight Order* — et le cinquième est un
artefact de test à 1 912 000. Si la publication était ouverte par défaut, la
boutique s'ouvrirait sur la plomberie comptable du fret.

Un produit n'est donc visible que sur décision explicite.

## Le slug est la référence publique

Le navigateur ne manipule jamais l'identifiant de base d'un produit : ni dans
l'URL, ni dans le panier. Un entier séquentiel s'énumère, et il ferait de la
non-publication un simple trou dans une suite — ce qui suffirait à déduire
qu'un produit existe. Le slug est la seule clé qui traverse la frontière.

## Le prix ne traverse jamais dans l'autre sens

Le prix affiché est calculé ici, à partir du tarif boutique. Rien de ce que le
navigateur envoie ne participe à ce calcul, aujourd'hui pour l'affichage et
demain pour la commande.
"""

import base64
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.mimetypes import guess_mimetype

_logger = logging.getLogger(__name__)

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: Slugs réservés par la vitrine.
#:
#: Les fiches produit vivent sous `/boutique/<slug>`, et le site y place aussi des
#: pages fixes — `/boutique/panier` aujourd'hui, la commande demain. Un segment
#: statique gagne toujours contre un segment dynamique dans Next.js : un produit
#: dont le slug serait `panier` aurait une fiche **inaccessible**, et le symptôme
#: serait déroutant — le produit apparaît au catalogue, son lien mène au panier.
#:
#: Le refus est donc ici, au moment où le slug est saisi, et non dans une note de
#: documentation que personne ne relit en nommant un produit.
SLUGS_RESERVES = frozenset({"panier", "commande", "paiement", "confirmation"})

#: Clé de configuration portant le tarif de la boutique.
CLE_TARIF = "dally_shop.pricelist_id"

#: Tailles d'image servies au public, et le champ Odoo derrière chacune.
#:
#: Une énumération fermée, et non une dimension libre passée dans l'URL. Un
#: paramètre `?width=` arbitraire ferait redimensionner à la demande depuis
#: l'extérieur : chaque valeur inédite est un calcul d'image et une entrée de
#: cache, donc une amplification offerte à qui itère de 1 à 4000.
#:
#: `image_1920` reste la source de vérité ; ces deux champs en sont des dérivés
#: stockés qu'Odoo recalcule tout seul quand l'original change.
TAILLES_IMAGE = {
    "card": "image_512",
    "detail": "image_1024",
}
TAILLE_IMAGE_DEFAUT = "card"

#: Types d'image que la boutique accepte de servir.
#:
#: Liste blanche, et l'absence de SVG est délibérée. Un SVG est un document XML
#: qui peut porter du script : servi depuis notre origine, il s'exécuterait dans
#: notre contexte. L'image d'un produit vient d'un champ que le personnel
#: remplit — c'est-à-dire d'une source interne mais non vérifiée — et le même
#: raisonnement que pour la description en `whitespace-pre-line` s'applique ici.
#:
#: Le type est déduit des **octets**, jamais du nom de fichier ni de ce que
#: l'envoyeur a déclaré.
MIMETYPES_IMAGE = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})


def empreintes_image(env, modele, ids):
    """`{id: jeton}` pour les enregistrements portant une `image_1920`.

    Une seule implémentation pour la photo principale du produit et pour les
    photos de galerie : le jeton doit se calculer de la même façon des deux
    côtés, sinon l'un des deux caches se comporterait autrement que l'autre
    sans que rien ne le signale.

    ## Pourquoi les pièces jointes plutôt que le champ

    `image_1920` est un `fields.Image`, donc stocké en pièce jointe et non en
    colonne — vérifié sur la base de production, qui n'a aucune colonne
    `image%` sur `product_template`. Lire le champ pour savoir s'il est rempli
    chargerait les octets de **chaque** produit du catalogue, à chaque
    affichage, pour n'en garder qu'un booléen.

    La table des pièces jointes porte déjà l'empreinte du contenu : une requête,
    aucun octet lu, et l'empreinte est exactement le numéro de version voulu.

    `search` sur `ir.attachment` masque d'ordinaire les pièces jointes de champ
    en ajoutant `res_field = False` au domaine ; il ne le fait pas quand le
    domaine mentionne lui-même `res_field`, ce qui est le cas ici. Comportement
    vérifié dans le source d'Odoo 19, pas supposé.

    `sudo()` : la clé d'intégration n'a pas de droit de lecture sur
    `ir.attachment`, et n'a aucune raison d'en avoir. Le domaine borne la
    lecture au seul champ image d'enregistrements dont l'appelant a déjà établi
    la visibilité.
    """
    if not ids:
        return {}
    pieces = env["ir.attachment"].sudo().search_read(
        [
            ("res_model", "=", modele),
            ("res_field", "=", "image_1920"),
            ("res_id", "in", list(ids)),
        ],
        ["res_id", "checksum", "write_date"],
    )
    empreintes = {}
    for piece in pieces:
        # L'empreinte du contenu quand elle existe ; sinon la date de
        # modification, qui change elle aussi à chaque remplacement d'image. Le
        # second cas n'est pas théorique : une pièce jointe créée par un import
        # peut arriver sans empreinte calculée.
        brut = piece.get("checksum") or str(piece.get("write_date") or "")
        if not brut:
            continue
        empreintes[piece["res_id"]] = brut[:16]
    return empreintes


class ShopPricelistMissing(Exception):
    """Aucun tarif boutique n'est configuré.

    Ce n'est **pas une panne** : c'est l'état d'une boutique qu'on n'a pas encore
    ouverte. La distinction compte jusqu'à l'écran du visiteur — « momentanément
    indisponible » évoque un incident et invite à revenir dans cinq minutes, alors
    que la vérité est « pas encore en vente ». Deux messages, donc deux codes, donc
    deux exceptions.
    """


class ShopPricelistInvalid(Exception):
    """Un tarif est configuré, mais l'enregistrement n'existe plus.

    Traité comme une panne et non comme une boutique fermée, parce que quelqu'un
    a bel et bien pris la décision d'ouvrir : le paramètre porte un identifiant.
    Le silence serait le pire des deux mondes — une boutique qui se présente comme
    « en préparation » alors que sa configuration est cassée ne serait jamais
    réparée.
    """


#: Politiques de stock proposées au MVP.
#:
#: `on_order` — l'article est approvisionné après la commande. C'est le cas
#: normal du négoce : le stock physique n'existe pas encore au moment de l'achat.
#: `managed` — le stock est suivi dans Odoo et affiché comme tel.
#:
#: Aucune des deux ne bloque une commande au MVP : la politique décrit ce que le
#: client lit, pas une règle d'arbitrage. Un blocage sur stock demanderait des
#: réservations, et ce n'est pas ce cycle.
POLITIQUES_STOCK = [
    ("on_order", "Sur commande"),
    ("managed", "Stock suivi"),
]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    dally_published = fields.Boolean(
        string="Publié sur la boutique",
        default=False,
        index=True,
        copy=False,
        help="Fermé par défaut. Un produit n'apparaît sur la boutique que sur "
             "décision explicite — la base contient des articles techniques qui "
             "n'ont rien à y faire.",
    )
    dally_shop_slug = fields.Char(
        string="Slug boutique",
        index=True,
        copy=False,
        help="Référence publique du produit : elle sert d'URL et de clé de "
             "panier. L'identifiant de base ne franchit jamais la frontière.",
    )
    dally_shop_sequence = fields.Integer(
        string="Ordre d'affichage",
        default=100,
        help="Croissant. À égalité, le nom tranche, pour que deux visites "
             "successives donnent le même ordre.",
    )
    dally_shop_category_id = fields.Many2one(
        comodel_name="dally.shop.category",
        string="Catégorie boutique",
        ondelete="restrict",
        index=True,
        help="Taxonomie publique, distincte de la catégorie comptable "
             "`categ_id` qui décide des comptes de stock et de résultat.",
    )
    dally_stock_policy = fields.Selection(
        selection=POLITIQUES_STOCK,
        string="Politique de stock",
        default="on_order",
        required=True,
    )
    dally_shop_image_ids = fields.One2many(
        comodel_name="dally.shop.product.image",
        inverse_name="product_tmpl_id",
        string="Galerie boutique",
        copy=True,
        help="Photos supplémentaires. La photo principale reste le champ image "
             "natif du produit : la galerie ne la recopie pas, la vitrine la "
             "place d'office en première position.",
    )
    dally_shop_summary = fields.Text(
        string="Résumé boutique",
        translate=True,
        help="Texte court affiché sur la vitrine. Séparé de la description de "
             "vente, qui sert les documents commerciaux.",
    )

    _shop_slug_unique = models.Constraint(
        "UNIQUE (dally_shop_slug)",
        "Ce slug boutique est déjà utilisé par un autre produit.",
    )

    @api.constrains("dally_shop_slug")
    def _check_shop_slug(self):
        for produit in self:
            if not produit.dally_shop_slug:
                continue
            if not _SLUG.match(produit.dally_shop_slug):
                raise ValidationError(
                    _("Le slug « %s » doit être en minuscules, sans accent, "
                      "avec des tirets pour séparer les mots.")
                    % produit.dally_shop_slug
                )
            if produit.dally_shop_slug in SLUGS_RESERVES:
                raise ValidationError(
                    _("Le slug « %s » est réservé par la boutique : une page du "
                      "site porte déjà cette adresse, et la fiche du produit "
                      "serait inaccessible.") % produit.dally_shop_slug
                )

    @api.constrains("dally_published", "dally_shop_slug")
    def _check_published_has_slug(self):
        """Publier sans slug produirait une fiche sans URL.

        Le contrôle est ici plutôt que dans l'interface : la publication passe
        aussi par l'import de données et par l'ORM.
        """
        for produit in self:
            if produit.dally_published and not produit.dally_shop_slug:
                raise ValidationError(
                    _("« %s » ne peut pas être publié sans slug boutique : le "
                      "slug est son adresse publique.") % produit.display_name
                )

    # ------------------------------------------------------------------
    # Tarif
    # ------------------------------------------------------------------

    @api.model
    def _dally_shop_pricelist(self):
        """Le tarif de la boutique, ou une erreur.

        Volontairement fermé : sans tarif configuré, la boutique **ne sert pas**
        de prix plutôt que de retomber sur `list_price`. Le prix de liste d'un
        produit n'a pas été décidé pour la vente publique, et le publier par
        défaut, c'est afficher un montant que personne n'a validé — dont le
        1 912 000 de l'artefact de test.

        La même règle que pour le mode de transport du fret : quand la donnée
        manque, on refuse au lieu de deviner.

        ## Deux échecs, et pourquoi ils ne se confondent pas

        `ShopPricelistMissing` — le paramètre est vide. La boutique n'a pas été
        ouverte, et le visiteur doit lire « en préparation ».

        `ShopPricelistInvalid` — le paramètre porte un identifiant, mais
        l'enregistrement a disparu, ou la valeur n'est pas un entier. Quelqu'un a
        décidé d'ouvrir et la configuration est cassée : c'est une panne, elle doit
        se voir comme telle.

        Les deux étaient auparavant un seul `UserError`, et la boutique fermée
        s'annonçait « momentanément indisponible ».
        """
        brut = (self.env["ir.config_parameter"].sudo().get_param(CLE_TARIF) or "").strip()
        if not brut:
            raise ShopPricelistMissing(CLE_TARIF)
        try:
            identifiant = int(brut)
        except (TypeError, ValueError):
            # Une valeur non numérique est une configuration cassée, pas une
            # absence de configuration.
            raise ShopPricelistInvalid(CLE_TARIF) from None
        tarif = self.env["product.pricelist"].sudo().browse(identifiant).exists()
        if not tarif:
            raise ShopPricelistInvalid(CLE_TARIF)
        return tarif

    def _dally_shop_price(self, tarif=None):
        """Prix unitaire public **explicitement décidé**, par produit.

        Retourne un dictionnaire ne contenant que les produits dont le prix vient
        d'une règle du tarif. Les autres en sont **absents** — ils ne sont pas
        vendables, et l'appelant doit les écarter plutôt que leur inventer un prix.

        ## Le repli silencieux d'Odoo, mesuré

        `_get_product_price` rend toujours un montant. Sur un tarif sans règle
        applicable, ce montant est le `list_price` du produit. Mesuré : tarif sans
        règle → 777 777, c'est-à-dire exactement le prix de liste, avec
        `rule_id` vide.

        C'est le repli que la boutique refuse depuis le premier jour, et il ne
        suffisait pas de choisir un tarif pour s'en protéger : il faut vérifier
        qu'une **règle** s'est appliquée. `_get_product_price_rule` rend le couple
        `(prix, règle)`, et l'absence de règle est le signal.

        Un prix de liste n'a pas été décidé pour la vente publique. Le servir,
        c'est afficher un montant que personne n'a validé — dont le 1 912 000 de
        l'artefact de test présent en production.
        """
        tarif = tarif or self._dally_shop_pricelist()
        prix = {}
        sans_regle = []
        for produit in self:
            montant, regle = tarif._get_product_price_rule(produit, 1.0)
            if not regle:
                sans_regle.append(produit.dally_shop_slug or produit.display_name)
                continue
            prix[produit.id] = montant
        if sans_regle:
            _logger.warning(
                "Boutique : %s produit(s) publie(s) sans regle de tarif, donc "
                "ecarte(s) du catalogue : %s. Ajouter une regle au tarif %s pour "
                "les mettre en vente.",
                len(sans_regle), ", ".join(sorted(sans_regle)), tarif.display_name,
            )
        return prix

    # ------------------------------------------------------------------
    # Projection publique
    # ------------------------------------------------------------------

    def _dally_shop_projection(self, tarif=None, detail=False):
        """Ce qu'un visiteur anonyme peut voir d'un produit, et rien de plus.

        Liste blanche explicite. Un produit Odoo porte le coût d'achat, la marge,
        les fournisseurs, les notes internes et la comptabilité analytique : une
        projection par exclusion laisserait passer le prochain champ ajouté par
        un module tiers. Ici, un champ non nommé n'existe pas pour le public.

        Le stock n'est jamais un nombre. « 12 en stock » renseigne un concurrent
        sur les volumes d'achat ; la disponibilité suffit au client.

        ## L'image n'est pas dans la projection

        `imageVersion` porte un jeton court, jamais les octets. Une image de
        produit pèse des centaines de kilooctets ; en base64 dans le JSON du
        catalogue, dix produits feraient plusieurs mégaoctets **retransmis à
        chaque affichage de page**, sans jamais être mis en cache par le
        navigateur puisqu'ils voyageraient dans un document dynamique.

        Le jeton est l'empreinte du contenu de l'image. Il sert d'adresse : tant
        que l'image ne change pas il ne change pas, donc le navigateur garde la
        sienne ; quand elle change, l'adresse change et le cache se renouvelle
        sans que personne ait à le vider. `None` signifie « aucune image », et
        c'est le signal qui fait afficher le substitut plutôt qu'une requête
        vouée au 404.
        """
        tarif = tarif or self._dally_shop_pricelist()
        prix = self._dally_shop_price(tarif)
        devise = tarif.currency_id
        versions = self._dally_shop_image_versions()

        projections = []
        for produit in self:
            # Absent du dictionnaire = aucune règle de tarif ne s'applique. Le
            # produit est publié mais son prix n'a pas été décidé : il ne sort pas.
            if produit.id not in prix:
                continue
            projection = {
                "reference": produit.dally_shop_slug,
                "name": produit.display_name,
                "summary": produit.dally_shop_summary or None,
                "price": prix[produit.id],
                "currency": devise.name,
                "stockPolicy": produit.dally_stock_policy,
                "stockPolicyLabel": dict(POLITIQUES_STOCK).get(
                    produit.dally_stock_policy, ""
                ),
                "availability": produit._dally_shop_availability(),
                "imageVersion": versions.get(produit.id),
                "category": (
                    {
                        "reference": produit.dally_shop_category_id.slug,
                        "name": produit.dally_shop_category_id.name,
                    }
                    if produit.dally_shop_category_id.published
                    else None
                ),
            }
            if detail:
                projection["description"] = produit.description_sale or None
                projection["unit"] = produit.uom_id.name
                # La galerie n'est **que** dans le détail. Sur le catalogue,
                # trente vignettes de galerie voyageraient dans la charge de la
                # page pour n'afficher qu'une image par tuile ; l'absence du
                # champ en liste rend cette erreur impossible plutôt que
                # simplement déconseillée.
                projection["gallery"] = produit._dally_shop_gallery()
            projections.append(projection)
        return projections

    # ------------------------------------------------------------------
    # Image
    # ------------------------------------------------------------------

    def _dally_shop_image_versions(self):
        """`{id du produit: jeton}` pour ceux qui portent une image.

        ## Pourquoi passer par les pièces jointes plutôt que par le champ

        `image_1920` est un champ `fields.Image`, donc stocké en pièce jointe et
        non en colonne — vérifié sur la base de production, qui n'a aucune
        colonne `image%` sur `product_template`. Lire le champ pour savoir s'il
        est rempli chargerait donc les octets de **chaque** produit du catalogue,
        à chaque affichage, pour n'en garder qu'un booléen.

        La table des pièces jointes porte déjà l'empreinte du contenu. Une seule
        requête, aucun octet d'image lu, et l'empreinte est exactement ce dont on
        a besoin comme numéro de version.

        `search` sur `ir.attachment` masque d'ordinaire les pièces jointes de
        champ en ajoutant `res_field = False` au domaine ; il ne le fait pas
        quand le domaine mentionne lui-même `res_field`, ce qui est le cas ici.
        Le comportement est vérifié dans le source d'Odoo 19, pas supposé.

        `sudo()` : la clé d'intégration n'a pas de droit de lecture sur
        `ir.attachment`, et n'a aucune raison d'en avoir. Le domaine restreint la
        lecture au seul champ image de produits dont l'appelant a déjà établi la
        publication.
        """
        return empreintes_image(self.env, "product.template", self.ids)

    def _dally_shop_gallery(self):
        """Les photos supplémentaires du produit, ordonnées, sans octets.

        Chaque entrée porte un `reference` — le jeton opaque de la photo — et sa
        `sequence`. La photo principale n'y figure pas : elle a son propre jeton
        dans `imageVersion`, et la fiche publique la place en première position
        sans qu'une ligne de galerie ait à exister pour elle. Recopier l'image
        principale dans la galerie créerait deux vérités sur le même objet.

        Une photo dont l'empreinte est introuvable est **omise** plutôt que
        servie avec un jeton vide : sans jeton il n'y a pas d'URL, et une
        vignette morte vaut moins qu'une vignette absente.
        """
        self.ensure_one()
        photos = self.sudo().dally_shop_image_ids
        empreintes = empreintes_image(
            self.env, "dally.shop.product.image", photos.ids
        )
        return [
            {"reference": empreintes[photo.id], "sequence": photo.sequence}
            for photo in photos
            if photo.id in empreintes
        ]

    def _dally_shop_photo_galerie(self, jeton):
        """La photo de galerie **de ce produit** portant ce jeton, ou vide.

        La recherche est bornée aux photos du produit déjà autorisé. C'est ce qui
        rend inutile de faire confiance au navigateur : le jeton n'est pas un
        identifiant qu'on irait chercher dans la base, c'est une valeur qu'on
        compare à celles qu'on vient de calculer pour ce produit-là. Un jeton
        valide pour un autre produit ne trouve rien ici, et un identifiant de
        base n'a aucune chance de ressembler à une empreinte.
        """
        self.ensure_one()
        if not jeton or not isinstance(jeton, str):
            return self.env["dally.shop.product.image"]
        photos = self.sudo().dally_shop_image_ids
        empreintes = empreintes_image(
            self.env, "dally.shop.product.image", photos.ids
        )
        for photo in photos:
            if empreintes.get(photo.id) == jeton:
                return photo
        return self.env["dally.shop.product.image"]

    @api.model
    def _dally_shop_image(self, reference, taille=None, jeton_galerie=None):
        """Les octets de l'image d'un produit publié, ou `None`.

        `None` recouvre volontairement quatre situations : référence inconnue,
        produit non publié, produit publié sans image, image d'un type refusé.
        L'appelant répond 404 dans les quatre cas, et ne peut donc pas les
        distinguer — c'est la même règle que la fiche produit, pour la même
        raison : distinguer « pas d'image » de « pas publié » suffirait à
        énumérer un catalogue en préparation.

        La visibilité passe par `_dally_shop_find`, et non par un domaine
        recopié. Un second chemin de décision finirait par diverger du premier :
        le jour où un produit devient invisible au catalogue, son image doit
        disparaître au même instant, sans qu'on ait à y penser.

        Le type est déduit des octets. Ni le nom du fichier, ni le `mimetype`
        déclaré sur la pièce jointe ne sont consultés : tous deux viennent de
        l'envoyeur, et servir un `text/html` depuis notre origine parce qu'un
        fichier s'appelait `photo.png` serait une faille de script.

        ## La galerie passe par le même chemin

        `jeton_galerie` désigne une photo supplémentaire. Le produit est
        d'abord résolu et autorisé exactement comme pour la photo principale ;
        la galerie n'ouvre donc aucune seconde porte. Un jeton inconnu, ou
        valide mais appartenant à un autre produit, rend `None` — donc le même
        404 que tout le reste.
        """
        produit = self._dally_shop_find(reference)
        if not produit:
            return None

        champ = TAILLES_IMAGE.get(taille or "", TAILLES_IMAGE[TAILLE_IMAGE_DEFAUT])
        if jeton_galerie:
            porteur = produit._dally_shop_photo_galerie(jeton_galerie)
            if not porteur:
                return None
        else:
            porteur = produit
        brut = porteur.sudo()[champ]
        if not brut:
            return None

        try:
            octets = base64.b64decode(brut)
        except (ValueError, TypeError):
            _logger.warning(
                "Boutique : l'image du produit %s n'est pas decodable.", reference
            )
            return None

        mimetype = guess_mimetype(octets, default="")
        if mimetype not in MIMETYPES_IMAGE:
            _logger.warning(
                "Boutique : image du produit %s refusee, type %r hors liste "
                "blanche. Remplacer par un PNG, JPEG, WebP ou GIF.",
                reference, mimetype,
            )
            return None
        return octets, mimetype

    def _dally_shop_availability(self):
        """Disponibilité qualitative, jamais une quantité.

        En `on_order`, la question du stock ne se pose pas : l'article est
        approvisionné après la commande, et afficher « 0 en stock » serait faux
        autant que dissuasif.
        """
        self.ensure_one()
        if self.dally_stock_policy == "on_order":
            return "on_order"
        return "in_stock" if self.qty_available > 0 else "out_of_stock"

    # ------------------------------------------------------------------
    # Lecture publique
    # ------------------------------------------------------------------

    @api.model
    def _dally_shop_domain(self):
        """Le domaine unique par lequel passe toute lecture publique.

        Un seul endroit à corriger, et un seul à vérifier. Les trois conditions
        comptent, et chacune ferme un cas différent :

        * `dally_published` — la décision d'exposer le produit ;
        * `active` — un produit archivé est retiré de la circulation, et la
          publication seule le laisserait en vitrine ;
        * `sale_ok` — un produit peut rester publié pendant qu'on suspend sa
          vente. Il était auparavant vérifié **seulement** à la commande : le
          catalogue pouvait donc lister un article que la commande refuserait
          ensuite, ce qui est la pire séquence — le client choisit, puis on lui
          dit non.
        """
        return [
            ("dally_published", "=", True),
            ("active", "=", True),
            ("sale_ok", "=", True),
        ]

    @api.model
    def _dally_shop_search(self, categorie_slug=None, limite=None, decalage=0):
        """Le catalogue publiable, trié de façon stable."""
        domaine = self._dally_shop_domain()
        if categorie_slug:
            domaine.append(("dally_shop_category_id.slug", "=", categorie_slug))
        return self.sudo().search(
            domaine,
            order="dally_shop_sequence asc, name asc, id asc",
            limit=limite,
            offset=decalage,
        )

    @api.model
    def _dally_shop_resolve_lines(self, demandes):
        """Revalide un panier au moment de commander, et refuse s'il a bougé.

        `demandes` est une liste de couples `(référence, quantité)`. Le retour est
        une liste de couples `(product.template, quantité)` dans le même ordre.

        ## Pourquoi une seconde lecture

        Le panier vit dans un cookie qui peut avoir trente jours. Entre la mise au
        panier et la commande, un produit peut avoir été dépublié, archivé, ou
        rendu non vendable. Se fier à ce qui a été validé à l'ajout, c'est
        commander sur un état du monde périmé.

        La lecture porte sur les trois conditions à la fois. `sale_ok` s'ajoute à
        la publication parce que ce sont deux décisions différentes : un produit
        peut rester en vitrine pendant qu'on suspend sa vente, et l'oubli
        produirait une commande qu'Odoo refuserait plus loin, à un endroit où le
        message n'a plus de rapport avec la cause.

        ## Le refus est global

        Une seule référence en défaut fait échouer la commande entière. Retirer
        silencieusement la ligne fautive serait plus doux et pire : le client
        validerait un total qu'il n'a pas vu, pour un contenu qu'il n'a pas
        choisi. Il doit revoir son panier.
        """
        if not demandes:
            raise ValueError("empty_cart")

        references = [reference for reference, _q in demandes]
        publies = self.sudo().search(
            self._dally_shop_domain() + [("dally_shop_slug", "in", references)]
        )
        par_reference = {produit.dally_shop_slug: produit for produit in publies}
        manquantes = [r for r in references if r not in par_reference]

        if manquantes:
            # Le domaine public porte les trois conditions ensemble : le refus
            # rendu au client ne les distingue pas, et c'est voulu. Mais une
            # exploitation a besoin de savoir laquelle a joué — « vente suspendue »
            # et « dépublié » n'appellent pas le même geste. On le relit donc ici,
            # dans le journal interne uniquement.
            for produit in self.sudo().with_context(active_test=False).search(
                [("dally_shop_slug", "in", manquantes)]
            ):
                _logger.info(
                    "Commande boutique refusee : %s (publie=%s actif=%s vendable=%s)",
                    produit.dally_shop_slug, produit.dally_published,
                    produit.active, produit.sale_ok,
                )
            raise ValueError("unavailable_products:%s" % ",".join(sorted(manquantes)))

        # Un produit sans règle de tarif n'est pas commandable. Le contrôle est
        # ici et non seulement à l'affichage : un panier de trente jours peut
        # porter une référence dont la règle de tarif a été retirée depuis.
        tarifes = publies._dally_shop_price()
        sans_prix = [
            slug for slug, produit in par_reference.items() if produit.id not in tarifes
        ]
        if sans_prix:
            _logger.warning(
                "Commande boutique refusee : aucune regle de tarif pour %s",
                ", ".join(sorted(sans_prix)),
            )
            raise ValueError("unavailable_products:%s" % ",".join(sorted(sans_prix)))

        lignes = []
        for reference, quantite in demandes:
            produit = par_reference[reference]
            if not produit.product_variant_id:
                # Un modèle sans variante ne peut pas figurer sur une ligne de
                # commande. Le cas n'existe pas normalement — Odoo crée toujours
                # une variante — mais un produit dont toutes les variantes sont
                # archivées y ressemble, et l'erreur brute serait incompréhensible.
                raise ValueError("unavailable_products:%s" % reference)
            lignes.append((produit, quantite))
        return lignes

    @api.model
    def _dally_shop_find(self, reference):
        """Le produit publié portant ce slug, ou un ensemble vide.

        Un produit non publié et un slug inventé donnent tous deux un ensemble
        vide : c'est la seule façon de rendre les deux cas indiscernables, et
        c'est le sens de la décision « produit non publié = produit inconnu ».
        Aucun appelant ne doit pouvoir distinguer les deux, donc aucun ne reçoit
        de quoi le faire.
        """
        if not reference or not isinstance(reference, str):
            return self.browse()
        trouve = self.sudo().search(
            self._dally_shop_domain() + [("dally_shop_slug", "=", reference)],
            limit=1,
        )
        if not trouve:
            return trouve
        # Publié, actif, vendable — mais sans prix décidé. La fiche doit répondre
        # comme pour un produit inconnu : sinon elle s'ouvrirait sur un montant
        # que personne n'a validé, ou sur une page en erreur.
        if trouve.id not in trouve._dally_shop_price():
            return self.browse()
        return trouve
