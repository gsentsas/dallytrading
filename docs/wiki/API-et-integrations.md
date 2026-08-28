# API et intégrations

DallyTrading sépare strictement les API publiques du site et les API privées d'Odoo.

## Deux surfaces

| Surface | Exposition | Authentification | Consommateur |
|---|---|---|---|
| `dallytrading.com/api/*` | publique | selon la route, souvent aucune | navigateur |
| `crm.dallytrading.com/api/v1/*` | privée | clé API ou session Odoo | backend Next.js / intégrations |

Le navigateur ne reçoit jamais une clé d'intégration Odoo.

```text
Navigateur → API Next.js → OdooGateway → API Odoo
```

## OdooGateway

L'accès serveur à Odoo passe par `OdooGateway`.

Implémentation de production :

- `DallyApiAdapter` → endpoints `/api/v1/*`.

Les autres adaptateurs restent des abstractions et ne doivent pas être considérés comme actifs tant qu'ils ne sont pas implémentés et qualifiés.

## Endpoints structurants

### Catalogue de services

```http
GET /api/v1/services
X-API-Key: ...
```

Odoo est la source de vérité des services publiés et des champs requis par le formulaire.

### Demandes de devis

```http
POST /api/v1/quotes
```

Le flux métier reste :

```text
formulaire → dally.quote.request → crm.lead
           → qualification → sale.order → confirmation → expédition si nécessaire
```

Une soumission publique ne crée pas automatiquement une commande ou une expédition.

### Portail client

Les routes `/api/v1/portal/*` utilisent la **session réelle du client Odoo**, pas une clé de service.

### Freight Google Sheets

Le connecteur exploite notamment :

```text
POST /api/v1/freight/sync
POST /api/v1/freight/invoice
POST /api/v1/freight/payment
POST /api/v1/freight/payment/reconcile
POST /api/v1/freight/expense
POST /api/v1/freight/cash-transfer
```

## Authentification par capacité

Les intégrations utilisent des identités séparées et des scopes minimaux. Une fuite de clé doit être bornée à une capacité métier, pas donner accès à toute la plateforme.

Exemples de capacités :

- lecture catalogue ;
- écriture devis ;
- sourcing ;
- tracking ;
- Freight sync ;
- Freight facturation/paiement/caisse.

## Idempotence

Les opérations d'écriture utilisent des identifiants métier ou UUID stables afin qu'un retry réseau ne duplique pas les objets.

Exemples :

- `requestUuid` pour une demande publique ;
- clés dossier/article/paiement pour Freight ;
- identifiant panier pour la boutique.

## Règle de projection

Les DTO publics utilisent des listes blanches explicites. Un nouveau champ Odoo ne devient jamais public automatiquement.

Ne doivent pas sortir vers le navigateur par défaut :

- coûts fournisseurs ;
- marges ;
- commissions internes ;
- notes de négociation ;
- identifiants techniques ;
- références du module tiers Freight.

## Référence complète

[docs/API.md](https://github.com/gsentsas/dallytrading/blob/main/docs/API.md)
