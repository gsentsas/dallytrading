# -*- coding: utf-8 -*-
"""
Les photos supplémentaires d'un produit de la boutique.

## Pourquoi ce modèle existe alors qu'Odoo en a un

Odoo 19 porte bien un `product.image` avec `product_tmpl_id`, `image_1920` et
`sequence` — exactement la forme dont on a besoin. Il est **défini dans
`website_sale`**, mesuré sur l'instance :
`/usr/lib/python3/dist-packages/odoo/addons/website_sale/models/product_image.py`.

`website_sale` est désinstallé en production, et ses dépendances déclarées sont
`website`, `sale`, `website_payment`, `website_mail`, `portal_rating`, `digest`,
`delivery`, `html_builder`. L'installer pour obtenir un modèle de galerie
ferait entrer :

* une **boutique en ligne concurrente** — c'est précisément ce que
  `website_sale` est — alors que la vitrine du site est déjà servie par Next.js,
  et après qu'on a dû neutraliser le portail de vente natif pour la même raison ;
* des flux de **paiement web** et de **livraison**, tous deux hors périmètre et
  explicitement écartés ;
* des **routes publiques** supplémentaires à auditer et à neutraliser une à une.

`product.image` porte aussi `video_url` et `embed_code`, ce dernier en
`fields.Html(sanitize=False)` : du HTML non assaini, stocké, sur un objet destiné
à l'affichage public. La boutique refuse le SVG pour cette raison exacte ; hériter
d'un champ qui va plus loin serait incohérent.

Le coût de ce modèle est de quarante lignes. Le coût de l'alternative est un
module de commerce complet installé pour trois champs.

## Ce qu'il ne duplique pas

`product.template.image_1920` reste la **photo principale** et la source de
vérité. Ce modèle ne porte que les photos *supplémentaires* : rien ici ne recopie
l'image principale, et la fiche publique la place en première position sans
qu'aucune ligne de galerie n'ait à exister.
"""

import base64

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.mimetypes import guess_mimetype

from .product_template import MIMETYPES_IMAGE


class DallyShopProductImage(models.Model):
    # `_name` est bien posé : un `_inherit` de mixin sans `_name` créerait un
    # modèle fantôme en Odoo 19 — le piège déjà rencontré sur ce projet.
    _name = "dally.shop.product.image"
    _description = "Photo de galerie boutique"
    _inherit = ["image.mixin"]
    # `sequence` d'abord, `id` pour départager : deux photos de même rang
    # doivent s'afficher dans un ordre stable d'un affichage à l'autre.
    _order = "sequence, id"

    name = fields.Char(
        string="Légende interne",
        required=True,
        help="Sert à s'y retrouver dans le back-office. Ce texte n'est pas "
             "publié : la vitrine n'affiche aucune légende, et un champ qui "
             "sortirait sans avoir été pensé comme public serait une fuite.",
    )
    sequence = fields.Integer(
        string="Ordre",
        default=10,
        index=True,
        help="Croissant. La photo principale du produit passe toujours avant, "
             "quelle que soit cette valeur.",
    )
    product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
        string="Produit",
        required=True,
        ondelete="cascade",
        index=True,
        help="Supprimer le produit supprime ses photos : une photo orpheline "
             "resterait dans le filestore sans que rien ne la désigne.",
    )
    active = fields.Boolean(
        string="Actif",
        default=True,
        help="Retirer une photo de la galerie sans la supprimer. Une photo "
             "inactive n'est plus servie, immédiatement.",
    )
    image_1920 = fields.Image(
        string="Photo",
        required=True,
        help="La galerie n'a pas de ligne sans photo : une entrée vide "
             "produirait une vignette morte sur la fiche publique.",
    )

    @api.constrains("image_1920")
    def _check_image(self):
        """Une photo non vide, et d'un type que la vitrine sait servir.

        ## Le vide

        `required=True` couvre la création ; cette contrainte couvre l'écriture
        qui viderait le champ ensuite.

        ## Le type, refusé ici et pas seulement à la lecture

        Mesuré sur Odoo 19 : `fields.Image` **accepte** un SVG. Il est stocké
        sans broncher. La liste blanche appliquée au moment de servir le
        refuserait — le visiteur n'aurait jamais l'image — mais la personne qui
        l'a déposée verrait sa photo enregistrée dans le back-office et
        introuvable sur le site, sans que rien n'explique pourquoi.

        Le refus est donc aussi à l'écriture, là où quelqu'un peut encore
        corriger. Le type est déduit des **octets**, jamais du nom du fichier :
        `guess_mimetype` rend bien `image/svg+xml` pour un SVG et `text/html`
        pour du HTML, tous deux hors liste.

        La photo principale du produit, elle, n'est pas contrainte ici : c'est
        le champ natif de `product.template`, partagé avec tout Odoo, et y poser
        une règle de boutique bloquerait des produits qui ne sont pas en vente
        en ligne. Elle reste protégée à la lecture, et le refus est journalisé.
        """
        for photo in self:
            if not photo.image_1920:
                raise ValidationError(
                    _("La photo « %s » est vide : une entrée de galerie doit "
                      "porter une image.") % (photo.name or photo.id)
                )
            try:
                octets = base64.b64decode(photo.image_1920)
            except (ValueError, TypeError):
                raise ValidationError(
                    _("La photo « %s » n'est pas lisible.") % photo.name
                ) from None
            mimetype = guess_mimetype(octets, default="")
            if mimetype not in MIMETYPES_IMAGE:
                raise ValidationError(
                    _("La photo « %(nom)s » est de type %(type)s, que la "
                      "boutique ne sert pas. Formats acceptés : PNG, JPEG, "
                      "WebP, GIF. Le SVG est refusé : c'est un document qui "
                      "peut porter du script.",
                      nom=photo.name, type=mimetype or _("inconnu"))
                )
