# DallyTrading Wiki

**IMPORT • EXPORT • LOGISTICS • SOLUTIONS**

Bienvenue dans la documentation opérationnelle de **DallyTrading**.

DallyTrading repose sur deux surfaces complémentaires :

| Surface | Domaine | Rôle |
|---|---|---|
| Site public | `https://dallytrading.com` | Vitrine, demandes de devis, sourcing, trading, suivi, espace client et boutique |
| ERP / CRM | `https://crm.dallytrading.com` | Odoo 19 Community, source de vérité métier |

Le site public est développé en **Next.js**. Le cœur métier est porté par **Odoo 19**, avec une base **PostgreSQL 16** dédiée. Le reverse proxy public est assuré par **nginx/Plesk**.

## Principes structurants

1. **Odoo est la source de vérité métier.** Le navigateur ne décide ni des prix, ni des droits, ni des états métier.
2. **Le navigateur ne parle jamais directement à Odoo avec une clé d'intégration.** Les appels publics passent par le BFF Next.js.
3. **DallyTrading est techniquement indépendant des autres systèmes hébergés sur la machine.** Base, filestore, utilisateurs, modules, API, sauvegardes et ports sont séparés.
4. **Les secrets ne sont jamais versionnés.** Ils vivent dans `.env`, `odoo.conf` généré ou les Script Properties Google Apps Script.
5. **Les actions sensibles sont explicites.** Pas de création automatique de commande, facture, achat ou expédition quand une décision humaine est attendue.
6. **Les projections publiques fonctionnent par liste blanche.** Les coûts, marges, notes internes et identifiants techniques ne sortent pas par défaut.

## Navigation

### Comprendre la plateforme

- [[Architecture]]
- [[Modules-Odoo]]
- [[API-et-integrations]]

### Métiers

- [[Freight-et-consolidation]]
- [[Portail-client-et-tracking]]
- [[Sourcing]]
- [[Trading]]
- [[E-commerce]]
- [[Google-Sheets-Freight]]

### Exploitation

- [[Installation-et-deploiement]]
- [[Securite-et-isolation]]
- [[Sauvegardes-et-restauration]]
- [[Tests-et-qualite]]
- [[Exploitation-et-depannage]]
- [[Glossaire]]

## Documentation canonique

Le Wiki est une **porte d'entrée concise**. Les documents techniques détaillés restent versionnés dans `docs/` et constituent la référence de fond :

- `docs/ARCHITECTURE.md`
- `docs/API.md`
- `docs/DEPLOYMENT.md`
- `docs/RUNBOOK-DEPLOY.md`
- `docs/BACKUPS.md`
- `docs/RESTORE.md`
- `docs/PORTAL.md`
- `docs/SOURCING.md`
- `docs/TRADING.md`
- `docs/ECOMMERCE-PRO.md`
- `docs/FREIGHT-BRIDGE.md`
- `integrations/google-sheets/freight-sync/README.md`

## Règle de stabilité

Le Wiki décrit en priorité ce qui est présent sur la branche `main`. Une fonctionnalité en branche ou en pull request n'est pas considérée comme stable tant qu'elle n'a pas été fusionnée et qualifiée.

---

**Dépôt :** `gsentsas/dallytrading`  
**Branche de production :** `main`
