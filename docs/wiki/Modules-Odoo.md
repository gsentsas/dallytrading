# Modules Odoo

Tout le métier DallyTrading vit dans `odoo/custom-addons/`. Le cœur Odoo n'est jamais modifié.

## Socle

| Module | Rôle |
|---|---|
| `dally_core` | Références, séquences, mixins, paramètres et groupes communs |
| `dally_crm` | Demandes de devis qualifiables, CRM, anti-doublon, liens commerciaux |
| `dally_api` | API REST versionnée, clés, scopes, idempotence et journalisation |

## Freight

| Module | Rôle |
|---|---|
| `dally_freight` | Expéditions, colis, maritime, aérien, routier, véhicules, CBM, poids taxable |
| `dally_freight_billing` | Synchronisation commerciale, facturation brouillon, paiements et caisse Freight |
| `dally_freight_consolidation` | Groupages, consolidations et planification des départs |
| `dally_freight_routing` | Routes et règles d'acheminement |
| `dally_freight_dashboard` | Pilotage et vues opérationnelles |
| `dally_freight_data` | Données métier de référence du sous-système Freight |
| `dally_freight_notifications` | Notifications Freight |
| `dally_freight_bridge` | Confinement et projection du module tiers Freight vers les modèles DallyTrading |

## Portail et tracking

| Module | Rôle |
|---|---|
| `dally_tracking` | Événements, timeline et suivi public sécurisé |
| `dally_portal` | API et projections de l'espace client authentifié |

## Commerce

| Module | Rôle |
|---|---|
| `dally_sourcing` | Demandes sourcing, fournisseurs candidats, offres internes, propositions client, achat et vente |
| `dally_trade` | Achat-revente, import-export, distribution, courtage, commission et représentation commerciale |
| `dally_shop` | Catalogue, panier, commandes boutique, workflow commercial et logistique e-commerce |

## Principes de conception

### Réutiliser Odoo natif

DallyTrading réutilise les objets natifs lorsqu'ils existent :

- `res.partner` pour clients et fournisseurs ;
- `sale.order` pour les ventes ;
- `purchase.order` pour les achats ;
- `account.move` et `account.payment` pour la comptabilité ;
- `product.product` pour les articles ;
- `uom.uom` pour les unités ;
- `account.incoterms` pour les Incoterms.

Les modules DallyTrading ajoutent la logique métier, pas des copies parallèles de modèles Odoo standards.

### Confidentialité structurelle

Les informations internes sont protégées à plusieurs niveaux :

- groupes sur les champs (`groups=`) ;
- ACL ;
- record rules ;
- projections publiques par liste blanche.

Masquer un champ uniquement dans une vue n'est jamais considéré comme une protection suffisante.

### Partenaires externes

Un partenaire externe est modélisé comme un `res.partner` standard. Aucun partenaire commercial ne doit devenir une dépendance technique du cœur DallyTrading.

## Références

- [README du projet](https://github.com/gsentsas/dallytrading/blob/main/README.md)
- [Sourcing](https://github.com/gsentsas/dallytrading/blob/main/docs/SOURCING.md)
- [Trading](https://github.com/gsentsas/dallytrading/blob/main/docs/TRADING.md)
- [Freight Bridge](https://github.com/gsentsas/dallytrading/blob/main/docs/FREIGHT-BRIDGE.md)
