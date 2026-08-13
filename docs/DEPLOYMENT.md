# Déploiement

Procédure de référence et état validé de mise en place de l'instance Odoo 19 DallyTrading sur le serveur
`217.154.121.244` (Plesk Obsidian, Ubuntu 24.04).

Chaque étape indique le **niveau de privilège requis**. Les étapes marquées 🔒 ne
peuvent pas être exécutées depuis le compte d'hébergement `dallytrading.com_*` : elles
requièrent `root` ou un accès administrateur Plesk.

---

## Rappel de sécurité préalable

Ce serveur héberge une vingtaine de domaines en production, dont une instance Odoo 18
appartenant à un autre abonnement (`crm.sen-containers.com`, ports `18069`/`18072`).

- ❌ Ne jamais publier un conteneur sur les ports **80** ou **443** — Plesk les possède.
- ❌ Ne jamais utiliser les ports **18069** / **18072** — occupés.
- ❌ Ne jamais exécuter `docker compose -p dallytrading down -v` : `-v` détruit les volumes, donc la
  base et le filestore.
- ✅ Toujours passer `-p dallytrading`, `--env-file ../.env` et les **deux** fichiers Compose.

---

## Étape 1 — 🔒 Swap (constat DT-004)

Sans swap, un dépassement mémoire provoque un arrêt brutal par l'OOM-killer, qui peut
frapper un service d'un autre domaine hébergé.

```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
sysctl -w vm.swappiness=10
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
```

Contrôle — `Swap` ne doit plus être à `0B` :

```bash
free -h
```

## Étape 2 — 🔒 DNS

État validé le 13 août 2026 : `dallytrading.com`, `www.dallytrading.com` et `crm.dallytrading.com` résolvent. Ne modifier les enregistrements que pendant une intervention DNS planifiée.

## Étape 3 — 🔒 Certificats HTTPS

État validé le 13 août 2026 : certificats valides sur les trois noms, redirection HTTP vers HTTPS et HSTS actifs. Contrôle :

```bash
curl -sI https://dallytrading.com/
curl -sI https://crm.dallytrading.com/web/health
```

## Étape 4 — 🔒 Redirection www

État validé : `https://www.dallytrading.com/<chemin>` répond 301 vers `https://dallytrading.com/<chemin>` en conservant la query string. Le réglage se trouve dans Plesk, domaine `www.dallytrading.com`, type Hébergement = Redirection permanente 301.

## Étape 5 — 🔒 Accès Docker

Le compte applicatif dispose désormais de l’accès Docker nécessaire. Les commandes restent strictement limitées au projet `dallytrading`; le compte ne dispose pas de sudo.

Deux options :

**(a) Autoriser le compte** — le plus fluide pour l'exploitation courante :

```bash
usermod -aG docker dallytrading.com_02xd20o36s7
```

> ⚠️ L'appartenance au groupe `docker` équivaut de fait à un accès `root` sur la
> machine : le démon Docker tourne en root et permet de monter n'importe quel chemin de
> l'hôte. Sur un serveur mutualisé portant des données de production tierces, cette
> décision doit être prise en connaissance de cause.

**(b) Exécuter les commandes Docker en tant que `root`** — les fichiers du dépôt sont
lisibles depuis `root` sans élargir les privilèges du compte d'hébergement.

## Étape 6 — Secrets et configuration

Sans privilège particulier.

```bash
cd /var/www/vhosts/dallytrading.com/platform
./infrastructure/scripts/generate-secrets.sh
./infrastructure/scripts/render-config.sh
```

Contrôles :

```bash
ls -l .env odoo/config/odoo.conf        # attendu : -rw------- (0600)
git check-ignore -v .env odoo/config/odoo.conf   # les deux doivent être ignorés
git status --short                      # aucun secret ne doit apparaître
```

## Étape 7 — Démarrage de la stack

```bash
cd /var/www/vhosts/dallytrading.com/platform/infrastructure
docker compose -p dallytrading --env-file ../.env \
  -f docker-compose.yml -f docker-compose.production.yml config >/dev/null   # valide la syntaxe
docker compose -p dallytrading --env-file ../.env \
  -f docker-compose.yml -f docker-compose.production.yml up -d
```

Attendre que les deux services soient `healthy` (PostgreSQL ~30 s, Odoo jusqu'à 120 s) :

```bash
docker compose -p dallytrading ps
docker logs --tail 50 dallytrading-odoo
```

## Étape 8 — Initialisation de la base

```bash
docker exec -it dallytrading-odoo odoo -c /etc/odoo/odoo.conf \
    -d dallytrading -i base --without-demo=all --stop-after-init
docker restart dallytrading-odoo
```

Le rôle PostgreSQL est volontairement **sans `CREATEDB` ni `SUPERUSER`** : la base est
pré-créée par l'entrypoint PostgreSQL et lui appartient, Odoo n'a donc jamais besoin de
créer une base lui-même (§7).

Le test de restauration utilise le PostgreSQL dédié décrit dans [`RESTORE.md`](RESTORE.md). Aucun privilège de production temporaire est requis.

## Étape 9 — Contrôles de sécurité Odoo

**Impératif avant d'exposer le domaine.**

```bash
# Le Database Manager doit être fermé (§9, §91)
curl -s -o /dev/null -w 'manager  : %{http_code}\n' http://127.0.0.1:18169/web/database/manager
curl -s -X POST http://127.0.0.1:18169/web/database/list \
     -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","method":"call","params":{}}'
# Attendu : list_db=False → pas de liste de bases exploitable

# Aucun mot de passe en ligne de commande (constat DT-003) — doit ne rien renvoyer
ps aux | grep -- '--db_password' | grep -v grep

# PostgreSQL ne doit pas être joignable depuis l'extérieur du réseau Docker
ss -tlnp | grep -E ':5432' | grep -v '127.0.0.1'   # doit ne rien renvoyer
```

Changer le mot de passe de l'utilisateur `admin` Odoo dès la première connexion.

## Étape 10 — 🔒 Reverse proxy Plesk

**Plesk → crm.dallytrading.com → Paramètres Apache & nginx** :

1. **Décocher** « Proxy mode » — nginx sert directement, Apache n'intervient pas.
2. Coller le contenu de
   [`infrastructure/nginx/crm.dallytrading.com.conf`](../infrastructure/nginx/crm.dallytrading.com.conf)
   dans **« Directives nginx additionnelles »**.
3. Appliquer. Plesk valide la syntaxe et refuse une configuration invalide.

Les deux reverse proxies sont appliqués et validés : Next.js sur `127.0.0.1:3010`, Odoo sur `127.0.0.1:18169` et websocket sur `127.0.0.1:18172`.

## Étape 11 — Validation de bout en bout

Critères du §88 :

```bash
# HTTPS opérationnel sur le CRM
curl -o /dev/null -w 'crm : %{http_code} ssl=%{ssl_verify_result}\n' https://crm.dallytrading.com/

# Database Manager inaccessible publiquement
curl -o /dev/null -w 'manager : %{http_code}\n' https://crm.dallytrading.com/web/database/manager
# Attendu : 404

# PostgreSQL non joignable publiquement
nc -zv -w3 217.154.121.244 5432    # doit échouer

# Redémarrage ciblé du seul service Odoo
docker compose -p dallytrading --env-file ../.env -f docker-compose.yml -f docker-compose.production.yml restart odoo
sleep 60 && curl -sf http://127.0.0.1:18169/web/health && echo OK
```

## Étape 12 — Sauvegardes planifiées

La sauvegarde réelle `production-release/20260813T192539Z` et sa restauration isolée sont validées. Le timer systemd quotidien fourni sauvegarde, vérifie, journalise et applique la rétention. Son installation root est décrite exactement dans [`BACKUPS.md`](BACKUPS.md). Ne pas installer une tâche cron concurrente.

---

## Récapitulatif des étapes privilégiées

| Étape | Objet | Requiert |
|---|---|---|
| 1 | Swap 4 Gi | `root` |
| 2 | DNS `www` | Plesk |
| 3 | Certificats Let's Encrypt | Plesk |
| 4 | Redirection `www` | Plesk |
| 5 | Accès Docker | `root` |
| 10 | Directives nginx | Plesk |

Les étapes 6 à 9, 11 et 12 s'exécutent depuis le compte d'hébergement, une fois
l'étape 5 réglée.

## Retour arrière

```bash
# Arrêt SANS destruction de données — jamais l'option -v
docker compose -p dallytrading --env-file ../.env -f docker-compose.yml -f docker-compose.production.yml down

# Les volumes dallytrading_postgres_data et dallytrading_odoo_filestore survivent
docker volume ls | grep dally
```

Côté Plesk, vider le champ « Directives nginx additionnelles » et appliquer : le
domaine revient à son comportement par défaut sans toucher aux autres domaines.
