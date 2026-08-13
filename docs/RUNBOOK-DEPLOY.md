# Runbook — mise en service DallyTrading

État opérationnel et procédure de maintenance de `dallytrading.com` et `crm.dallytrading.com`. Production validée le 13 août 2026 : Docker DallyTrading, Odoo 19, frontend systemd, HTTPS/HSTS, tracking, backup et restauration isolée.

---

## 0. Avant de commencer

Ce serveur héberge **une vingtaine de domaines en production** et une instance Odoo
tierce (SEN CONTAINERS, base `sen_containers_crm`, ports 18069/18072). Aucune commande
de ce runbook ne doit la toucher.

Trois interdits absolus :

| Interdit | Conséquence si transgressé |
|---|---|
| Publier un conteneur sur les ports 80 ou 443 | Coupe **tous** les domaines de la machine |
| `docker compose -p dallytrading down -v` | Détruit les volumes, donc la base |
| Toucher aux conteneurs, volumes ou base SEN CONTAINERS | Incident sur un abonnement tiers |

Contrôle de pré-vol, **en lecture seule**, à lancer avant et après :

```bash
cd /var/www/vhosts/dallytrading.com/platform && bash infrastructure/scripts/preflight.sh
```

État au 13/08/2026 : accès Docker opérationnel. Le swap, le stockage hors serveur et l’installation root du timer restent à traiter séparément.

---

## 1. Accès applicatif

Le compte projet a accès au démon Docker. Toute commande Compose doit inclure explicitement `-p dallytrading`; aucune commande globale et aucun `prune` ne sont permis. Le compte reste sans sudo, ce qui borne les modifications systemd et Plesk aux interventions administrateur.

---

## 2. Swap (constat DT-004)

La machine n'a **aucun swap**. Sur un hôte partagé, un pic mémoire déclenche l'OOM
killer, qui choisit sa victime parmi tous les processus — y compris ceux des autres
abonnements.

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
swapon --show
```

---

## 3. Démarrer la stack

Les secrets et `odoo.conf` sont **déjà générés** (64 caractères aléatoires chacun,
fichiers en 0600, hors Git). Ne pas les régénérer : `POSTGRES_PASSWORD` régénéré après
initialisation empêcherait Odoo de se connecter.

```bash
cd /var/www/vhosts/dallytrading.com/platform/infrastructure
docker compose -p dallytrading --env-file ../.env \
  -f docker-compose.yml -f docker-compose.production.yml up -d
docker compose -p dallytrading ps
```

Attendu : `dallytrading-postgres` et `dallytrading-odoo` en `healthy`.

Contrôles :

```bash
ss -lntp | grep -E '18169|18172'   # doit montrer 127.0.0.1 uniquement
ss -lnt  | grep ':5432'            # PostgreSQL ne doit PAS être publié sur l'hôte
curl -sf http://127.0.0.1:18169/web/health && echo " Odoo répond"
```

Si un port apparaît sur `0.0.0.0`, **arrêter immédiatement** : la stack serait
joignable depuis internet en contournant Plesk.

---

## 4. Créer la base

Une seule base, `dallytrading`. `dbfilter = ^dallytrading$` interdit toute autre.

```bash
docker exec -it dallytrading-odoo odoo -c /etc/odoo/odoo.conf \
  -d dallytrading -i base --without-demo=True --stop-after-init
```

`--without-demo=True` est impératif : les données de démonstration créent des clients,
des produits et des factures fictifs qu'il faudrait ensuite distinguer des vrais.

---

## 5. Installer les modules

L'ordre ci-dessous est **résolu depuis les `depends` des manifestes**, pas supposé :

```
dally_core → dally_crm → dally_api → dally_freight → dally_sourcing
           → dally_tracking → dally_trade
```

Modules Odoo natifs requis, et **uniquement** ceux-là : `base`, `mail`, `crm`, `utm`,
`sale`, `purchase`, `account`, `uom`. Odoo les tire automatiquement des dépendances —
il n'y a rien à installer à la main, et surtout pas l'ensemble des applications.

Installation module par module, pour que l'échec éventuel désigne son module :

```bash
cd /var/www/vhosts/dallytrading.com/platform/infrastructure
for M in dally_core dally_crm dally_api dally_freight dally_sourcing dally_tracking dally_trade; do
  echo "── installation : $M"
  docker exec dallytrading-odoo odoo -c /etc/odoo/odoo.conf \
    -d dallytrading -i "$M" --stop-after-init --log-level=warn || {
      echo "ÉCHEC sur $M — ne pas continuer"; break; }
done
docker restart dallytrading-odoo
```

---

## 6. Exécuter les tests Odoo

Ne jamais lancer les tests sur la base de production. La recette du 13 août 2026 a utilisé une base, un volume PostgreSQL, un filestore et un réseau éphémères dédiés, sans port publié. Résultat : **587 méthodes en 134,69 s, 0 échec, 0 erreur** ; 79 713 requêtes. Les résultats par module sont consignés dans le checkpoint de production.

## 7. Créer la clé API

Dans Odoo : **Paramètres → Technique → DallyTrading API → Clés d'API**.

Scopes nécessaires au site :

```
services:read  leads:write  quotes:write  sourcing:write  trading:write  tracking:read
```

Reporter la valeur dans `apps/web/.env.production`, champ `ODOO_API_KEY`.
Le frontend refuse de démarrer tant qu'elle est vide — volontairement : une clé
manquante doit arrêter le service au démarrage, pas produire un 503 sur la première
demande d'un client.

---

## 8. Reverse proxy Plesk — CRM

Le certificat est **déjà en place** : wildcard Let's Encrypt `*.dallytrading.com`,
valide jusqu'au 10/11/2026. Rien à émettre.

Plesk → Domaines → `crm.dallytrading.com` → **Paramètres Apache & nginx** :

1. décocher **Proxy mode** (nginx sert directement, Apache n'a rien à faire ici) ;
2. coller le contenu de
   [`infrastructure/nginx/crm.dallytrading.com.conf`](../infrastructure/nginx/crm.dallytrading.com.conf)
   dans « Directives nginx additionnelles » ;
3. appliquer.

Ce fichier bloque déjà `/web/database*` en défense en profondeur — `list_db = False`
reste la protection principale, mais une configuration Odoo peut être modifiée par
erreur lors d'une mise à jour.

Vérification :

```bash
curl -sI https://crm.dallytrading.com/ | head -3        # 200 attendu
curl -s -o /dev/null -w '%{http_code}\n' https://crm.dallytrading.com/web/database/manager  # 404 attendu
```

---

## 9. Démarrer le frontend

Le build doit être refait **après** avoir renseigné `.env.production` : Next inline les
`NEXT_PUBLIC_*` pendant `npm run build`. Les fournir seulement au démarrage produit un
site sans coordonnées, **sans aucune erreur**.

Depuis le compte projet :

```bash
cd /var/www/vhosts/dallytrading.com/platform/apps/web
export PATH=/var/www/vhosts/dallytrading.com/.nodenv/versions/22/bin:$PATH
node -v   # doit afficher v22.x — le même binaire que l'unité systemd
npm ci
npm run verify
npm run build
```

Le `PATH` est forcé sur node 22 pour une raison précise : le shim `nodenv` de ce
vhost retombe sur `/usr/bin/node` (v20.20.2) alors que l'unité systemd exécute
v22.23.2. Construire avec l'un et exécuter avec l'autre fonctionne ici — les deux
satisfont `engines: >=20.9.0` de Next 16.3 — mais c'est un écart gratuit, et le jour
où il cassera, le symptôme n'aura aucun rapport visible avec la cause.

Puis, en administrateur :

```bash
sudo cp /var/www/vhosts/dallytrading.com/platform/infrastructure/systemd/dallytrading-web.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dallytrading-web
sudo systemctl status dallytrading-web --no-pager
```

Le choix de systemd plutôt que PM2 ou Plesk Node.js est justifié en tête de l'unité.

Contrôles :

```bash
ss -lntp | grep 3010                       # 127.0.0.1:3010 uniquement
curl -sI http://127.0.0.1:3010/ | head -2  # 200 attendu
journalctl -u dallytrading-web -n 30 --no-pager
```

---

## 10. Reverse proxy Plesk — site

Plesk → Domaines → `dallytrading.com` → **Paramètres Apache & nginx** :

1. décocher **Proxy mode** ;
2. coller
   [`infrastructure/nginx/dallytrading.com.conf`](../infrastructure/nginx/dallytrading.com.conf) ;
3. appliquer.

État validé : le service tourne sur `127.0.0.1:3010`, le proxy est appliqué et la page publique répond 200.

Pour `www` : Plesk → `www.dallytrading.com` → redirection permanente 301 vers
`https://dallytrading.com`. Le DNS `www` existe déjà et le certificat wildcard le
couvre.

```bash
curl -sI https://dallytrading.com/      | head -3
curl -sI https://www.dallytrading.com/  | head -3   # 301 attendu
```

---

## 11. Recette intégration

Recette réelle validée le 13 août 2026. Objets créés puis contrôlés dans Odoo : contact `DT-2026-000065`, devis `DT-2026-000066`, sourcing `DT-SRC-2026-000122`, trading `DT-TRD-2026-000084`. Le suivi `DT-SHP-2026-000249` retourne uniquement la liste blanche publique avec le bon token. Le token synthétique de recette a ensuite été tourné ; token incorrect, absent, référence inconnue et énumération sont refusés sans révéler événements internes, notes, coûts, fournisseur, marge ni identifiants sensibles.


---

## 12. Confidentialité — à tester avec de vrais utilisateurs

Créer un utilisateur par groupe et vérifier **au niveau ORM**, pas seulement dans
l'interface : un champ masqué dans une vue est toujours dans le résultat de requête,
alors qu'un champ dont l'utilisateur n'a pas le `groups=` n'est jamais chargé.

```bash
docker exec -it dallytrading-odoo odoo shell -c /etc/odoo/odoo.conf -d dallytrading
```

```python
user = env['res.users'].search([('login', '=', 'trade.user@…')])
deal = env['dally.trade.opportunity'].search([], limit=1)
deal.with_user(user).read(['net_margin'])          # AccessError attendu
env['dally.trade.cost'].with_user(user).search([]) # AccessError attendu
```

À vérifier pour : Trade User, Trade Manager, Sourcing User, Sourcing Manager,
Commercial, Finance, utilisateur d'API, utilisateur sans groupe.

---

## 13. Sauvegardes

**Avant** de charger la moindre donnée réelle :

```bash
cd /var/www/vhosts/dallytrading.com/platform
./infrastructure/scripts/backup.sh
./infrastructure/scripts/verify-backup.sh <chemin_de_la_sauvegarde>
```

Base et filestore forment une seule sauvegarde logique. La restauration complète se fait uniquement avec le Compose isolé décrit dans [`RESTORE.md`](RESTORE.md).

```bash
docker compose -p dallytrading-restore --env-file .env -f infrastructure/docker-compose.restore.yml up -d
./infrastructure/scripts/restore.sh <chemin_de_la_sauvegarde> --isolated-test --replace-filestore --confirm-filestore-volume dallytrading_restore_odoo_filestore --yes
./infrastructure/scripts/verify-backup.sh <chemin_de_la_sauvegarde> --deep
```

Le mode `--isolated-test` est impératif pour cet exercice ; `--target-db` seul est refusé.

Planifier ensuite le quotidien avec les unités `dallytrading-backup.service` et `dallytrading-backup.timer`, selon [`BACKUPS.md`](BACKUPS.md). Ne pas ajouter de cron concurrent.

---

## 14. Contrôle de sortie

```bash
bash infrastructure/scripts/preflight.sh
```

Attendu à ce stade : **0 bloquant**, `https://dallytrading.com/ → 200`,
`https://crm.dallytrading.com/ → 200`.

Puis la revue manuelle :

- [ ] PostgreSQL sans port publié sur l'hôte
- [ ] 18169, 18172, 3010 en `127.0.0.1` uniquement
- [ ] `list_db = False`, `/web/database` en 404
- [ ] aucun secret dans les bundles `.next/static`
- [ ] aucun secret suivi par Git
- [ ] `dallytrading` est la seule base listée par Odoo
- [ ] `journalctl -u dallytrading-web` ne contient ni clé ni mot de passe

---

## 15. Git

Les changements de clôture sont commités et poussés uniquement sur `feature/sourcing-closure-and-trade`. Avant toute proposition vers `main`, exécuter :

```bash
git merge-base origin/main HEAD
git log --graph --oneline --decorate --all --max-count=40
```

Si aucun ancêtre commun existe, arrêter : ne pas créer de merge artificiel, ne pas utiliser `--allow-unrelated-histories` et ne jamais forcer `main`. Un merge exige une autorisation explicite.
