# -*- coding: utf-8 -*-
"""
Taxonomie publique de la boutique.

## Pourquoi pas `product.category`

L'audit de la production a tranché : les trois `product.category` existantes sont
celles qu'Odoo installe par défaut — *Goods*, *Expenses*, *Services* — et **aucun
produit n'y est rattaché**. Elles servent la classification comptable : c'est
`categ_id` qui décide des comptes de stock et de résultat.

Les détourner pour ranger la vitrine ferait dépendre la comptabilité de
l'arborescence marketing. Le jour où quelqu'un renomme une catégorie pour le
référencement, il déplace des écritures.

D'où une taxonomie séparée, qui n'a qu'un travail : dire où un produit s'affiche.

## Le slug est la clé publique

L'URL d'une catégorie ne doit pas exposer un identifiant de base : un entier
invite à énumérer. Le slug est donc obligatoire, unique, et borné à un alphabet
sûr — il finit dans une URL et dans du HTML.
"""

import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class DallyShopCategory(models.Model):
    _name = "dally.shop.category"
    _description = "DallyTrading Shop Category"
    _order = "sequence, name"
    _parent_store = True

    name = fields.Char(string="Nom", required=True, translate=True)
    slug = fields.Char(
        string="Slug",
        required=True,
        index=True,
        help="Identifiant public, utilisé dans l'URL. Jamais l'identifiant de "
             "base : un entier dans une URL invite à énumérer le catalogue.",
    )
    sequence = fields.Integer(string="Ordre", default=10)
    active = fields.Boolean(default=True)

    parent_id = fields.Many2one(
        comodel_name="dally.shop.category",
        string="Catégorie parente",
        ondelete="restrict",
        index=True,
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        comodel_name="dally.shop.category",
        inverse_name="parent_id",
        string="Sous-catégories",
    )

    published = fields.Boolean(
        string="Publiée",
        default=False,
        help="Fermé par défaut, comme la publication d'un produit : une "
             "catégorie n'apparaît que sur décision explicite.",
    )

    product_count = fields.Integer(
        string="Produits publiés", compute="_compute_product_count"
    )

    _slug_unique = models.Constraint(
        "UNIQUE (slug)",
        "Ce slug de catégorie est déjà utilisé.",
    )

    def _compute_product_count(self):
        """Compte les produits publiés de chaque catégorie, en une requête.

        Un regroupement plutôt qu'une boucle : une vitrine de quelques centaines
        de références produirait autant de requêtes, et ce compteur s'affiche sur
        chaque tuile de catégorie.

        `_read_group` et non `read_group` : ce dernier est déprécié depuis 19.0
        (`odoo/orm/models.py:2747`) et émet un avertissement à chaque appel.
        """
        groupes = self.env["product.template"].sudo()._read_group(
            [("dally_shop_category_id", "in", self.ids), ("dally_published", "=", True)],
            groupby=["dally_shop_category_id"],
            aggregates=["__count"],
        )
        par_categorie = {
            categorie.id: nombre for categorie, nombre in groupes if categorie
        }
        for categorie in self:
            categorie.product_count = par_categorie.get(categorie.id, 0)

    @api.constrains("slug")
    def _check_slug(self):
        for categorie in self:
            if not _SLUG.match(categorie.slug or ""):
                raise ValidationError(
                    _("Le slug « %s » doit être en minuscules, sans accent, "
                      "avec des tirets pour séparer les mots.") % categorie.slug
                )

    @api.constrains("parent_id")
    def _check_hierarchy(self):
        if self._has_cycle():
            raise ValidationError(_("Une catégorie ne peut pas se contenir."))
