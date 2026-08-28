# Trading

`dally_trade` gère les opérations commerciales auxquelles DallyTrading participe directement.

## Frontière avec le sourcing

- **Sourcing** : DallyTrading cherche une solution, un fournisseur ou un produit pour le compte d'un client.
- **Trading** : DallyTrading achète, revend, distribue, met en relation, touche une commission ou représente commercialement pour son propre compte.

## Six types d'opération

| Type | Modèle économique | Volet achat |
|---|---|---|
| Achat-revente | marge de négoce | oui |
| Import-export | marge de négoce | oui |
| Distribution | marge de négoce | oui |
| Courtage | honoraires | non |
| Commission | commission | non |
| Représentation commerciale | commission | non |

Un courtage ne doit pas créer artificiellement une commande d'achat : DallyTrading n'acquiert pas la marchandise.

## Modèles principaux

| Modèle | Rôle |
|---|---|
| `dally.trade.opportunity` | dossier commercial, parties, workflow, devises, marge, approbation |
| `dally.trade.line` | lignes avec prix d'achat et de vente distincts |
| `dally.trade.cost` | coûts internes |
| `dally.trade.commission` | commissions à recevoir ou payer |

## Prix et marge

Les prix d'achat et de vente sont saisis explicitement.

Une marge n'est pas déduite naïvement de montants exprimés dans des devises différentes. La conversion doit être explicitement définie avant de produire une marge comparable.

## Confidentialité

Un utilisateur opérationnel peut travailler sur le dossier sans nécessairement voir :

- le fournisseur ;
- le prix d'achat ;
- les coûts ;
- les commissions ;
- la marge brute ou nette ;
- les notes de négociation ;
- les informations d'approbation.

La protection repose sur plusieurs couches :

1. `groups=` sur les champs ;
2. ACL ;
3. record rules ;
4. projections publiques par liste blanche.

## Réutilisation Odoo

Le module s'appuie sur les modèles natifs :

- `res.partner` ;
- `product.product` ;
- `sale.order` ;
- `purchase.order` ;
- `account.move` ;
- `uom.uom` ;
- `account.incoterms`.

Le module Trading orchestre le dossier métier ; il ne remplace pas la comptabilité, les ventes, les achats ou le Freight.

## Référence complète

[docs/TRADING.md](https://github.com/gsentsas/dallytrading/blob/main/docs/TRADING.md)
