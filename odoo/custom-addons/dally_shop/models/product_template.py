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

import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

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
        """
        brut = self.env["ir.config_parameter"].sudo().get_param(CLE_TARIF)
        tarif = self.env["product.pricelist"].browse(int(brut)).exists() if brut else None
        if not tarif:
            raise UserError(
                _("La boutique n'a pas de tarif configuré (%s). Aucun prix ne "
                  "sera affiché tant que ce tarif n'est pas défini.") % CLE_TARIF
            )
        return tarif

    def _dally_shop_price(self, tarif=None):
        """Prix unitaire public, calculé par Odoo pour la quantité 1.

        Retourne un dictionnaire par produit, pas une valeur : les appelants
        traitent des listes, et le tarif ne doit être résolu qu'une fois.
        """
        tarif = tarif or self._dally_shop_pricelist()
        return {
            produit.id: tarif._get_product_price(produit, 1.0)
            for produit in self
        }

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
        """
        tarif = tarif or self._dally_shop_pricelist()
        prix = self._dally_shop_price(tarif)
        devise = tarif.currency_id

        projections = []
        for produit in self:
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
            projections.append(projection)
        return projections

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

        Un seul endroit à corriger, et un seul à vérifier. Les deux conditions
        comptent : `active` écarte les produits archivés, que la publication
        laisserait visibles si on ne regardait que `dally_published`.
        """
        return [("dally_published", "=", True), ("active", "=", True)]

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
        # `sale_ok` est filtré après la recherche et non dans le domaine, pour que
        # le message distingue « plus au catalogue » de « vente suspendue » dans
        # les journaux internes. Côté client, les deux donnent le même refus.
        par_reference = {
            produit.dally_shop_slug: produit for produit in publies if produit.sale_ok
        }
        non_vendables = [
            produit.dally_shop_slug for produit in publies if not produit.sale_ok
        ]
        if non_vendables:
            _logger.info(
                "Commande boutique refusee : produits non vendables %s", non_vendables
            )

        manquantes = [r for r in references if r not in par_reference]
        if manquantes:
            raise ValueError("unavailable_products:%s" % ",".join(sorted(manquantes)))

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
        return self.sudo().search(
            self._dally_shop_domain() + [("dally_shop_slug", "=", reference)],
            limit=1,
        )
