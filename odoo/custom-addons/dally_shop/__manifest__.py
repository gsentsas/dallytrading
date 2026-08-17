{
    "name": "DallyTrading — Boutique",
    "summary": "Catalogue public et panier, avec Odoo pour seule source de vérité.",
    "description": """
Socle boutique de DallyTrading.

## Pourquoi `website_sale` n'est pas installé

Le module e-commerce d'Odoo apporterait sa propre boutique : routes publiques,
gabarits, panier en session Odoo. Le frontend de DallyTrading est Next.js — il y
aurait donc deux boutiques, dont une à neutraliser route par route. C'est
exactement le travail qu'a coûté `tk_freight`, et il n'y a aucune raison de le
refaire volontairement.

Le socle nécessaire est déjà là sans lui : `sale`, `product`, `stock`, `account`.

## Ce que ce module ajoute, et rien de plus

* la **publication** d'un produit, fermée par défaut ;
* une **taxonomie publique** distincte de `product.category` ;
* une **politique de stock** par produit ;
* la **projection** de tout cela vers le catalogue public.

Aucun modèle de produit parallèle : `product.template` et `product.product`
restent l'autorité sur le nom, le prix et le stock.
""",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "category": "Sales/DallyTrading",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["dally_core", "dally_portal", "product", "sale", "stock"],
    "data": [
        "security/ir.model.access.csv",
        "views/dally_shop_category_views.xml",
        "views/product_template_views.xml",
        "views/res_config_settings_views.xml",
        "views/dally_shop_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
