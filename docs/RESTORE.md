# Restauration et exercice de reprise

Deux usages distincts :

1. **Exercice de restauration** — obligatoire avant la mise en production (§62, §91).
   Se déroule sur une base jetable, sans jamais toucher la production.
2. **Restauration réelle** — après incident, perte de données ou migration.

---

## Partie 1 — Exercice de restauration (obligatoire)

### Objectif

Prouver qu'une sauvegarde est effectivement restaurable. Tant que cet exercice n'a pas
réussi, la mise en production n'est pas validée.

### Procédure

```bash
cd /var/www/vhosts/dallytrading.com/platform
```

**1. Produire une sauvegarde de référence**

```bash
./infrastructure/scripts/backup.sh --tag daily
BACKUP=$(find backups/daily -mindepth 1 -maxdepth 1 -type d | sort -r | head -1)
echo "Sauvegarde de référence : ${BACKUP}"
```

**2. Contrôles d'intégrité**

```bash
./infrastructure/scripts/verify-backup.sh "${BACKUP}"
```

Attendu : `RÉSULTAT : contrôles rapides OK.`

**3. Accorder temporairement `CREATEDB`**

Le rôle applicatif n'a pas ce droit en exploitation normale, par principe de moindre
privilège. L'exercice en a besoin pour créer une base jetable.

```bash
docker exec dallytrading-postgres psql -U postgres -c 'ALTER ROLE odoo_dally CREATEDB;'
```

**4. Restauration réelle en base jetable**

```bash
./infrastructure/scripts/verify-backup.sh "${BACKUP}" --deep
```

Le script crée `verify_<horodatage>_<pid>`, y restaure le dump, compte les tables,
vérifie la présence d'utilisateurs, de contacts et de modules, puis **supprime la base**.
La production n'est jamais touchée.

Attendu : `RÉSULTAT : sauvegarde VALIDE et restaurabilité PROUVÉE.`

**5. Restauration complète sur une base de test nommée**

Contrairement à `--deep`, cette étape restaure **aussi le filestore**, seul moyen de
valider la cohérence base ↔ pièces jointes.

```bash
./infrastructure/scripts/restore.sh "${BACKUP}" --target-db essai_restauration --skip-filestore
```

> `--skip-filestore` est utilisé ici car le filestore est partagé par le volume Odoo :
> le restaurer écraserait celui de la base de production. La validation complète
> base + filestore se fait à l'étape 6, sur un environnement isolé.

**6. Validation base + filestore en environnement isolé**

Seul montage qui valide l'ensemble de la chaîne. Sur une machine ou un projet Docker
séparé :

```bash
export COMPOSE_PROJECT_NAME=dally_restore_test
cd infrastructure
docker compose --env-file ../.env -f docker-compose.yml up -d postgres
# volumes distincts grâce au préfixe de projet
cd ..
./infrastructure/scripts/restore.sh "${BACKUP}" --yes
```

Contrôles fonctionnels, à effectuer manuellement dans l'interface :

- [ ] Connexion avec un compte utilisateur réel
- [ ] Ouverture d'une fiche contact
- [ ] Ouverture d'un devis / d'une commande
- [ ] **Téléchargement d'une pièce jointe** ← valide la cohérence base ↔ filestore
- [ ] Ouverture d'une expédition et de sa chronologie d'événements
- [ ] Aucune erreur dans `docker logs dallytrading-odoo`

**7. Retirer `CREATEDB`**

```bash
docker exec dallytrading-postgres psql -U postgres -c 'ALTER ROLE odoo_dally NOCREATEDB;'
```

**8. Nettoyer l'environnement de test**

```bash
docker exec dallytrading-postgres psql -U postgres -d postgres \
  -c 'DROP DATABASE IF EXISTS essai_restauration;'
```

### Consignation

À archiver après chaque exercice (au minimum trimestriel) :

| Champ | Valeur |
|---|---|
| Date de l'exercice | |
| Sauvegarde utilisée | |
| Taille base / filestore | |
| Durée de la restauration | |
| Contrôles fonctionnels | ✅ / ❌ |
| Anomalies rencontrées | |
| Opérateur | |

---

## Partie 2 — Restauration réelle en production

> ⚠️ **Opération destructive.** Écrase la base **et** le filestore de production.

### Garde-fous intégrés à `restore.sh`

1. **Vérification préalable** — les empreintes SHA-256 et le marqueur `.complete` sont
   contrôlés *avant* toute écriture. Une sauvegarde corrompue est refusée.
2. **Sauvegarde de sécurité automatique** — l'état actuel est dumpé dans
   `backups/pre-restore/`. Si ce dump échoue et que la cible est la production,
   **la restauration est refusée**.
3. **Confirmation explicite** — en production, il faut saisir exactement le nom de la
   base. Un `[o/N]` serait trop facile à valider par réflexe.
4. **Arrêt d'Odoo** — restaurer sous une instance active corrompt le cache et laisse des
   verrous incohérents. Odoo est redémarré en sortie quoi qu'il arrive (`trap`).

### Procédure

```bash
cd /var/www/vhosts/dallytrading.com/platform

# 1. Choisir la sauvegarde
find backups -mindepth 2 -maxdepth 2 -type d | sort -r | head -10

# 2. La vérifier AVANT de restaurer
./infrastructure/scripts/verify-backup.sh backups/daily/20260812T021500Z

# 3. Restaurer
./infrastructure/scripts/restore.sh backups/daily/20260812T021500Z
```

Le script enchaîne : vérification → confirmation → sauvegarde de sécurité → arrêt
d'Odoo → restauration de la base → restauration du filestore → redémarrage → contrôle
de disponibilité sur `/web/health` (jusqu'à 180 s).

### Contrôles post-restauration

```bash
curl -sf http://127.0.0.1:18169/web/health && echo OK
docker logs --tail 100 dallytrading-odoo | grep -iE 'error|traceback' || echo "aucune erreur"
curl -o /dev/null -w '%{http_code}\n' https://crm.dallytrading.com/
```

Puis, dans l'interface : connexion, ouverture d'un enregistrement, **téléchargement
d'une pièce jointe**.

### Retour arrière

Si la restauration produit un état pire que l'initial, la sauvegarde de sécurité prise à
l'étape 3 permet de revenir en arrière :

```bash
ls -lt backups/pre-restore/
./infrastructure/scripts/restore.sh backups/pre-restore/<horodatage>-dallytrading --skip-filestore
```

---

## Objectifs de reprise

| Indicateur | Cible | Fondement |
|---|---|---|
| **RPO** (perte de données maximale) | 24 h | Sauvegarde quotidienne à 02h15 |
| **RTO** (délai de rétablissement) | < 1 h | À confirmer par chronométrage lors de l'exercice |

Ces valeurs restent des **hypothèses** jusqu'au premier exercice chronométré. Le RTO
dépend directement de la taille du filestore, qui croîtra avec les documents de fret.
À réévaluer à chaque exercice trimestriel.

Pour un RPO inférieur à 24 h, il faudrait activer l'archivage WAL en continu sur
PostgreSQL — non retenu au MVP, la volumétrie et la criticité initiales ne le
justifiant pas.
