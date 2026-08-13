# DallyTrading — Plateforme numérique

**IMPORT • EXPORT • LOGISTICS • SOLUTIONS**

Écosystème composé de deux applications :

| Application | Domaine | Rôle |
|---|---|---|
| Site public | `https://dallytrading.com` | Vitrine, devis, suivi, espace client, boutique |
| ERP / CRM | `https://crm.dallytrading.com` | Odoo 19 Community — système central de gestion |

---

## ⚠️ Contexte d'hébergement — à lire avant toute intervention

Ce projet **ne tourne pas sur un VPS dédié**. Il partage un serveur Plesk avec une
vingtaine d'autres domaines en production.

1. **Plesk possède les ports 80 et 443.** Ne jamais démarrer de conteneur qui les
   publie : cela couperait tous les domaines de la machine. Le reverse proxy est le
   nginx de Plesk, configuré via
   [`infrastructure/nginx/`](infrastructure/nginx/).
2. **Une autre instance Odoo tourne sur cette machine** (Odoo 18, base
   `sen_containers_crm`, ports `18069`/`18072`, domaine `crm.sen-containers.com`). Elle
   appartient à un autre abonnement. **Ne pas la modifier, la lire, l'interroger ni s'y
   connecter.** L'instance DallyTrading utilise les ports `18169`/`18172` et une base
   distincte.
3. **Aucune commande destructive** (`docker compose down -v`, `DROP DATABASE`,
   `rm -rf`) sans avoir identifié l'impact et pris une sauvegarde. Des données de
   production tierces sont sur cette machine.

Constats de sécurité relevés lors de l'audit : [`docs/SECURITY-FINDINGS.md`](docs/SECURITY-FINDINGS.md).

---

## 1. Prérequis

Déjà présents sur le serveur (vérifiés) :

| Composant | Version |
|---|---|
| Ubuntu | 24.04.4 LTS |
| Docker | 29.7.2 |
| Docker Compose | v5.4.0 |
| Node.js | 20.20.2 |
| Git | 2.43.0 |
| OpenSSL, envsubst | 3.0.13 / 0.21 |

Requis en complément :

- Accès `root` ou membre du groupe `docker` (pour les conteneurs).
- Accès administrateur Plesk (certificats, DNS, directives nginx).
- 4 Gi de swap à créer — cf. DT-004 dans les constats de sécurité.

## 2. Arborescence

```text
platform/
├── infrastructure/
│   ├── docker-compose.yml              Stack Odoo 19 + PostgreSQL 16
│   ├── docker-compose.production.yml   Surcouche de durcissement
│   ├── nginx/                          Directives à coller dans Plesk
│   └── scripts/                        Secrets, config, sauvegarde, restauration
├── odoo/
│   ├── config/odoo.conf.template       Modèle versionné
│   ├── config/odoo.conf                GÉNÉRÉ — 0600, hors Git
│   └── custom-addons/                  Modules DallyTrading
├── apps/web/                            Next.js
│   ├── src/app/                         /, /a-propos, /activites, /devis,
│   │                                    /sourcing, /tracking, /contact,
│   │                                    sitemap, robots
│   ├── src/components/                  brand (logo), layout, ui, seo
│   ├── src/config/                      site (coordonnées), activities (contenu)
│   ├── src/features/                    quote, contact, tracking
│   ├── src/services/odoo/               OdooGateway + adaptateurs
│   └── src/lib/                         env, logger, rate-limit
├── docs/
└── .env                                 GÉNÉRÉ — 0600, hors Git
```

## 3. Variables d'environnement

Tous les paramètres vivent dans `.env`, jamais dans le code.
[`.env.example`](.env.example) documente chaque variable.

```bash
./infrastructure/scripts/generate-secrets.sh
```

Crée `.env` en `0600` et génère `POSTGRES_PASSWORD`, `ODOO_ADMIN_PASSWD` et
`BACKUP_ENCRYPTION_KEY` (32 octets aléatoires chacun). Le script est **idempotent** :
il ne réécrit jamais un secret déjà renseigné — régénérer `POSTGRES_PASSWORD` après
l'initialisation de la base empêcherait Odoo de s'y connecter.

À compléter ensuite manuellement : `ODOO_API_KEY`, `SMTP_*`, `S3_*`, `ALERT_EMAIL`.

Contrôle indispensable :

```bash
git check-ignore -v .env odoo/config/odoo.conf
```

## 4. Démarrage

```bash
./infrastructure/scripts/generate-secrets.sh
./infrastructure/scripts/render-config.sh
cd infrastructure
docker compose --env-file ../.env -f docker-compose.yml -f docker-compose.production.yml up -d
```

`render-config.sh` doit être relancé après **toute** modification de `.env` touchant
Odoo : `odoo.conf` en est un artefact généré.

Initialiser la base au premier démarrage :

```bash
docker exec -it dally-odoo odoo -c /etc/odoo/odoo.conf \
    -d dallytrading -i base --without-demo=all --stop-after-init
docker restart dally-odoo
```

Contrôle :

```bash
curl -sf http://127.0.0.1:18169/web/health && echo OK
docker compose ps          # les deux services doivent être « healthy »
```

## 5. Tests

### Modules Odoo

Validation statique, sans Odoo — utilisable en CI :

```bash
python3 infrastructure/scripts/validate-addons.py odoo/custom-addons
```

Vérifie la cohérence vues ↔ modèles, les manifestes, les ACL, les identifiants
externes et les imports. Les tests unitaires Odoo (`odoo/custom-addons/*/tests/`)
requièrent une instance et n'ont **pas encore été exécutés** :

```bash
docker exec -it dally-odoo odoo -c /etc/odoo/odoo.conf \
    -d dallytrading --test-enable --test-tags dally --stop-after-init
```

### Site Next.js

```bash
cd apps/web
npm run verify        # typecheck + lint + tests
```

## 6. Build

```bash
cd apps/web
npm run build
```

⚠️ **Les variables `NEXT_PUBLIC_*` doivent être présentes AVANT le build.**
Next.js les inline pendant `next build`, et les pages statiques — accueil, à
propos, les onze pages activités — sont rendues à ce moment. Les fournir
seulement au runtime produit un site sans téléphone, sans e-mail et sans bouton
WhatsApp sur toutes ces pages, **sans aucune erreur**. Constaté en test, détaillé
dans [`.env.example`](.env.example).

⚠️ `next.config.mjs` fixe `output: 'standalone'` : **`next start` est alors
inopérant** (Next l'annonce au démarrage). La commande de production est
`node .next/standalone/server.js`. Détail dans
[`docs/VPS-MIGRATION.md`](docs/VPS-MIGRATION.md) § 8.

En développement, toujours lier le serveur à la loopback — cette machine est
partagée :

```bash
npx next dev --hostname 127.0.0.1 --port 3010
```

## 7. Odoo

- Configuration : [`odoo/config/odoo.conf.template`](odoo/config/odoo.conf.template)
- Dimensionnement calculé pour ce serveur : 4 workers, 2 threads cron, limites mémoire
  1,5 / 2 Gi. **Pas** la formule `(2×vCPU)+1`, qui supposerait une machine dédiée.
- `list_db = False` et `dbfilter = ^dallytrading$` : le Database Manager est fermé
  (critères §9 et §91).

## 8. Modules custom

Le core Odoo n'est **jamais** modifié. Tout vit dans `odoo/custom-addons/` :

| Module | Rôle |
|---|---|
| `dally_core` | ✅ Socle : séquences `DT-YYYY-NNNNNN`, mixins, paramètres |
| `dally_crm` | ✅ `dally.quote.request` qualifiable, extension `crm.lead`, anti-doublon, lien `sale.order` |
| `dally_freight` | ✅ `dally.shipment` + lignes de colis : maritime, aérien, routier, véhicules, groupage, CBM, conteneurs, **poids taxable** |
| `dally_tracking` | ✅ `dally.shipment.event`, timeline publique, frontière de confidentialité à trois couches |
| `dally_sourcing` | ✅ Demande, fournisseurs candidats, offres internes, propositions client ; workflow 16 états, conversions achat et vente |
| `dally_trade` | `dally.trade.opportunity` |
| `dally_agrobusiness` | Socle extensible, minimal au MVP |
| `dally_api` | ✅ Points d'accès REST versionnés `/api/v1/*` |

SEN CONTAINERS est traité comme un **partenaire externe standard** (`res.partner`), au
même titre que tout autre fournisseur. Aucun champ ni module dédié dans le cœur.

## 9. Migration

Jamais de mise à jour majeure directement en production (§66) :
sauvegarde → clone en staging → mise à jour → tests → validation → production.

## 10. Déploiement

[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — procédure complète, y compris les étapes
nécessitant `root` ou Plesk.

---

## Sauvegardes

```bash
./infrastructure/scripts/backup.sh                     # base + filestore, atomique
./infrastructure/scripts/verify-backup.sh --deep       # prouve la restaurabilité
./infrastructure/scripts/restore.sh <chemin>           # restauration
```

Base et filestore forment **une seule sauvegarde logique** : un dump sans son filestore
produit des pièces jointes orphelines. Détails : [`docs/BACKUPS.md`](docs/BACKUPS.md),
exercice de restauration : [`docs/RESTORE.md`](docs/RESTORE.md).

> Une sauvegarde dont la restauration n'a jamais été testée n'est pas une sauvegarde (§62).

## Documentation

| Document | Contenu | Phase |
|---|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Architecture, décisions et arbitrages | ✅ |
| [`docs/SECURITY-FINDINGS.md`](docs/SECURITY-FINDINGS.md) | Constats de l'audit | ✅ |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Déploiement pas à pas (Plesk) | ✅ |
| [`docs/VPS-MIGRATION.md`](docs/VPS-MIGRATION.md) | Déploiement et migration vers un VPS dédié | ✅ |
| [`docs/BACKUPS.md`](docs/BACKUPS.md) | Stratégie de sauvegarde | ✅ |
| [`docs/RESTORE.md`](docs/RESTORE.md) | Exercice de restauration | ✅ |
| [`docs/API.md`](docs/API.md) | Contrat d'API, OdooGateway, tracking public | ✅ |
| [`docs/SOURCING.md`](docs/SOURCING.md) | Sous-système sourcing : modèles, workflow, confidentialité | ✅ |
| `docs/ODOO.md` | Exploitation Odoo au quotidien | Phase 3 |
| `docs/SECURITY.md` | Politique de sécurité applicative | Phase 8 |
| `docs/OPERATIONS.md` | Runbooks d'exploitation | Phase 12 |

## Git

Stratégie **trunk-based** : `main` protégé, branches courtes `feature/*`, déploiement
par tags. Justification (§68) : équipe réduite, un seul environnement de production,
livraisons fréquentes — GitFlow ajouterait de la cérémonie sans bénéfice à cette
échelle.
