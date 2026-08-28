# Installation et déploiement

> Cette page est un aide-mémoire. Les procédures exhaustives restent dans `docs/DEPLOYMENT.md` et `docs/RUNBOOK-DEPLOY.md`.

## Prérequis

Environnement cible :

- Ubuntu 24.04 LTS ;
- Docker + Docker Compose ;
- Node.js 22 pour le site ;
- Git ;
- accès au groupe `docker` ou privilèges administrateur ;
- accès Plesk pour DNS, TLS et directives nginx.

## Secrets et configuration

Les secrets vivent dans `.env`, jamais dans Git.

```bash
./infrastructure/scripts/generate-secrets.sh
./infrastructure/scripts/render-config.sh
```

`generate-secrets.sh` est idempotent : il ne doit pas écraser les secrets déjà utilisés par la base.

Contrôle indispensable :

```bash
git check-ignore -v .env odoo/config/odoo.conf
```

## Pré-vol

Avant toute intervention :

```bash
bash infrastructure/scripts/preflight.sh
```

Le pré-vol contrôle notamment :

- ressources ;
- droits ;
- ports ;
- exposition réseau ;
- secrets ;
- fichiers ignorés par Git ;
- domaines et TLS.

## Démarrage Odoo + PostgreSQL

```bash
cd infrastructure
docker compose -p dallytrading \
  --env-file ../.env \
  -f docker-compose.yml \
  -f docker-compose.production.yml \
  up -d
```

Premier démarrage de la base :

```bash
docker exec -it dallytrading-odoo \
  odoo -c /etc/odoo/odoo.conf \
  -d dallytrading -i base --without-demo=all --stop-after-init

docker restart dallytrading-odoo
```

## Vérification santé

```bash
curl -sf http://127.0.0.1:18169/web/health && echo OK
cd infrastructure
docker compose -p dallytrading ps
```

Les services doivent être `healthy`.

## Site Next.js

```bash
cd apps/web
npm ci
npm run verify
npm run build
```

Les variables `NEXT_PUBLIC_*` doivent être présentes **avant** le build, car Next.js les intègre dans les pages statiques.

La production utilise `output: 'standalone'`. Le serveur démarre avec :

```bash
node .next/standalone/server.js
```

et non `next start`.

## Reverse proxy

Plesk possède les ports 80/443. Ne jamais lancer de proxy Docker sur ces ports.

Les directives versionnées sont dans :

```text
infrastructure/nginx/
```

Elles sont appliquées depuis l'interface Plesk.

## Règle de mise à jour

Une mise à jour majeure ne se fait jamais directement en production :

```text
sauvegarde → clone/staging → mise à jour → tests → validation → production
```

## Liens utiles

- [Déploiement détaillé](https://github.com/gsentsas/dallytrading/blob/main/docs/DEPLOYMENT.md)
- [Runbook de mise en service](https://github.com/gsentsas/dallytrading/blob/main/docs/RUNBOOK-DEPLOY.md)
- [Migration vers VPS dédié](https://github.com/gsentsas/dallytrading/blob/main/docs/VPS-MIGRATION.md)
