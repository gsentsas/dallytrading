# Sauvegardes DallyTrading

## Périmètre réel

Une sauvegarde logique contient exactement la base PostgreSQL déclarée par
`ODOO_DB_NAME` et le répertoire de filestore correspondant
`/var/lib/odoo/filestore/<ODOO_DB_NAME>`. Elle ne lit aucun conteneur ni volume
extérieur au projet Compose `dallytrading`.

Les valeurs par défaut, surchargeables dans `.env`, sont :

| Ressource | Variable | Valeur sûre par défaut |
|---|---|---|
| Projet Compose | `COMPOSE_PROJECT_NAME` | `dallytrading` |
| Conteneur PostgreSQL | `PG_CONTAINER` | `dallytrading-postgres` |
| Conteneur Odoo | `ODOO_CONTAINER` | `dallytrading-odoo` |
| Volume PostgreSQL | `POSTGRES_VOLUME` | `dallytrading_postgres_data` |
| Volume filestore | `ODOO_FILESTORE_VOLUME` | `dallytrading_odoo_filestore` |
| Réseau privé | `PRIVATE_NETWORK` | `dallytrading_private` |
| Réseau sortant Odoo | `PUBLIC_NETWORK` | `dallytrading_public` |
| Base | `ODOO_DB_NAME` | `dallytrading` |
| Répertoire | `BACKUP_DIR` | `<projet>/backups` |

Avant toute lecture, `backup.sh` confirme que les deux conteneurs appartiennent au
projet attendu, qu'ils sont démarrés, que les volumes attendus sont montés aux bons
chemins, que les réseaux correspondent et que la base et son filestore existent. Les
noms `odoo_crm` et `sen_containers` sont explicitement refusés.

## Format

```text
backups/daily/20260813T021500Z/
├── database.dump
├── filestore.tar.gz
├── manifest.json
├── SHA256SUMS
└── .complete
```

Le manifeste v2 porte un horodatage logique unique dans
`database.captured_at` et `filestore.captured_at`. Les tailles réelles, le nom de
base et les ressources sources y sont consignés. `SHA256SUMS` couvre le dump,
l'archive et le manifeste.

L'archive contient uniquement le contenu du répertoire de la base. Cette disposition
permet à `restore.sh` de le réimplanter sous un autre nom de base isolé sans vider le
reste du volume Odoo.

## Exécution et vérification rapide

```bash
cd /var/www/vhosts/dallytrading.com/platform
./infrastructure/scripts/backup.sh --tag daily
./infrastructure/scripts/verify-backup.sh backups/daily/<timestamp>
```

La vérification rapide contrôle la complétude, le manifeste, la concordance des
timestamps et tailles, les SHA-256, le catalogue `pg_restore` et l'innocuité des
chemins de l'archive. Elle n'écrit rien dans PostgreSQL.

`backup.sh` applique un `umask` restrictif et prend un verrou exclusif dans
`BACKUP_DIR/.backup.lock`. Une seconde exécution concurrente échoue clairement au
lieu de produire deux captures qui se chevauchent.

Le mode profond s'exécute seulement après une restauration isolée :

```bash
./infrastructure/scripts/verify-backup.sh backups/daily/<timestamp> --deep
```

Il inspecte alors les conteneurs `dallytrading-restore-*`, leurs volumes et leur
réseau interne. Il refuse toute ressource de production et ne crée ni ne supprime de
base.

## Rétention

| Tag | Variable | Défaut |
|---|---|---|
| `daily` | `BACKUP_RETENTION_DAILY` | 7 |
| `weekly` | `BACKUP_RETENTION_WEEKLY` | 4 |
| `monthly` | `BACKUP_RETENTION_MONTHLY` | 6 |

La rétention ne supprime jamais la dernière sauvegarde complète. Les suppressions
restent bornées au sous-répertoire `BACKUP_DIR/<tag>`.

## Planification quotidienne systemd

Le dépôt fournit `dallytrading-backup.service` et `dallytrading-backup.timer`. Le
timer démarre chaque jour à 02:15 UTC, avec un décalage aléatoire maximal de 15
minutes. Il est persistant : un lancement manqué pendant un arrêt est rattrapé au
redémarrage.

Le service s'exécute sous l'utilisateur du vhost, ne publie aucun port et lance
`backup-daily.sh`. Celui-ci sauvegarde avec le tag `daily`, récupère le chemin exact
annoncé par `backup.sh`, exige le marqueur `.complete`, puis exécute
`verify-backup.sh` sur cet artefact. Toute erreur rend l'unité systemd en échec. Les
sorties sont ajoutées à `logs/backup.log`; la rétention quotidienne par défaut est
de 7 sauvegardes.

Validation sans créer de sauvegarde :

```bash
./infrastructure/scripts/backup-daily.sh --check
systemd-analyze verify \
  infrastructure/systemd/dallytrading-backup.service \
  infrastructure/systemd/dallytrading-backup.timer
```

Installation à effectuer avec les droits root :

```bash
sudo install -o root -g root -m 0644 \
  infrastructure/systemd/dallytrading-backup.service \
  /etc/systemd/system/dallytrading-backup.service
sudo install -o root -g root -m 0644 \
  infrastructure/systemd/dallytrading-backup.timer \
  /etc/systemd/system/dallytrading-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now dallytrading-backup.timer
sudo systemctl list-timers dallytrading-backup.timer --no-pager
```

Ne pas activer simultanément une entrée cron équivalente. L'installation des
unités ne doit intervenir qu'après une restauration isolée validée.

## Sauvegarde réelle validée le 13 août 2026

Artefact `backups/production-release/20260813T192539Z` :

- dump PostgreSQL : 5 652 016 octets, SHA-256 `1a431b88e49fa55070266f9c9e6bfc458e744d3f77d4c0f79c062c74e01d7d3f` ;
- filestore : 13 294 435 octets, 924 entrées, SHA-256 `f15e4796035147c1444304b8df14fd99bdfe7c5f03ad0e3d61f708097e8491f3` ;
- manifeste v2 : 950 octets, SHA-256 `aa54081ea1d6152d93f969a1af2d0a59631f95191acbb3a0ca6444b18aef9638` ;
- catalogue PostgreSQL : 433 entrées `TABLE DATA` ;
- vérification rapide et profonde : OK.

Ces empreintes peuvent être publiées : elles authentifient les fichiers sans révéler le contenu ni aucun secret.

## Copie hors serveur

Si toutes les variables S3 et la clé de chiffrement sont présentes, l'archive est
chiffrée localement avant envoi. Une configuration partielle provoque un refus
d'envoi, jamais un transfert en clair.

En l'absence de stockage externe configuré, les sauvegardes restent sur le même
serveur : c'est un risque de perte simultanée du service et de ses sauvegardes.
