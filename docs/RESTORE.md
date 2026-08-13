# Restauration et exercice isolé

## Principes de sécurité

`restore.sh` ne choisit jamais une cible implicitement. Une invocation doit préciser
`--isolated-test` ou `--production`. Une simple option `--target-db` ne suffit
pas et ne modifie jamais un filestore.

Le remplacement du filestore exige simultanément :

- `--replace-filestore` ;
- `--confirm-filestore-volume <nom exact>`.

En mode production, il faut aussi répéter le nom de base avec
`--confirm-production-db`, puis saisir une phrase complète au clavier. Le mode
production refuse tout nom de conteneur, volume ou réseau différent de ceux déclarés
pour DallyTrading et produit d'abord une sauvegarde complète `pre-restore`.

## Exercice obligatoire dans des ressources dédiées

Depuis la racine du projet :

```bash
cd /var/www/vhosts/dallytrading.com/platform

docker compose -p dallytrading-restore \
  --env-file .env \
  -f infrastructure/docker-compose.restore.yml \
  up -d
```

Ce Compose crée uniquement :

| Type | Nom par défaut |
|---|---|
| Conteneur PostgreSQL | `dallytrading-restore-postgres` |
| Conteneur support filestore | `dallytrading-restore-odoo` |
| Volume PostgreSQL | `dallytrading_restore_postgres_data` |
| Volume filestore | `dallytrading_restore_odoo_filestore` |
| Réseau interne | `dallytrading_restore_private` |
| Base restaurée | `dallytrading_restore` |

Aucun port n'est publié. Les conteneurs ne rejoignent que le réseau interne dédié. Ils
portent le label `com.dallytrading.restore=true`, comme leurs volumes et leur réseau.
`restore.sh` vérifie ces faits, les montages exacts et l'absence de toute ressource
production avant le premier `DROP DATABASE`.

Restauration complète :

```bash
BACKUP=backups/daily/<timestamp>

./infrastructure/scripts/restore.sh "$BACKUP" \
  --isolated-test \
  --replace-filestore \
  --confirm-filestore-volume dallytrading_restore_odoo_filestore \
  --yes

./infrastructure/scripts/verify-backup.sh "$BACKUP" --deep
```

Le mode profond contrôle en lecture seule le nombre de tables, les modules
`dally_*`, les utilisateurs, les partenaires, les tables métier, la lisibilité du
filestore et l'isolation réseau/volumes/ports.

Nettoyage après validation :

```bash
docker compose -p dallytrading-restore \
  --env-file .env \
  -f infrastructure/docker-compose.restore.yml \
  down --volumes --remove-orphans
```

Cette commande cible seulement le projet éphémère `dallytrading-restore`. Aucun
`prune`, arrêt global ou suppression globale n'est autorisé.

## Exercice réellement exécuté le 13 août 2026

Le backup `production-release/20260813T192539Z` a été restauré en **13 secondes** dans les ressources `dallytrading-restore-*` décrites ci-dessus : 436 tables, 7 modules DallyTrading, 16 tables métier et 923 fichiers lisibles. La base isolée comptait 8 utilisateurs et 9 partenaires. Aucun port, volume, conteneur, réseau ou nom de base de production ne figurait dans la cible. Les ressources de cet exercice ont ensuite été supprimées avec le `down --volumes` explicitement borné au projet `dallytrading-restore`, sans prune.

## Restauration de production

Opération de dernier recours, destructive, à exécuter pendant une fenêtre de
maintenance :

```bash
./infrastructure/scripts/restore.sh backups/daily/<timestamp> \
  --production \
  --confirm-production-db dallytrading \
  --replace-filestore \
  --confirm-filestore-volume dallytrading_odoo_filestore
```

Le filestore restauré remplace uniquement
`/var/lib/odoo/filestore/dallytrading`, jamais tout le volume. Une restauration de
base seule est refusée sauf ajout de `--acknowledge-db-only`, car elle peut
désynchroniser les pièces jointes.

La restauration de production arrête et redémarre uniquement
`dallytrading-odoo`; elle ne touche jamais `odoo_crm` ni `odoo_crm_db`.

## Objectifs

La cible reste un RPO de 24 h avec sauvegarde quotidienne. Le RTO doit être remplacé
par la durée réellement mesurée lors de chaque exercice isolé et consignée dans le
checkpoint de production.
