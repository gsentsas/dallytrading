# Architecture

## Vue d'ensemble

```text
Navigateur
   │
   ▼
Next.js — dallytrading.com
   │  BFF / API same-origin
   ▼
OdooGateway
   │  X-API-Key pour les intégrations publiques serveur-à-serveur
   │  session Odoo pour le portail client
   ▼
Odoo 19 — crm.dallytrading.com
   │
   ▼
PostgreSQL 16 dédié
```

Le reverse proxy HTTPS est assuré par **nginx de Plesk**. Aucun conteneur DallyTrading ne publie directement les ports 80 ou 443.

## Composants

| Composant | Technologie | Responsabilité |
|---|---|---|
| Site public | Next.js | Pages publiques, formulaires, boutique, BFF, espace client |
| ERP / CRM | Odoo 19 Community | Source de vérité métier, droits, workflows, ventes, achats, fret |
| Base | PostgreSQL 16 | Base `dallytrading`, non exposée publiquement |
| Reverse proxy | Plesk nginx | TLS, redirections, proxy vers les services loopback |
| Intégrations | REST + Apps Script | Site, Google Sheets, outils d'exploitation |

## Isolation

DallyTrading utilise une instance dédiée :

- base PostgreSQL dédiée ;
- filestore dédié ;
- utilisateurs dédiés ;
- modules `dally_*` dédiés ;
- clés API dédiées ;
- sauvegardes dédiées ;
- ports Odoo dédiés (`18169` / `18172` sur loopback).

Les autres instances Odoo présentes sur l'hôte sont **hors périmètre** et ne doivent pas être lues, interrogées ou modifiées par DallyTrading.

## Décisions importantes

### Plesk reste propriétaire du trafic web

Les ports 80/443 sont déjà utilisés par Plesk pour plusieurs domaines. La stack DallyTrading n'ajoute donc pas de reverse proxy Docker concurrent.

### PostgreSQL est conteneurisé et non publié

Le service PostgreSQL n'expose aucun port sur l'hôte. Il n'est joignable que depuis le réseau Docker privé de DallyTrading.

### Le cœur Odoo n'est jamais modifié

Les adaptations métier vivent dans `odoo/custom-addons/`. Cette règle facilite les mises à jour et évite les forks du noyau Odoo.

### Une passerelle unique vers Odoo

Le site utilise `OdooGateway`. L'implémentation de production est `DallyApiAdapter`, basée sur les endpoints `/api/v1/*` des modules DallyTrading.

Aucun appel métier Odoo ne doit être dispersé directement dans les composants frontend.

## Frontières de responsabilité

- **Next.js** : expérience utilisateur, validation de forme, BFF, protections web.
- **Odoo** : validation métier, droits, prix, workflow, création d'objets métier.
- **PostgreSQL** : persistance, contraintes et intégrité transactionnelle.
- **Google Sheets** : outil opérationnel synchronisé, jamais source comptable de vérité.

## Documents de référence

- [Architecture détaillée](https://github.com/gsentsas/dallytrading/blob/main/docs/ARCHITECTURE.md)
- [Contrat API](https://github.com/gsentsas/dallytrading/blob/main/docs/API.md)
- [Déploiement](https://github.com/gsentsas/dallytrading/blob/main/docs/DEPLOYMENT.md)
- [Audit sécurité](https://github.com/gsentsas/dallytrading/blob/main/docs/SECURITY-FINDINGS.md)
