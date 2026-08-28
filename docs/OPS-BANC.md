# Banc de test de Dally Ops

Comment rejouer la chaîne complète — navigateur → BFF Next.js → session Odoo →
`/api/v1/ops/me` — sans toucher à la production.

> **Ce banc n'est pas la production.** Il utilise sa propre base
> (`dally_ops`), son propre conteneur et ses propres comptes. Aucune étape de
> ce document ne redémarre un conteneur de production, ne crée un utilisateur
> en production, ni n'écrit dans `dallytrading`.

## 1. Le serveur Odoo de banc

La base `dally_ops` vit sur le serveur PostgreSQL du banc *freight-dev*. Le
conteneur Odoo qui la sert est distinct de celui du banc freight, parce qu'il
doit monter le worktree où `dally_ops_mobile` est développé :

```
docker run -d --name dallytrading-ops-bench-odoo \
  --network dallytrading_freight_dev_private \
  -v <scratch>/ops-bench/odoo.conf:/etc/odoo/odoo.conf:ro \
  -v <worktree>/odoo/custom-addons:/mnt/extra-addons:ro \
  -v /tmp/dallytrading-tk-freight-dev/vendor-addons:/mnt/vendor-addons:ro \
  -v dallytrading_ops_bench_filestore:/var/lib/odoo \
  odoo:19.0
```

La configuration est celle du banc freight, avec `dbfilter = ^dally_ops$` et
`db_name = dally_ops`.

Deux points appris à la mise en place :

- **Le filestore ne se partage pas** avec le banc freight : `/var/lib/odoo`
  appartient à l'autre conteneur, et Odoo échoue sur `sessions/` avec un
  `PermissionError`. D'où le volume dédié.
- **Sur cette machine, `-p` reste sans effet** : `docker port` ne renvoie rien
  et rien n'écoute côté hôte. On joint donc le conteneur par son adresse sur
  le réseau Docker, relevée avec
  `docker inspect … --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'`.

## 2. Les comptes de banc

| Compte | Interne ? | Rôle Ops | Sert à prouver |
| --- | --- | --- | --- |
| `gilles.banc` | non (`share = True`) | logisticien | qu'un compte à zéro modèle lisible suffit |
| `temoin.banc` | oui (`base.group_user`) | aucun | qu'un compte Odoo valide est refusé sans rôle Ops |

Ils se créent par `odoo shell` sur la base `dally_ops`. En Odoo 19 le champ
s'appelle `group_ids` sur `res.users` — `groups_id` lève
`ValueError: Invalid field`.

## 3. L'application

```bash
cd apps/ops && npm ci
```

Puis, en pointant vers le banc :

```bash
OPS_PUBLIC_URL=http://127.0.0.1:3020 \
OPS_SESSION_SECRET=<32 caractères de banc> \
ODOO_URL=http://<ip-du-banc>:8069 \
ODOO_DATABASE=dally_ops \
npm run build && npm run start
```

`OPS_PUBLIC_URL` en `http://` retire le drapeau `Secure` du cookie, ce qui est
nécessaire pour un banc local — et seulement pour lui.

## 4. Les tests

```bash
npm run verify        # types, lint, 104 tests unitaires
```

Les tests de bout en bout ont besoin d'un navigateur ; les bibliothèques
système manquent sur cette machine, donc on passe par l'image officielle :

```bash
docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e OPS_E2E_BASE_URL=http://127.0.0.1:3020 \
  -v <worktree>:<worktree> -w <worktree>/apps/ops \
  mcr.microsoft.com/playwright:v1.62.1-noble npx playwright test
```

## 5. Ce que le banc a servi à établir

- Un compte **non interne**, sans aucun droit de lecture métier, se connecte et
  obtient son identité : l'architecture de référence tient en conditions
  réelles.
- Un compte interne **sans rôle Ops** reçoit un `403` d'Odoo et, côté
  application, exactement le même message qu'un mot de passe faux.
- Le cookie `dt_ops_session` est `httpOnly` : `document.cookie` ne le voit pas.
- Ni session Odoo, ni secret, ni mot de passe n'apparaissent dans le HTML servi
  ni dans le journal du serveur.
