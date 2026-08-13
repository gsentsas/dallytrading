# Constats de sécurité — audit d'infrastructure

**Date de l'audit :** 12 août 2026
**Périmètre :** serveur `217.154.121.244` (Plesk Obsidian 18.0.80.2, Ubuntu 24.04.4 LTS)
**Auteur :** audit technique préalable au projet DallyTrading

> **Note de périmètre.** Les constats DT-001 à DT-003 concernent l'instance Odoo
> **SEN CONTAINERS**, explicitement **hors périmètre** du projet DallyTrading. Ils sont
> consignés ici à titre de signalement écrit, conformément à la décision du
> commanditaire. **Aucune modification n'a été apportée à cette instance**, et le
> système DallyTrading ne la lit, ne l'interroge et ne s'y connecte en aucune façon.
> Leur traitement relève du responsable de `sen-containers.com`.

---

## DT-001 — Database Manager Odoo exposé publiquement

| | |
|---|---|
| **Gravité** | 🔴 Critique |
| **Système** | `https://crm.sen-containers.com` (Odoo 18.0, base `sen_containers_crm`) |
| **Statut** | ⚠️ Non corrigé — hors périmètre |

### Constat

Le gestionnaire de bases de données d'Odoo est accessible sans authentification
préalable depuis Internet :

```text
GET https://crm.sen-containers.com/web/database/manager   →  HTTP 200
```

### Impact

Le Database Manager expose les opérations `create`, `duplicate`, `drop`, `backup` et
`restore`. Elles sont protégées par le seul `admin_passwd` (master password) du fichier
`odoo.conf`. En conséquence :

- **Destruction de données** — `drop` supprime la base de production.
- **Exfiltration complète** — `backup` télécharge l'intégralité de la base et du
  filestore : contacts, devis, tarifs, marges, documents commerciaux.
- **Aucune limitation de tentatives** — le master password peut être attaqué par force
  brute sans verrouillage ni temporisation, Odoo n'implémentant pas de *rate limiting*
  sur ce formulaire.

La compromission ne requiert qu'un seul secret, sans compte utilisateur valide.

### Correctif recommandé

1. `list_db = False` dans `odoo.conf`, puis redémarrage d'Odoo.
2. Blocage réseau en défense en profondeur, dans les directives nginx du domaine :
   ```nginx
   location /web/database { deny all; return 404; }
   ```
3. Rotation du `admin_passwd` vers une valeur d'au moins 32 octets aléatoires.
4. Vérification post-correctif :
   ```bash
   curl -o /dev/null -w '%{http_code}\n' https://crm.sen-containers.com/web/database/manager
   # Attendu : 404
   ```

Un modèle de configuration appliquant ces trois mesures est fourni pour l'instance
DallyTrading : [`infrastructure/nginx/crm.dallytrading.com.conf`](../infrastructure/nginx/crm.dallytrading.com.conf)
et [`odoo/config/odoo.conf.template`](../odoo/config/odoo.conf.template).

---

## DT-002 — Énumération publique des bases de données

| | |
|---|---|
| **Gravité** | 🟠 Élevée |
| **Système** | `https://crm.sen-containers.com` |
| **Statut** | ⚠️ Non corrigé — hors périmètre |

### Constat

Le point d'accès de listage des bases répond sans authentification :

```bash
curl -X POST https://crm.sen-containers.com/web/database/list \
     -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","method":"call","params":{}}'
```
```json
{"jsonrpc": "2.0", "id": null, "result": ["sen_containers_crm"]}
```

### Impact

Le nom exact de la base de production est divulgué. C'est un prérequis opérationnel
pour exploiter DT-001 : les opérations `drop`, `duplicate` et `backup` exigent le nom
de la base. Ce constat transforme DT-001 d'une attaque nécessitant de la devinette en
une attaque directement ciblée.

### Correctif recommandé

`list_db = False` corrige simultanément DT-001 et DT-002. Ajouter `dbfilter` en
expression exacte (`dbfilter = ^sen_containers_crm$`) pour verrouiller le service à
cette seule base.

---

## DT-003 — Mot de passe de base de données lisible via `ps`

| | |
|---|---|
| **Gravité** | 🟠 Élevée |
| **Système** | Instance Odoo 18 (processus hôte) |
| **Statut** | ⚠️ Non corrigé — hors périmètre |

### Constat

Le mot de passe PostgreSQL est passé en argument de ligne de commande et donc visible
par **tout utilisateur du serveur**, y compris les comptes d'hébergement mutualisé :

```text
/usr/bin/python3 /usr/bin/odoo --db_host db --db_port 5432 --db_user odoo \
  --db_password <48 caractères hexadécimaux, lisibles en clair>
```

Constaté depuis un compte non privilégié (`uid=10016`, groupe `psacln`), sans `sudo`.

> **La valeur réelle est délibérément absente de ce document.** Il s'agit d'un
> identifiant de production appartenant à un abonnement tiers, et ce dépôt est publié
> sur GitHub : l'y recopier transformerait un constat de sécurité en divulgation.
> Le constat ne dépend pas de la valeur — il porte sur le fait qu'elle soit lisible.
> Elle est reproductible en une commande par l'administrateur du serveur.

### Cause

L'`entrypoint.sh` de l'image Docker Odoo officielle lit les paramètres de connexion
dans `odoo.conf` puis **les repasse en arguments de ligne de commande** à l'exécutable
`odoo`. Le comportement est celui de l'image amont, pas une erreur de configuration
locale.

### Impact

Ce serveur héberge une vingtaine de domaines appartenant à des abonnements distincts.
Tout compte d'hébergement de la machine peut lire ce mot de passe. Combiné à un accès
au réseau Docker, il autorise une connexion directe à la base de production.

### Correctif appliqué côté DallyTrading

L'instance DallyTrading contourne l'`entrypoint` de l'image :

```yaml
entrypoint: ["odoo"]
command: ["-c", "/etc/odoo/odoo.conf"]
```

Les secrets restent exclusivement dans `odoo.conf` en mode `0600`, généré depuis un
modèle par [`render-config.sh`](../infrastructure/scripts/render-config.sh). La
synchronisation au démarrage, normalement assurée par l'`entrypoint`, est reprise par
`depends_on: condition: service_healthy`.

Vérification après déploiement — **doit ne rien renvoyer** :

```bash
ps aux | grep -- '--db_password' | grep -v grep
```

---

## DT-004 — Absence de swap : risque d'arrêt brutal par l'OOM-killer

| | |
|---|---|
| **Gravité** | 🟡 Moyenne |
| **Système** | Hôte `217.154.121.244` |
| **Statut** | ⚠️ Ouvert — action requise avant mise en production |

### Constat

```text
Swap:  0B  0B  0B
```

Aucun espace d'échange n'est configuré, pour 23 Gi de mémoire physique.

### Impact

Sans swap, un dépassement mémoire ne provoque pas un ralentissement mais une
**terminaison immédiate** par le noyau. Deux conséquences pour ce projet :

1. Le mécanisme `limit_memory_soft` d'Odoo suppose de pouvoir recycler proprement un
   worker en fin de requête. Sans marge mémoire, l'OOM-killer intervient avant.
2. L'OOM-killer sélectionne sa cible sur un score heuristique, **pas** sur le processus
   responsable. Il peut donc arrêter PostgreSQL, Plesk ou un service appartenant à un
   autre domaine hébergé.

### Correctif recommandé

Créer 4 Gi de swap (requiert `root`) :

```bash
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
sysctl -w vm.swappiness=10        # swap en filet de sécurité, non en usage courant
```

---

## DT-005 — Absence de sauvegardes Odoo vérifiables

| | |
|---|---|
| **Gravité** | 🟡 Moyenne |
| **Système** | `/opt/odoo-crm/backups` |
| **Statut** | ℹ️ Constat — traité côté DallyTrading |

### Constat

L'arborescence `/opt/odoo-crm/{config,addons,backups}` existe (créée le 2 mai 2026)
mais ses trois répertoires sont **vides**. L'instance Odoo 18 en production stocke ses
données dans des volumes Docker et aucun artefact de sauvegarde n'est déposé à cet
emplacement. Aucune tâche planifiée de sauvegarde Odoo n'a pu être observée depuis un
compte non privilégié.

Le gestionnaire de sauvegardes de Plesk peut couvrir les fichiers et les bases
MySQL/PostgreSQL déclarés dans Plesk ; il ne couvre **pas** les volumes Docker, ni la
cohérence base ↔ filestore d'Odoo.

### Traitement côté DallyTrading

Sauvegarde atomique base + filestore, empreintes SHA-256, manifeste et rétention échelonnée. La copie distante chiffrée est optionnelle et reste inactive sans configuration S3 complète :
[`backup.sh`](../infrastructure/scripts/backup.sh),
[`verify-backup.sh`](../infrastructure/scripts/verify-backup.sh),
[`restore.sh`](../infrastructure/scripts/restore.sh).
Procédure exercice de restauration : [`RESTORE.md`](RESTORE.md). Le 13 août 2026, le backup réel `production-release/20260813T192539Z` a passé ses contrôles puis a été restauré en 13 s dans des volumes, une base et un réseau dédiés, sans port publié ni accès aux ressources de production.

---

## DT-006 — Token de tracking présent dans les journaux URL

| | |
|---|---|
| **Gravité** | 🟡 Moyenne |
| **Système** | Tracking public DallyTrading |
| **Statut** | ⚠️ Risque restant documenté |

Le lien de capacité utilise actuellement les paramètres `ref` et `t`. Odoo et les reverse proxies peuvent journaliser la query string complète dans leurs logs accès. Aucun token ne figure dans le payload public, mais un opérateur ayant accès aux logs peut retrouver un lien encore valide. Le token de expédition synthétique utilisé pendant la recette a été tourné immédiatement après le constat, rendant la valeur observée inutilisable.

Traitement recommandé hors clôture : transporter le secret hors URL ou appliquer une politique de redaction des query strings sur Plesk et Odoo, protéger la lecture des logs, réduire leur rétention et tourner tout token suspect.

---

## Récapitulatif

| Réf. | Gravité | Objet | Périmètre | Statut |
|---|---|---|---|---|
| DT-001 | 🔴 Critique | Database Manager public | SEN CONTAINERS | Signalé, non traité |
| DT-002 | 🟠 Élevée | Liste des bases publique | SEN CONTAINERS | Signalé, non traité |
| DT-003 | 🟠 Élevée | Mot de passe DB dans `ps` | SEN CONTAINERS | Signalé, non traité |
| DT-004 | 🟡 Moyenne | Aucun swap | Hôte partagé | Action requise (root) |
| DT-005 | 🟡 Moyenne | Sauvegardes Odoo absentes | Hôte / SEN CONTAINERS | Traité côté DallyTrading |

**Aucune modification n'a été apportée à l'instance SEN CONTAINERS ni à la
configuration de l'hôte** dans le cadre de cet audit. Toutes les vérifications
effectuées ont été en lecture seule.
