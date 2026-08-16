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

`.complete` signifie exclusivement **backup local complet et vérifié**. Le marqueur
est écrit après validation des empreintes, de l'archive filestore, du catalogue
PostgreSQL et de la cohérence du manifeste. Il ne signifie ni « upload effectué » ni
« objet distant vérifié » et sa sémantique reste compatible avec le restore existant.

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

`backup.sh` prend un verrou exclusif dans `BACKUP_DIR/.backup.lock` : une seconde
exécution concurrente échoue clairement au lieu de produire deux captures qui se
chevauchent.

### Permissions : imposées, pas héritées

Les répertoires de sauvegarde sont en `700` et les fichiers en `600`, posés par des
`chmod` explicites — à la création et après l'écriture du marqueur `.complete`.

Le script pose bien `umask 0077`, mais cela ne suffisait pas : l'umask ne protège que
ce que le script crée pendant son exécution, et une sauvegarde lancée depuis un shell
dont l'umask valait 022 produisait des répertoires `755` et des fichiers `644`. Le
`database.dump` de production s'est ainsi retrouvé lisible par les ~20 comptes
d'hébergement de cette machine partagée (constat DT-007).

Un umask est un état hérité de l'appelant. Faire dépendre la protection d'un dump de
production d'une variable que personne ne vérifie ne tient pas ; le `chmod` explicite,
si.

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
`verify-backup.sh` sur cet artefact. Si `backup.sh` retourne un code non nul,
`backup-daily.sh` le détecte via `PIPESTATUS` et retourne lui-même 1.

L'unité installée est de type `oneshot`, son `ExecStart` appelle directement
`backup-daily.sh`, `ignore_errors=no` et aucun `SuccessExitStatus` alternatif
n'est défini. La chaîne attendue est donc :

```text
backup.sh != 0
→ backup-daily.sh = 1
→ dallytrading-backup.service Result=exit-code
```

Les sorties sont ajoutées à `logs/backup.log`; la rétention quotidienne par défaut
est de 7 sauvegardes. Cet état `failed` est volontairement exploitable par une
alerte ou un monitoring ultérieur.

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

### Détection sans ambiguïté

Les variables structurantes sont `S3_ENDPOINT`, `S3_BUCKET`, `S3_REGION`,
`S3_ACCESS_KEY` et `S3_SECRET_KEY`.

| État | Mode | Résultat attendu |
|---|---|---|
| Les cinq variables `S3_*` sont vides | local-only | `OFFSITE DISABLED: not configured`; succès si le local est valide |
| Au moins une variable `S3_*` est présente, mais la configuration est incomplète ou incohérente | erreur de configuration | backup local conservé; job non nul |
| Les cinq variables, `BACKUP_ENCRYPTION_KEY`, `aws` et `openssl` sont valides | offsite requis | upload et vérification distante obligatoires |

Une clé `BACKUP_ENCRYPTION_KEY` préparée seule n'active pas l'offsite. Ce choix
permet à `generate-secrets.sh` de préparer une installation local-only sans la
mettre artificiellement en panne. Dès qu'une variable `S3_*` est renseignée, la clé
de chiffrement fait partie des prérequis obligatoires. Les noms de credentials
configurés sont `S3_ACCESS_KEY` et `S3_SECRET_KEY`; ils ne deviennent
`AWS_ACCESS_KEY_ID` et `AWS_SECRET_ACCESS_KEY` que dans l'environnement privé du
sous-processus `aws`.

L'endpoint doit être HTTPS, le bucket et la région doivent avoir un format valide,
et la clé de chiffrement doit contenir au moins 32 caractères. Pour Backblaze B2
DallyTrading, la région attendue reste `eu-central-003`.

### Ordre et sémantique d'échec

Le job suit cet ordre :

1. dump PostgreSQL ;
2. archive du filestore ;
3. manifeste v2 ;
4. `SHA256SUMS` ;
5. vérification locale ;
6. écriture de `.complete` et log `LOCAL BACKUP COMPLETE` ;
7. création du bundle `<tag>-<timestamp>.tar.gz.enc` ;
8. chiffrement AES-256-CBC, PBKDF2, 200000 itérations ;
9. upload vers `odoo/<tag>/<tag>-<timestamp>.tar.gz.enc` ;
10. `head-object` distant et comparaison exacte de `ContentLength` ;
11. suppression du bundle chiffré temporaire ;
12. rétention locale.

Quand l'offsite est configuré, sont fatals : configuration partielle ou incohérente,
client `aws` absent, client ou opération `openssl` en échec, upload en échec,
objet distant absent, `head-object` en échec et taille distante différente. Le job
termine alors avec un code non nul après la rétention locale.

Les cinq artefacts locaux restent présents et vérifiables :

```text
database.dump
filestore.tar.gz
manifest.json
SHA256SUMS
.complete
```

Le bundle chiffré hors de ce répertoire est temporaire et supprimé après succès
comme après échec. Le backup local complet permet de le reconstruire; conserver des
bundles orphelins sans rétention risquerait de remplir le disque. Si la suppression
elle-même échoue, le job est également marqué en échec et le trap réessaie sans
jamais supprimer le backup local.

Les logs stables sont notamment :

```text
LOCAL BACKUP COMPLETE
OFFSITE DISABLED: not configured

LOCAL BACKUP COMPLETE
OFFSITE UPLOAD SUCCESS
OFFSITE VERIFY SUCCESS

LOCAL BACKUP COMPLETE
OFFSITE UPLOAD FAILED
BACKUP JOB FAILED: required offsite copy was not completed
```

Aucune valeur de credential, clé de chiffrement, URL signée ou contenu d'archive
n'est journalisé. Backup local réussi et backup offsite réussi sont deux résultats
distincts; si l'offsite est requis, le second conditionne le succès global.

### Tests isolés

La matrice de panne utilise uniquement des mocks Docker, `aws` et `openssl` :

```bash
./infrastructure/tests/test-backup-offsite.sh
```

Elle couvre local-only, succès offsite, absence d'`aws`, configuration partielle,
échec de chiffrement, d'upload, de vérification distante, différence de taille,
préservation/vérification du local, absence de secrets dans les logs, propagation
par `backup-daily.sh`, rétention et permissions 700/600. Elle ne contacte jamais
B2 et ne touche aucun conteneur.

### Plan du test de succès en production — à ne pas lancer sans validation

Après revue et déploiement séparé du code seulement :

1. lancer manuellement un backup avec un tag dédié ;
2. confirmer `LOCAL BACKUP COMPLETE`, les SHA-256 et la vérification locale ;
3. confirmer le chiffrement AES-256-CBC/PBKDF2/200000 ;
4. confirmer `OFFSITE UPLOAD SUCCESS` ;
5. confirmer `OFFSITE VERIFY SUCCESS` et la taille distante exacte ;
6. confirmer le code de sortie 0 et les permissions 700/600.

Ce plan ne prévoit aucune panne volontaire de B2, aucune suppression distante et
aucune modification d'Object Lock. Le restore demeure inchangé et continue
d'accepter le manifest v2 et le format local existant.

En l'absence de stockage externe configuré, les sauvegardes restent sur le même
serveur : c'est un risque de perte simultanée du service et de ses sauvegardes.
