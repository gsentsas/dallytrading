# E-commerce

La boutique DallyTrading utilise **Odoo comme source de vérité commerciale** et **Next.js comme unique vitrine publique**.

## Principes

1. Pas de `website_sale` comme seconde vitrine publique.
2. Pas de modèle de commande parallèle : `sale.order` reste l'autorité.
3. Aucun prix fourni par le navigateur.
4. Odoo calcule prix, taxes, frais et totaux.
5. Idempotence avant tout effet métier.
6. Workflow DallyTrading séparé de `sale.order.state`.
7. Projections client par liste blanche.
8. Notifications asynchrones.
9. Livraison et adresse sont figées sur la commande selon le workflow métier.
10. La confirmation native de la vente doit rester une action métier explicitement autorisée.

## Architecture

```text
Client
  │
  ▼
Next.js boutique
  │ panier / checkout
  ▼
API DallyTrading
  │
  ▼
Odoo — dally_shop
  │
  └── sale.order / produits / pricelist / livraison
```

## Catalogue

La publication produit est fermée par défaut. Le catalogue public ne doit exposer que les produits explicitement publiés et les catégories prévues pour le site.

Les prix viennent d'une pricelist Odoo ; le navigateur ne soumet pas de montant à faire confiance.

## Checkout

Le checkout peut être invité ou connecté, mais il doit rester idempotent sur l'identité du panier.

Une commande boutique ne doit pas être dupliquée à cause d'un retry réseau.

## Workflow commercial

États métier prévus :

- `received` ;
- `validated` ;
- `rejected` ;
- `cancelled`.

La validation commerciale n'est pas automatiquement la confirmation native de la vente Odoo.

## Livraison

Le modèle de livraison distingue notamment :

- retrait ;
- livraison ;
- gratuit ;
- frais fixes ;
- cotation à confirmer.

Une adresse modifiée après cotation de livraison doit invalider une cotation devenue obsolète.

## Roadmap

La roadmap E-commerce Pro est découpée en lots :

- Lot A : backoffice commandes ;
- Lot B : workflow commercial ;
- Lot C : livraison ;
- Lot D : paiement ;
- Lot E : facturation ;
- Lot F : pilotage.

Le statut exact de chaque lot doit être lu dans le document canonique avant tout déploiement.

## Références

- [E-commerce Pro](https://github.com/gsentsas/dallytrading/blob/main/docs/ECOMMERCE-PRO.md)
- [Portail boutique natif](https://github.com/gsentsas/dallytrading/blob/main/docs/SHOP-NATIVE-PORTAL.md)
