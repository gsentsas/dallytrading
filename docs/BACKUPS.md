# Stratégie de sauvegarde

## Principe fondamental

Une sauvegarde Odoo se compose de **deux artefacts inséparables** :

| Artefact | Contenu | Emplacement |
|---|---|---|
| Base PostgreSQL | Enregistrements, configuration, droits, séquences | volume `dally_postgres_data` |
| Filestore | Pièces jointes binaires (documents de fret, scans, photos) | volume `dally_odoo_filestore` |

Odoo ne stocke **pas** les pièces jointes dans la base : `ir_attachment` conserve une
somme de contrôle qui pointe vers un fichier du filestore. En conséquence :

> Un dump de base sans son filestore correspondant produit une base qui référence des
> fichiers inexistants. L'interface affiche les documents, leur téléchargement échoue.
> L'inverse est vrai aussi : un filestore sans sa base est un tas de fichiers sans nom
> ni contexte.

`backup.sh` capture donc les deux **dans le même répertoire horodaté**, et refuse de
laisser une sauvegarde partielle : en cas d'échec en cours de route, le répertoire est
supprimé. Le marqueur `.complete` n'est écrit qu'après succès des deux captures.

## Contenu d'une sauvegarde

```text
backups/daily/20260812T021500Z/
├── database.dump       pg_dump -Fc (compressé, restauration sélective possible)
├── filestore.tar.gz    /var/lib/odoo
├── manifest.json       base, horodatage, tailles, versions Odoo et PostgreSQL
├── SHA256SUMS          empreintes des deux artefacts
└── .complete           marqueur de succès — son absence invalide la sauvegarde
```

## Utilisation

```bash
./infrastructure/scripts/backup.sh                  # étiquette « daily » par défaut
./infrastructure/scripts/backup.sh --tag weekly
./infrastructure/scripts/backup.sh --tag monthly
```

Le script vérifie que les conteneurs tournent, contrôle que le dump n'est pas
anormalement petit (< 4 Ko = échec silencieux de `pg_dump`), calcule les empreintes,
écrit le manifeste, puis applique la rétention.

## Rétention

| Étiquette | Conservation | Planification |
|---|---|---|
| `daily` | 7 | 02h15 chaque jour |
| `weekly` | 4 | 03h30 le dimanche |
| `monthly` | 6 | 04h45 le 1er du mois |

Configurable via `BACKUP_RETENTION_*` dans `.env`.

**Garde-fou** : la rétention ne supprime jamais la **dernière sauvegarde complète**
restante, même si le quota l'exige. Mieux vaut dépasser le quota disque que se
retrouver sans aucune sauvegarde restaurable.

## Copie distante

Une sauvegarde uniquement locale ne protège pas de la perte du serveur. Lorsque `S3_*`
est renseigné dans `.env`, `backup.sh` chiffre l'archive **avant** l'envoi :

```text
tar → openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt → S3
```

Le chiffrement précède le transfert : le prestataire de stockage ne voit jamais les
données en clair. Si `BACKUP_ENCRYPTION_KEY` est vide, **l'envoi est refusé** plutôt
qu'effectué en clair.

> ⚠️ `BACKUP_ENCRYPTION_KEY` doit être conservée **hors de ce serveur**. Perdre la clé
> rend toutes les archives distantes définitivement illisibles — y compris pour vous.

## Vérification

```bash
./infrastructure/scripts/verify-backup.sh                  # la plus récente, contrôles rapides
./infrastructure/scripts/verify-backup.sh <chemin>
./infrastructure/scripts/verify-backup.sh <chemin> --deep   # restauration réelle
```

| Niveau | Contrôles | Prouve la restaurabilité ? |
|---|---|---|
| rapide | fichiers présents, `.complete`, SHA-256, manifeste JSON, en-tête du dump lisible via `pg_restore --list`, intégrité de l'archive `gzip` | ❌ Non |
| `--deep` | restaure le dump dans une base **jetable**, compte les tables, vérifie `res_users`, `res_partner`, `ir_module_module`, puis supprime la base | ✅ Oui |

Le mode `--deep` n'écrit **jamais** dans la base de production : il crée une base
temporaire `verify_<horodatage>_<pid>`, supprimée systématiquement en sortie, y compris
en cas d'interruption (`trap`).

`--deep` requiert le droit `CREATEDB` sur le rôle, volontairement absent en
exploitation courante. Voir l'étape 8 de [`DEPLOYMENT.md`](DEPLOYMENT.md) pour
l'accorder temporairement.

## Ce que couvre — et ne couvre pas — Plesk

Le gestionnaire de sauvegardes de Plesk sauvegarde les fichiers des vhosts et les bases
déclarées **dans Plesk**. Il ne couvre **ni** les volumes Docker, **ni** la cohérence
base ↔ filestore d'Odoo. Les deux dispositifs sont complémentaires :

| Dispositif | Périmètre |
|---|---|
| Plesk | Fichiers du vhost, configuration du domaine, certificats |
| `backup.sh` | Base Odoo + filestore, de façon atomique |

## Supervision

Les journaux vont dans `logs/backup.log`. Points à surveiller (phase 8) :

- Sauvegarde absente depuis plus de 26 h → alerte.
- `verify-backup.sh` en échec → alerte.
- Occupation disque > `DISK_USAGE_THRESHOLD` (85 %) → alerte. Le disque est à 52 %
  aujourd'hui, avec 337 Gi libres.
- Échec de l'envoi distant → alerte (la copie locale est conservée dans ce cas).

## Restauration

Procédure et exercice obligatoire : [`RESTORE.md`](RESTORE.md).

> Une sauvegarde dont la restauration n'a jamais été testée n'est pas une sauvegarde (§62).
