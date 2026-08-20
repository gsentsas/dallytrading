{
    "name": "DallyTrading — Boutique",
    "summary": "Catalogue public, commandes, workflow et livraison boutique avec Odoo pour seule source de vérité.",
    "description": """
Socle boutique de DallyTrading.

Next.js reste l'unique vitrine publique. Odoo reste la source de vérité pour les
produits, les prix, les clients et les commandes ; `sale.order` reste l'unique
modèle de commande.

E-commerce Pro ajoute un workflow commercial distinct de l'état natif Vente puis
un sous-système de remise configurable. Le navigateur choisit seulement un code
public de méthode ; Odoo décide les frais, impose l'adresse quand nécessaire et
conserve le suivi logistique. Aucune confirmation Vente, facture ou paiement n'est
déclenché automatiquement par le checkout.
""",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "category": "Sales/DallyTrading",
    "version": "19.0.1.7.0",
    "license": "LGPL-3",
    "depends": ["dally_core", "dally_portal", "product", "sale", "stock", "mail"],
    "data": [
        "security/dally_shop_security.xml",
        "security/ir.model.access.csv",
        "security/dally_shop_order_acl.xml",
        "security/dally_shop_order_rules.xml",
        "data/dally_shop_integration_users.xml",
        "data/dally_shop_pricelist.xml",
        "data/dally_shop_delivery_methods.xml",
        "views/dally_shop_category_views.xml",
        "views/product_template_views.xml",
        "views/dally_shop_delivery_views.xml",
        "views/sale_order_views.xml",
        "views/dally_shop_shipping_management_views.xml",
        "views/res_config_settings_views.xml",
        "views/dally_shop_menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
