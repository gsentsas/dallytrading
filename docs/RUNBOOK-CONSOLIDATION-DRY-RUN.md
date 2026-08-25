# Runbook — dry-run production consolidation fret

Branche : `feat/freight-consolidation-workflow-20260825`
Date de rédaction : 2026-08-25
Portée : mise en service de `dally_freight_consolidation` + résserrement du workflow d'état de `dally.shipment` (garde des transitions, garde de `create`, propagation tk_freight ↔ Dally, jalon d'annulation).

**Ce document décrit le dry-run. Il n'exécute jamais la migration production.** L'exécution se fait en trois passes lisibles ; chacune est réversible tant qu'aucun `--production` n'est passé à `restore.sh`.

---

## 0. Prérequis, en lecture seule

```bash
cd /var/www/vhosts/dallytrading.com/platform
set -a
. ./.env
set +a
git status --short --branch                  # doit rester sur feat/freight-consolidation-workflow-20260825
bash infrastructure/scripts/preflight.sh     # santé Docker sans mutation
docker exec dallytrading-postgres psql -U odoo_dally -d dallytrading -tAc \
  "SELECT name, state FROM ir_module_module WHERE name IN
   ('dally_freight','dally_freight_bridge','dally_freight_notifications',
    'dally_tracking','dally_freight_billing','tk_freight');"
```

Attendu : tous `installed`, aucun `to upgrade`. Si un module apparaît en `to upgrade` avant même le début du dry-run, s'arrêter et diagnostiquer.

---

## 1. Sauvegarde production fraîche

La sauvegarde nocturne existe déjà (§Runbook Backup), mais on en refait une **datée du dry-run** pour éviter tout écart :

```bash
cd /var/www/vhosts/dallytrading.com/platform
set -a
. ./.env
set +a
bash infrastructure/scripts/backup.sh
ls -1 backups/daily | tail -3
```

Repérer le dossier créé, par exemple `backups/daily/20260825T060000Z/`. Contrôler `.complete` et `SHA256SUMS`.

**Rien n'a été écrit sur la production à ce stade** — `backup.sh` est en lecture seule.

---

## 2. Restauration isolée dans le projet dédié

Utiliser le Compose `dallytrading-restore` déjà décrit dans `docs/RESTORE.md`. Il monte un PostgreSQL et un support filestore **sur un réseau interne** sans port publié, avec des noms et labels distincts.

```bash
docker compose -p dallytrading-restore \
  --env-file .env \
  -f infrastructure/docker-compose.restore.yml \
  up -d

bash infrastructure/scripts/restore.sh \
  --isolated-test \
  --from backups/daily/20260825T060000Z/ \
  --replace-filestore \
  --confirm-filestore-volume dallytrading_restore_odoo_filestore
```

La base restaurée s'appelle `dallytrading_restore`. Le conteneur `dallytrading-restore-odoo` ne fait que porter le filestore ; il ne démarre pas l'application.

Contrôle : `docker exec dallytrading-restore-postgres psql -U postgres -d dallytrading_restore -tAc "SELECT count(*) FROM dally_shipment;"` renvoie le nombre attendu de dossiers.

---

## 3. Ancrer un Odoo éphémère sur la base restaurée

Le conteneur du projet restore est volontairement muet. Pour valider le comportement applicatif, on lance un Odoo temporaire qui pointe sur `dallytrading-restore-postgres`, avec les addons de la branche courante en `read-only`.

```bash
docker run --rm -it \
  --name dallytrading-dryrun-odoo \
  --network dallytrading_restore_private \
  -v /var/www/vhosts/dallytrading.com/platform/odoo/custom-addons:/mnt/extra-addons:ro \
  -v /var/www/vhosts/dallytrading.com/vendor-addons:/mnt/vendor-addons:ro \
  --volumes-from dallytrading-restore-odoo \
  odoo:19.0-20260810 \
  odoo \
    --db_host=dallytrading-restore-postgres --db_port=5432 \
    --db_user=postgres --db_password="$POSTGRES_PASSWORD" \
    -d dallytrading_restore \
    --stop-after-init --load-language fr_FR
```

Ce démarrage charge simplement les langues et sort. Aucune écriture applicative.

---

## 4. Upgrade des modules touchés, dans l'isolement

Toujours dans l'environnement `dallytrading-restore` :

```bash
docker run --rm -i \
  --name dallytrading-dryrun-odoo \
  --network dallytrading_restore_private \
  -v /var/www/vhosts/dallytrading.com/platform/odoo/custom-addons:/mnt/extra-addons:ro \
  -v /var/www/vhosts/dallytrading.com/vendor-addons:/mnt/vendor-addons:ro \
  --volumes-from dallytrading-restore-odoo \
  odoo:19.0-20260810 \
  odoo \
    --db_host=dallytrading-restore-postgres --db_port=5432 \
    --db_user=postgres --db_password="$POSTGRES_PASSWORD" \
    -d dallytrading_restore \
    --stop-after-init \
    -u dally_freight,dally_freight_bridge,dally_freight_notifications,dally_tracking,dally_freight_billing \
    -i dally_freight_consolidation
```

Points de contrôle dans les logs :

| Attendu | Motif |
|---|---|
| `Loading module dally_freight_consolidation` sans traceback | Le module s'installe pour la première fois. |
| `loading dally_freight_bridge/data/freight_shipment_stages.xml` | Les 13 stages tk sont créés (dont `stage_cancelled`). |
| Aucune ligne `ERROR` sur `dally.shipment` ni `dally.shipment.package` | Les gardes de transition n'ont rejeté aucune donnée existante. |
| Fin sur `Registry loaded in Xs` | Chargement complet réussi. |

Un `-i dally_freight_consolidation` déclenche aussi le calcul des computes stockés `consolidation_ids` / `consolidation_id` sur tous les dossiers existants (initialisation à vide, aucune consolidation historique n'est encore créée à ce stade).

---

## 5. Suite de tests contre la copie prod

```bash
docker run --rm -i \
  --network dallytrading_restore_private \
  -v /var/www/vhosts/dallytrading.com/platform/odoo/custom-addons:/mnt/extra-addons:ro \
  -v /var/www/vhosts/dallytrading.com/vendor-addons:/mnt/vendor-addons:ro \
  --volumes-from dallytrading-restore-odoo \
  odoo:19.0-20260810 \
  odoo \
    --db_host=dallytrading-restore-postgres --db_port=5432 \
    --db_user=postgres --db_password="$POSTGRES_PASSWORD" \
    -d dallytrading_restore \
    --stop-after-init --test-enable \
    --test-tags "/dally_freight,/dally_freight_bridge,/dally_freight_billing,/dally_freight_notifications,/dally_tracking,/dally_freight_consolidation"
```

Cible attendue : le nombre final de tests est renseigné après la suite complète ; **0 failed, 0 error**. La version Odoo est `19.0-20260810`.

---

## 6. Contrôles fonctionnels manuels (Odoo interactif éphémère)

### Validation concurrence réelle

Sur une base de dry-run isolée, le probe ouvre deux connexions PostgreSQL
indépendantes et appelle réellement `line.create()` / `package.write()` depuis
deux `Environment` Odoo. Il vérifie dans `pg_locks` que le second appel attend
le même verrou advisory avant d'être revalidé.

```bash
docker run --rm -i --entrypoint /usr/bin/python3 \
  --network dallytrading_restore_private \
  -v /var/www/vhosts/dallytrading.com/platform/odoo/custom-addons:/mnt/extra-addons:ro \
  -v /var/www/vhosts/dallytrading.com/vendor-addons:/mnt/vendor-addons:ro \
  --volumes-from dallytrading-restore-odoo \
  odoo:19.0-20260810 /usr/bin/odoo shell --config=/dev/null \
  --db_host=dallytrading-restore-postgres --db_port=5432 \
  --db_user=dryrun_odoo --db_password="" \
  -d dallytrading_restore --addons-path=/mnt/extra-addons,/mnt/vendor-addons \
  < /mnt/extra-addons/dally_freight_consolidation/scripts/verify_concurrency_probe.py
```

Le probe crée des données préfixées `CONCURRENCY-PROBE-*`, confirme les deux
scénarios, puis les supprime dans un `finally` et vérifie qu'il ne reste aucun
enregistrement.

Facultatif si (5) est vert. À réserver aux Managers freight.

Facultatif si (5) est vert. À réserver aux Managers freight.

Publier temporairement Odoo sur `127.0.0.1:8199` — jamais sur `0.0.0.0` :

```bash
docker run --rm -d --name dallytrading-dryrun-web \
  --network dallytrading_restore_private \
  -p 127.0.0.1:8199:8069 \
  -v /var/www/vhosts/dallytrading.com/platform/odoo/custom-addons:/mnt/extra-addons:ro \
  -v /var/www/vhosts/dallytrading.com/vendor-addons:/mnt/vendor-addons:ro \
  --volumes-from dallytrading-restore-odoo \
  odoo:19.0-20260810 \
  odoo \
    --db_host=dallytrading-restore-postgres --db_port=5432 \
    --db_user=postgres --db_password="$POSTGRES_PASSWORD" \
    -d dallytrading_restore --db-filter=^dallytrading_restore$
```

Parcours à faire, dans l'ordre, sur `http://127.0.0.1:8199` :

1. **Progression d'un dossier** — prendre un dossier `draft` de la copie et cliquer les boutons de progression. Toutes les étapes intermédiaires doivent apparaître dans le fil de discussion. Toute étape sautée doit être refusée avec le message *« Transition impossible ».*
2. **Annulation** — annuler un dossier `preparing` lié à tk : le stage tk doit passer à *Annulé* et le fil doit tracer la transition.
3. **Consolidation** — depuis un dossier `preparing`, cliquer *« Ajouter à la consolidation ouverte »*. Créer une consolidation aérienne DSS→CDG, y ajouter deux dossiers, saisir MAWB + vol, marquer *Prête au départ*, tenter *Enregistrer le départ* avec un dossier non payé → refus. Après paiement de la facture, *Enregistrer le départ* passe.
4. **Dérogation** — sur un dossier business à facture partiellement réglée, ouvrir la dérogation Manager, saisir une raison, valider. Vérifier la trace dans le chatter et l'immutabilité (relire le champ en tant que Logistics : masqué).
5. **Backfill historique** — sur la consolidation `AIR-DSS-CDG-2026-001` (créer si absente), ouvrir *Prévisualiser le backfill*, saisir la date de cutoff, lancer *Prévisualiser*. Vérifier que la liste s'affiche, qu'aucune donnée n'est modifiée, qu'aucune notification client n'est en file. Confirmer et vérifier que les dossiers passent en `departed` sans envoi de courriel.
6. **Manifeste** — imprimer le rapport PDF depuis la consolidation.

Arrêt de l'Odoo éphémère :

```bash
docker stop dallytrading-dryrun-web
```

---

## 7. Nettoyage complet du dry-run

```bash
docker compose -p dallytrading-restore -f infrastructure/docker-compose.restore.yml down -v
```

**Le `-v` ici est autorisé** parce que ce sont les volumes du projet `dallytrading-restore` (labels `com.dallytrading.restore=true`), pas ceux de la production. Le préflight du restore l'a déjà vérifié à l'aller.

---

## 8. Ce qui reste à faire APRÈS le dry-run vert

Cette section est intentionnellement séparée : **rien de ce qui suit ne s'exécute dans le dry-run**.

1. Commit + push de la branche `feat/freight-consolidation-workflow-20260825` sur `origin`.
2. Créer la PR vers `main`, joindre :
   - le résultat des 476 tests (0 failed, 0 error) ;
   - les captures d'écran des 6 parcours manuels ;
   - la liste explicite des invariants introduits (gardes `create`/`write`, stage tk `cancelled`, backfill idempotent).
3. Review par un deuxième pair sur les modifications de `dally_freight/models/dally_shipment.py` (§20 est du code critique).
4. **Migration production** — hors périmètre de ce runbook. Elle passera par `restore.sh --production` dans le sens inverse (rollback prêt) et un `odoo -u ...` avec la stack de production ; les commandes exactes vivent dans `RUNBOOK-DEPLOY.md`.

---

## Annexe A — Deltas fonctionnels apportés par la branche

| Fichier | Nature |
|---|---|
| `dally_freight/models/dally_shipment.py` | Garde `create` (état initial ∈ {draft, request_received}), garde `write` (transitions adjacentes), hooks `_check_ready/_departure_requirements`, `action_next_state` + boutons d'étape. |
| `dally_freight/views/dally_shipment_views.xml` | Statusbar élargie (8 étapes), 12 boutons de progression. |
| `dally_freight_bridge/data/freight_shipment_stages.xml` | 13 stages tk (12 étapes + `cancelled`), `is_last_stage=1` sur `delivered`. |
| `dally_freight_bridge/models/operational_workflow.py` | Propagation Dally→tk avec sudo local sur `tk_shipment_id` (ACL sync users). Propagation tk→Dally avec vérification de transition. |
| `dally_freight_bridge/models/freight_mapping.py` | Mapping bidirectionnel des 13 stages/états. |
| `dally_freight_bridge/models/quote_provisioning.py` | La sync fournisseur écrit désormais côté tk (`stage_id`), la projection Dally suit par sync tk→Dally. |
| `dally_freight_notifications/models/dally_shipment.py` | Événements d'un backfill historique ne mettent aucune notification en file. |
| `dally_tracking/models/dally_shipment.py` | Événements de backfill utilisent `historical_event_date` (pas `now()`). |
| `dally_freight_consolidation/*` | Nouveau module : consolidations aériennes, colis clients, MAWB, manifeste, wizards *ajouter*, *dérogation*, *backfill*. |

## Annexe B — Points d'attention connus

- **Sequences PostgreSQL et canaris de test.** Le canari `charges=999.0` dans `test_les_colis_du_fournisseur_sont_projetes` a été relevé à `74747474.0` pour rester distinctif quand les ID de test dépassent 999.
- **Bouton *Prévisualiser le backfill*** — visible uniquement sur `AIR-DSS-CDG-2026-001` (hard-coded volontairement, usage unique historique).
- **Poids d'emballage maître** — le champ `master_packaging_weight_kg` ne modifie jamais les poids clients ; il ne sert qu'à afficher un écart réconcilié dans le manifeste et n'est jamais imputé dans les factures.
