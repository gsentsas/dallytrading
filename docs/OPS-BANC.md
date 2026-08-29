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

`npm ci` part du lockfile et est déterministe. `npm install` à partir de rien,
lui, plantait sur `Cannot read properties of null (reading 'edgesOut')` : c'est
un défaut d'`arborist` (npm 10.8.2) déclenché par
`@vitest/browser-playwright@4.1.11`, qui exige `vitest` **exactement** en
4.1.11 alors que le paquet était épinglé en 4.1.10. Le contournement
`legacy-peer-deps` a été retiré au profit de l'alignement de version, qui
supprime le conflit au lieu de le masquer. `apps/web` présente le même
symptôme, masqué par son propre lockfile : il l'aura tant que son `vitest`
restera en 4.1.10. Sa correction est volontairement laissée à un chantier
séparé — l'aligner en même temps qu'un travail métier mêlerait un changement de
dépendances de production à une revue fonctionnelle.

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
npm run verify        # types, lint, 287 tests unitaires
```

Les tests de bout en bout ont besoin d'un navigateur ; les bibliothèques
système manquent sur cette machine, donc on passe par l'image officielle :

```bash
docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e OPS_E2E_BASE_URL=http://127.0.0.1:3020 \
  -v <worktree>:<worktree> -w <worktree>/apps/ops \
  mcr.microsoft.com/playwright:v1.62.1-noble npx playwright test
```

## 5. Les départs de banc

Quatre consolidations existent dans `dally_ops`, choisies pour couvrir le
filtre : `AIR-DSS-CDG-TEST-001` (aérien, collecte ouverte, départ prévu),
`SEA-DKR-LEH-TEST-001` (maritime, collecte ouverte, sans départ prévu),
`ROAD-DKR-BKO-TEST-001` (routier — hors phase 1) et `AIR-DSS-CDG-TEST-DRAFT`
(brouillon). Seules les deux premières doivent apparaître à l'écran.

## 6. Les clients de banc

Trois fiches, choisies pour couvrir les trois issues de la recherche :

| Fiche | Numéro | Sert à prouver |
| --- | --- | --- |
| Aissatou Kandji | `+221 77 123 45 67` | la correspondance unique |
| Mamadou Konaté | `+221 76 000 00 00` | l'ambiguïté… |
| Mariama Konaté | `00221760000000` | …écrite autrement, et pourtant le même numéro |
| Ousmane Ba | `+221 76 555 44 33` | une fiche que la recherche précédente n'a pas vue |

`+221 77 999 88 77` ne correspond à personne : c'est le cas « aucun client
trouvé ». `Ousmane Ba` sert au scénario de création : l'écran vient d'annoncer
« aucun client » pour un autre numéro, et le serveur retrouve pourtant cette
fiche au moment d'écrire.

Les essais de création laissent des fiches dans la base du banc — c'est voulu,
et les scénarios tirent un numéro neuf à chaque exécution pour rester
rejouables.

## 7. Les dépenses de banc

Les dépenses s'imputent sur un départ, et le filtre est plus large que celui
des réceptions : `collecting`, `collection_closed`, `ready`, `departed`,
`arrived`. On paie une manutention pendant la collecte, un dédouanement après
le départ, un stockage à l'arrivée. `AIR-DSS-CDG-TEST-001` sert de départ de
référence ; `AIR-DSS-CDG-TEST-DRAFT` doit rester absent de la liste.

Les scénarios laissent des dépenses dans la base — c'est voulu, et chacun tire
un libellé neuf à chaque exécution pour rester rejouable.

Deux fichiers suffisent à couvrir la détection de type, parce qu'elle se fait
sur les **octets** et non sur le nom :

| Contenu | Nom annoncé | Type annoncé | Attendu |
| --- | --- | --- | --- |
| `FF D8 FF E0 …` | `ticket.jpg` | `image/jpeg` | accepté |
| `<html><script>…` | `ticket.jpg` | `image/jpeg` | refusé, dépense intacte |

## 8. Ce que le banc a servi à établir

- Un compte **non interne**, sans aucun droit de lecture métier, se connecte et
  obtient son identité : l'architecture de référence tient en conditions
  réelles.
- Un compte interne **sans rôle Ops** reçoit un `403` d'Odoo et, côté
  application, exactement le même message qu'un mot de passe faux.
- Le cookie `dt_ops_session` est `httpOnly` : `document.cookie` ne le voit pas.
- Ni session Odoo, ni secret, ni mot de passe n'apparaissent dans le HTML servi
  ni dans le journal du serveur.
- Un logisticien à qui `dally.freight.consolidation` est refusé par l'ORM
  obtient malgré tout la liste de ses départs : le privilège vit dans le
  service, jamais dans le compte.
- Le même compte, à qui `res.partner` est refusé, retrouve un client par son
  numéro — et se voit refuser deux fiches plutôt que d'en montrer une.
- Ni numéro, ni adresse électronique n'apparaissent dans une URL : la recherche
  passe par un corps de requête.
- Une création rejouée après une coupure réseau porte le même identifiant de
  demande et ne produit qu'une fiche.
- Un logisticien sans aucun droit sur `dally.cash.expense` enregistre une
  dépense : `.sudo()` suffit, et c'est un test HTTP réel qui l'a établi. Les
  encaissements avaient exigé un environnement superutilisateur explicite ; les
  dépenses non, et l'exception n'a donc pas été généralisée.
- Une photo refusée — trop lourde, ou déguisée en JPEG alors que ses octets
  disent HTML — laisse la dépense enregistrée. L'argent sorti de la caisse ne
  dépend jamais de la réussite d'un envoi d'image.
- Deux devises se lisent côte à côte, sans total unique : aucune conversion
  n'est faite nulle part dans la chaîne.
- Une dépense historique venue du tableur, sans départ, continue de
  fonctionner : `consolidation_id` reste facultatif au niveau du modèle, et
  c'est Dally Ops seul qui l'exige.
