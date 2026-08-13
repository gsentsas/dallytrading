# Runbook — mise en service DallyTrading

Procédure exacte pour rendre `dallytrading.com` et `crm.dallytrading.com`
réellement opérationnels.

> **Ce document existe parce que le compte applicatif ne peut pas exécuter ces
> commandes.** L'audit du 13/08/2026 a établi que `dallytrading.com_02xd20o36s7`
> (uid 10016, groupe `psacln`) n'a ni `sudo` utilisable en non-interactif, ni accès au
> socket Docker, ni droit d'exécuter `plesk bin`. Tout ce qui pouvait être préparé sans
> privilèges l'a été ; ce qui suit demande un administrateur.

---

## 0. Avant de commencer

Ce serveur héberge **une vingtaine de domaines en production** et une instance Odoo
tierce (SEN CONTAINERS, base `sen_containers_crm`, ports 18069/18072). Aucune commande
de ce runbook ne doit la toucher.

Trois interdits absolus :

| Interdit | Conséquence si transgressé |
|---|---|
| Publier un conteneur sur les ports 80 ou 443 | Coupe **tous** les domaines de la machine |
| `docker compose down -v` | Détruit les volumes, donc la base |
| Toucher aux conteneurs, volumes ou base SEN CONTAINERS | Incident sur un abonnement tiers |

Contrôle de pré-vol, **en lecture seule**, à lancer avant et après :

```bash
cd /var/www/vhosts/dallytrading.com/platform && bash infrastructure/scripts/preflight.sh
```

État au 13/08/2026 : **28 contrôles OK, 1 bloquant** — l'accès Docker, qui est
précisément l'objet de ce runbook.

---

## 1. Débloquer le compte applicatif

Deux façons ; la première est préférable.

### Option A — donner l'accès Docker au compte projet (recommandé)

```bash
sudo usermod -aG docker dallytrading.com_02xd20o36s7
```

L'appartenance ne prend effet qu'à la prochaine session. Vérifier ensuite,
**depuis le compte projet** :

```bash
docker info >/dev/null && echo "accès Docker OK"
```

> Le groupe `docker` équivaut à un accès root sur la machine. C'est un choix
> délibéré et réversible (`sudo gpasswd -d dallytrading.com_02xd20o36s7 docker`),
> à ne faire que si vous acceptez cette équivalence. Les comptes
> `sen-containers` et `sen-trafic.com_tdvsu2xs6sq` y figurent déjà.

### Option B — l'administrateur exécute tout

Ne rien changer aux droits, et exécuter chaque commande ci-dessous en `sudo`.
Plus sûr, mais chaque itération de correction repasse par vous.

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
docker compose --env-file ../.env \
  -f docker-compose.yml -f docker-compose.production.yml up -d
docker compose ps
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

**C'est l'étape que rien n'a encore prouvée.** Les 109 tests de `dally_sourcing` et
`dally_trade` sont écrits mais n'ont jamais tourné sur une instance Odoo 19.

Module par module :

```bash
for M in dally_core dally_crm dally_api dally_freight dally_sourcing dally_tracking dally_trade; do
  echo "════ tests : $M"
  docker exec dallytrading-odoo odoo -c /etc/odoo/odoo.conf \
    -d dallytrading -u "$M" --test-enable --test-tags "/$M" \
    --stop-after-init --log-level=test 2>&1 | tail -30
done
```

Puis la suite complète marquée `dally` :

```bash
docker exec dallytrading-odoo odoo -c /etc/odoo/odoo.conf \
  -d dallytrading --test-enable --test-tags dally --stop-after-init \
  --log-level=test 2>&1 | tee /tmp/dally-tests.log
grep -E '(FAIL|ERROR|failed|tests? in)' /tmp/dally-tests.log
```

> **Un test qui échoue doit être analysé, pas neutralisé.** Si Odoo 19 a changé une
> API, adapter le code. Si le comportement métier est faux, corriger le code — pas le
> test. Les points les plus susceptibles de diverger de nos hypothèses statiques :
> `_sql_constraints`, la signature `product_uom` / `product_uom_id` sur les lignes de
> commande, `res.users.has_group`, la syntaxe `<chatter/>` des vues, et le
> comportement exact de `groups=` sur un champ lu explicitement.

---

## 7. Créer la clé d'API

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

**Ne pas activer avant que le service ne tourne** : le site renverrait 502 au lieu du
403 actuel.

Pour `www` : Plesk → `www.dallytrading.com` → redirection permanente 301 vers
`https://dallytrading.com`. Le DNS `www` existe déjà et le certificat wildcard le
couvre.

```bash
curl -sI https://dallytrading.com/      | head -3
curl -sI https://www.dallytrading.com/  | head -3   # 301 attendu
```

---

## 11. Recette d'intégration

À faire depuis un navigateur, avec le vrai Odoo — plus de faux Odoo à ce stade.

| Page | Action | Vérification dans Odoo |
|---|---|---|
| `/contact` | Envoyer une demande | Une `crm.lead` apparaît |
| `/devis` | Le catalogue de services se remplit | Il vient de `dally.service.type`, pas d'un repli en dur |
| `/devis` | Déposer une demande | `dally.quote.request` avec référence `DT-…` |
| `/devis` | Renvoyer le même formulaire | **Aucun doublon** (idempotence sur `request_uuid`) |
| `/sourcing` | Déposer une demande | `dally.sourcing.request`, référence `DT-SRC-…` |
| `/trading` | Proposer une opération | `dally.trade.opportunity`, référence `DT-TRD-…` |
| `/tracking` | Suivre une expédition de test | Timeline publique, **aucun** événement interne |

Pour le suivi : créer une `dally.shipment` dans Odoo, y ajouter un événement public et
un événement interne, relever `reference` et `public_tracking_token`, puis vérifier que
seul l'événement public ressort.

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
# verify-backup.sh attend le chemin de la sauvegarde à contrôler.
# Sans --deep, il ne vérifie que la forme : la restaurabilité n'est PAS prouvée.
./infrastructure/scripts/verify-backup.sh <chemin_de_la_sauvegarde> --deep
```

Base et filestore forment **une seule sauvegarde logique** : un dump sans son filestore
produit des pièces jointes orphelines.

Puis prouver la restauration sur une base jetable — une sauvegarde dont la restauration
n'a jamais été testée n'est pas une sauvegarde :

```bash
./infrastructure/scripts/restore.sh <chemin_de_la_sauvegarde> \
  --target-db dallytrading_restore_test
```

`--target-db` est impératif : sans lui, la restauration écrase `dallytrading`.

Planifier ensuite le quotidien :

```bash
sudo crontab -e
# 0 3 * * * /var/www/vhosts/dallytrading.com/platform/infrastructure/scripts/backup.sh
```

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

## 15. GitHub

Le dépôt local n'a **jamais été poussé**. Une clé de déploiement a été générée sur le
compte projet ; elle doit être autorisée sur `gsentsas/dallytrading` :

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP5l3HnxQSDVsArFwChg6pK7JLfzbOhiic05Y5KJm86O dallytrading-deploy@friendly-brahmagupta
```

GitHub → dépôt → **Settings → Deploy keys → Add deploy key**, en cochant
**Allow write access**.

Puis, depuis le compte projet :

```bash
cd /var/www/vhosts/dallytrading.com/platform
ssh -T git@github.com                       # doit saluer, pas refuser
git push -u origin main
git push -u origin feature/sourcing-closure-and-trade
```

> **L'historique a été réécrit** avant ce premier push : il contenait le mot de passe
> PostgreSQL de production de SEN CONTAINERS, recopié dans le constat DT-003. Comme
> rien n'avait jamais été poussé, la purge était sans conséquence. Les empreintes ont
> changé : `206b4f9 → f6e31f6`, `2e4c118 → c252e6b`, `d721ea2 → b5b3da9`. Une
> sauvegarde de l'état antérieur existe hors du dépôt, dans le répertoire de travail
> temporaire de la session.

Le merge vers `main` n'intervient qu'après les étapes 6, 9 et 11 : tests Odoo passants,
frontend en service, intégration démontrée. Jamais de `--force` sur `main`.
