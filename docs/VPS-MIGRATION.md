# Déploiement sur VPS dédié

Procédure complète pour installer DallyTrading sur un **VPS dédié**, soit en
installation neuve, soit en migration depuis l'hébergement Plesk mutualisé actuel.

> ⚠️ **Aucune commande de ce document n'a été exécutée.** Elles requièrent `root`
> sur un serveur qui n'existe pas encore. Elles sont écrites pour être lancées
> telles quelles, mais doivent être validées avant application — en particulier la
> section 9 (bascule DNS), qui est le point de non-retour.

---

## 1. Pourquoi un VPS dédié change l'architecture

L'installation actuelle est contrainte par Plesk. Sur un VPS dédié, trois
décisions s'inversent.

| | Plesk mutualisé (actuel) | VPS dédié (cible) |
|---|---|---|
| Reverse proxy | nginx de Plesk, configuré à la main dans l'interface | **Conteneur Caddy ou nginx**, versionné dans Git |
| Certificats | Let's Encrypt via Plesk | **Automatiques** dans le conteneur proxy |
| Ports 80/443 | possédés par Plesk, interdits | **disponibles** |
| Ports Odoo | 18169/18172 pour éviter une collision | **8069/8072**, les ports par défaut |
| Voisinage | ~20 domaines + un ERP tiers | **isolé** |
| Ressources | 12 vCPU / 23 Gi partagés | dédiées, à dimensionner |
| Déploiement | manuel, partiellement par interface | **entièrement scripté** |

Le gain décisif n'est pas la performance : c'est que **l'infrastructure devient
reproductible**. Sur Plesk, la configuration du reverse proxy vit dans un champ
de formulaire et ne peut être ni versionnée, ni testée, ni redéployée — ADR-001.

## 2. Dimensionnement recommandé

| Profil | vCPU | RAM | Disque | Usage |
|---|---|---|---|---|
| Minimum viable | 4 | 8 Gi | 80 Gi SSD | MVP, < 10 utilisateurs Odoo |
| **Recommandé** | **8** | **16 Gi** | **160 Gi SSD** | production, 10–30 utilisateurs |
| Confort | 8+ | 32 Gi | 320 Gi SSD | e-commerce actif, gros filestore |

Le disque est le paramètre à surveiller : le filestore grossit avec chaque
document de fret scanné, et les sauvegardes locales occupent un multiple de la
base. Prévoir large, ou un volume séparé pour `/opt/dallytrading/backups`.

Avec 8 vCPU dédiés, le dimensionnement Odoo peut passer à `workers = 9`
(formule `(2 × vCPU) + 1`), contre 4 aujourd'hui — ADR-006. Le calcul n'est
valable que parce que la machine est dédiée.

## 3. Préparation du serveur

Ubuntu 24.04 LTS, pour rester aligné sur l'environnement actuel.

```bash
# ─── Mises à jour ────────────────────────────────────────────────
apt update && apt upgrade -y
apt install -y ca-certificates curl gnupg git ufw fail2ban unattended-upgrades

# ─── Fuseau horaire ──────────────────────────────────────────────
timedatectl set-timezone Africa/Dakar

# ─── Swap (constat DT-004) ───────────────────────────────────────
# À faire dès l'installation : sans swap, un pic mémoire tue un processus
# au lieu de ralentir.
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
sysctl --system

# ─── Utilisateur de déploiement ──────────────────────────────────
# Le service ne tourne pas sous root, et l'appartenance au groupe docker
# équivaut à un accès root : elle est réservée à ce compte dédié.
adduser --disabled-password --gecos "DallyTrading deploy" dally
usermod -aG docker dally   # après l'installation de Docker (§4)
```

### Durcissement SSH

```bash
# /etc/ssh/sshd_config.d/99-dally.conf
cat > /etc/ssh/sshd_config.d/99-dally.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
X11Forwarding no
MaxAuthTries 3
AllowUsers dally
EOF

# Déposer la clé publique AVANT de recharger, sous peine de se verrouiller dehors.
mkdir -p /home/dally/.ssh && chmod 700 /home/dally/.ssh
# ... copier la clé dans /home/dally/.ssh/authorized_keys ...
chown -R dally:dally /home/dally/.ssh
chmod 600 /home/dally/.ssh/authorized_keys

sshd -t && systemctl reload ssh
```

> Vérifier la connexion depuis une **seconde session** avant de fermer la
> première. Une erreur dans ce fichier avec `PasswordAuthentication no` rend le
> serveur inaccessible.

### Pare-feu (§13)

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    comment 'SSH'
ufw allow 80/tcp    comment 'HTTP (redirection + ACME)'
ufw allow 443/tcp   comment 'HTTPS'
ufw --force enable
ufw status verbose
```

Rien d'autre n'est ouvert : PostgreSQL, Odoo et Next.js ne sont joignables que
depuis le réseau Docker ou la loopback.

> ⚠️ Docker écrit directement dans `iptables` et **contourne UFW** pour les ports
> publiés. C'est un piège classique : `ufw deny 5432` ne protège pas un conteneur
> lancé avec `-p 5432:5432`. La protection réelle est de **ne pas publier** le
> port — ce que fait déjà `docker-compose.yml` pour PostgreSQL. Ne jamais ajouter
> de publication de port sans vérifier `ss -tlnp` ensuite.

### Fail2ban

```bash
cat > /etc/fail2ban/jail.d/dally.conf <<'EOF'
[sshd]
enabled = true
maxretry = 4
bantime = 1h
findtime = 10m
EOF
systemctl enable --now fail2ban
```

## 4. Docker

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# Borner les journaux : sans cela ils remplissent le disque en silence.
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" },
  "live-restore": true
}
EOF
systemctl restart docker

docker --version && docker compose version
```

## 5. Arborescence

Sur un VPS dédié, `/opt` est accessible : l'arborescence du §6 du cahier des
charges s'applique enfin sans compromis.

```bash
mkdir -p /opt/dallytrading/{backups,logs}
chown -R dally:dally /opt/dallytrading

sudo -u dally -H bash <<'EOS'
cd /opt/dallytrading
git clone <URL_DU_DEPOT> platform
cd platform
./infrastructure/scripts/generate-secrets.sh
EOS
```

Ajuster `BACKUP_DIR=/opt/dallytrading/backups` dans `.env`.

## 6. Adaptation de la configuration

Trois changements par rapport au déploiement Plesk.

**a. Ports Odoo par défaut** — plus de collision à éviter :

```env
ODOO_HTTP_PORT=8069
ODOO_LONGPOLLING_PORT=8072
```

**b. Dimensionnement pour une machine dédiée** (profil 8 vCPU / 16 Gi) :

```env
ODOO_WORKERS=9
ODOO_MAX_CRON_THREADS=2
ODOO_LIMIT_MEMORY_SOFT=2147483648    # 2.0 Gi
ODOO_LIMIT_MEMORY_HARD=2684354560    # 2.5 Gi
ODOO_MEM_LIMIT=12g
POSTGRES_MEM_LIMIT=6g
```

Pire cas : `9 × 2.5 Gi ≈ 22 Gi`. Au-delà des 16 Gi physiques — c'est voulu : les
workers Odoo n'atteignent jamais leur plafond simultanément, et `limit_memory_soft`
les recycle bien avant. Avec 4 Gi de swap comme filet. Sur un profil 8 Gi, revenir
à `ODOO_WORKERS=4`.

**c. Publication sur la loopback uniquement** — inchangé. Le proxy conteneurisé
joint Odoo par le réseau Docker, pas par l'hôte. Dans
`docker-compose.production.yml`, on peut même supprimer entièrement la section
`ports` du service `odoo` : plus rien n'a besoin d'y accéder depuis l'hôte.

## 7. Reverse proxy conteneurisé

C'est ici que le VPS dédié apporte le plus : la configuration redevient du code.

**Caddy** est recommandé plutôt que nginx pour ce rôle : il gère Let's Encrypt
(émission, renouvellement, agrafage OCSP) sans cron ni script, et sa configuration
tient en quelques lignes au lieu de quelques dizaines.

`infrastructure/docker-compose.vps.yml` (à créer lors de la migration) :

```yaml
services:
  caddy:
    image: caddy:2.10-alpine
    container_name: dally-caddy
    restart: always
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"      # HTTP/3
    volumes:
      - ../infrastructure/caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data    # certificats — À SAUVEGARDER
      - caddy-config:/config
    networks:
      - dallytrading_public
    depends_on:
      odoo:
        condition: service_healthy

volumes:
  caddy-data:
  caddy-config:
```

`infrastructure/caddy/Caddyfile` :

```caddyfile
{
	email admin@dallytrading.com
}

# Redirection www — 301 permanent
www.dallytrading.com {
	redir https://dallytrading.com{uri} permanent
}

dallytrading.com {
	encode zstd gzip

	header {
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		-Server
		# HSTS : à décommenter APRÈS validation du HTTPS (§12).
		# Une fois envoyé, l'en-tête est mémorisé par les navigateurs pour
		# toute sa durée — une erreur rend le domaine inaccessible des mois.
		# Strict-Transport-Security "max-age=31536000; includeSubDomains"
	}

	handle /api/* {
		reverse_proxy web:3010
	}
	handle {
		reverse_proxy web:3010
	}
}

crm.dallytrading.com {
	encode zstd gzip

	header {
		X-Content-Type-Options nosniff
		X-Frame-Options SAMEORIGIN
		-Server
	}

	# Database Manager fermé (§9, §91), en plus de list_db = False.
	@dbmanager path /web/database*
	respond @dbmanager 404

	# API RPC historique fermée : non utilisée (ADR-008).
	@legacyrpc path /xmlrpc* /jsonrpc*
	respond @legacyrpc 404

	# Bus temps réel (Discuss, notifications).
	@websocket path /websocket /longpolling*
	reverse_proxy @websocket odoo:8072

	# Assets Odoo : immuables, empreinte dans l'URL.
	@static path /web/static/*
	handle @static {
		header Cache-Control "public, max-age=604800, immutable"
		reverse_proxy odoo:8069
	}

	reverse_proxy odoo:8069 {
		# Odoo tourne avec proxy_mode = True et s'appuie sur ces en-têtes.
		header_up X-Real-IP {remote_host}
		# Import de données et génération PDF dépassent 60 s.
		transport http {
			read_timeout 720s
			write_timeout 720s
		}
	}

	request_body {
		max_size 100MB
	}
}
```

Caddy remplace intégralement `infrastructure/nginx/*.conf`, qui devient
spécifique au déploiement Plesk. **Conserver les deux** tant que la migration
n'est pas terminée.

> Le volume `caddy-data` contient les certificats et leurs clés privées. Il doit
> entrer dans le périmètre de sauvegarde : le perdre signifie réémettre tous les
> certificats, et Let's Encrypt applique des quotas par domaine.

## 8. Service Next.js

Sur Plesk, Next.js tourne comme processus hôte. Sur le VPS, il devient un
conteneur — même cycle de vie que le reste.

Point vérifié en pratique : `next.config.mjs` fixe `output: 'standalone'`, et
**`next start` est alors inopérant**. Next l'annonce explicitement au démarrage :

```text
⚠ "next start" does not work with "output: standalone" configuration.
  Use "node .next/standalone/server.js" instead.
```

La commande de production est donc `node server.js` depuis le répertoire
standalone, ce que reflète le Dockerfile ci-dessous.

`apps/web/Dockerfile` (à créer lors de la migration) :

```dockerfile
# ─── Dépendances ───────────────────────────────────────────────
FROM node:20.20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# npm ci : installation reproductible depuis le lock, contrairement à npm install.
RUN npm ci --omit=dev --ignore-scripts

# ─── Build ─────────────────────────────────────────────────────
FROM node:20.20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ─── Exécution ─────────────────────────────────────────────────
FROM node:20.20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3010 HOSTNAME=0.0.0.0
# Utilisateur non-root : un conteneur compromis ne doit pas être root.
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
USER nextjs
EXPOSE 3010
# Conforme à l'avertissement ci-dessus : le serveur standalone, pas next start.
CMD ["node", "server.js"]
```

Service correspondant :

```yaml
  web:
    build:
      context: ../apps/web
    container_name: dally-web
    restart: always
    environment:
      NEXT_PUBLIC_SITE_URL: ${NEXT_PUBLIC_SITE_URL}
      ODOO_GATEWAY_ADAPTER: ${ODOO_GATEWAY_ADAPTER}
      # Appel interne au réseau Docker : ne traverse pas Internet et ne dépend
      # donc pas d'un certificat public.
      ODOO_URL: http://odoo:8069
      ODOO_DATABASE: ${ODOO_DATABASE}
      ODOO_API_KEY: ${ODOO_API_KEY}
    networks:
      - dallytrading_public
    depends_on:
      odoo:
        condition: service_healthy
```

> `ODOO_URL` devient `http://odoo:8069`. Avec `allowed_ips` sur la clé API,
> l'adresse autorisée n'est alors plus `127.0.0.1` mais l'IP du conteneur `web`
> sur le réseau Docker. Le plus simple est de vider `allowed_ips` et de s'appuyer
> sur l'isolation réseau : `dallytrading_public` n'est pas routable depuis Internet.

## 9. Migration des données

C'est la seule séquence irréversible. Elle suppose l'instance Plesk **déjà en
production** ; pour une installation neuve, passer directement au §10.

### Préparation (sans coupure)

```bash
# 1. Abaisser le TTL DNS 24 h à l'avance, pour que la bascule soit rapide.
#    Passer le TTL de dallytrading.com et crm.dallytrading.com à 300 s.

# 2. Déployer la stack complète sur le VPS, sans DNS. Tester par /etc/hosts.
#    Le site doit être entièrement fonctionnel avant toute bascule.
```

### Bascule (fenêtre de coupure)

```bash
# ─── Sur l'ancien serveur (Plesk) ────────────────────────────────
cd /var/www/vhosts/dallytrading.com/platform

# 3. Passer Odoo en lecture seule de fait : arrêter le site pour qu'aucune
#    demande n'arrive après la sauvegarde et ne soit perdue.
docker stop dally-web 2>/dev/null || true

# 4. Sauvegarde finale, base + filestore, atomique.
./infrastructure/scripts/backup.sh --tag migration

BACKUP=$(find backups/migration -mindepth 1 -maxdepth 1 -type d | sort -r | head -1)

# 5. Vérifier AVANT de transférer : une sauvegarde corrompue découverte
#    sur la cible signifie recommencer la coupure.
./infrastructure/scripts/verify-backup.sh "$BACKUP" --deep

# 6. Transfert
rsync -avz --progress "$BACKUP/" dally@NOUVEAU_VPS:/opt/dallytrading/backups/migration/final/

# ─── Sur le nouveau VPS ──────────────────────────────────────────
cd /opt/dallytrading/platform

# 7. Démarrer PostgreSQL seul : restaurer sous un Odoo actif corrompt le cache.
docker compose --env-file ../.env -f infrastructure/docker-compose.yml \
  -f infrastructure/docker-compose.vps.yml up -d postgres

# 8. Restaurer
./infrastructure/scripts/restore.sh /opt/dallytrading/backups/migration/final --yes

# 9. Démarrer le reste
docker compose --env-file ../.env -f infrastructure/docker-compose.yml \
  -f infrastructure/docker-compose.vps.yml up -d

# 10. Contrôles avant bascule DNS, via /etc/hosts
curl -sf http://127.0.0.1:8069/web/health && echo "Odoo OK"
docker compose ps
```

### Contrôles fonctionnels obligatoires avant la bascule DNS

- [ ] Connexion à Odoo avec un compte réel
- [ ] Nombre de contacts, devis et commandes identique à l'ancienne instance
- [ ] **Téléchargement d'une pièce jointe** — valide la cohérence base ↔ filestore
- [ ] Soumission d'une demande de devis → lead créé dans Odoo
- [ ] `docker logs dallytrading-odoo` sans erreur ni traceback
- [ ] Sauvegarde fonctionnelle sur le nouveau serveur

### Bascule DNS — point de non-retour

```text
dallytrading.com        A  → IP_DU_NOUVEAU_VPS
www.dallytrading.com    A  → IP_DU_NOUVEAU_VPS
crm.dallytrading.com    A  → IP_DU_NOUVEAU_VPS
```

Ne **pas** éteindre l'ancien serveur : le garder intact au moins 7 jours. C'est
le seul retour arrière réel si un problème apparaît après la bascule.

Une fois les certificats émis sur le nouveau serveur et le trafic stable,
remonter le TTL DNS à 3600 s.

> Ce qui **ne migre pas** et doit être reconfiguré : les enregistrements DNS de
> messagerie (SPF, DKIM, DMARC) si la messagerie était gérée par Plesk. À traiter
> avant la bascule, faute de quoi les e-mails transactionnels partiront en spam.
> Les boîtes e-mail elles-mêmes ne sont pas dans le périmètre de ce dépôt.

## 10. Après la migration

### Sauvegardes planifiées

Sur un VPS dédié, un timer systemd est préférable à `cron` : journalisation dans
`journalctl`, dépendances explicites, et pas de tâche silencieusement absente.

```ini
# /etc/systemd/system/dally-backup.service
[Unit]
Description=Sauvegarde DallyTrading (base + filestore)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=dally
WorkingDirectory=/opt/dallytrading/platform
ExecStart=/opt/dallytrading/platform/infrastructure/scripts/backup.sh --tag daily
```

```ini
# /etc/systemd/system/dally-backup.timer
[Unit]
Description=Sauvegarde quotidienne DallyTrading

[Timer]
OnCalendar=*-*-* 02:15:00
# Rattrape une exécution manquée après un redémarrage — ce que cron ne fait pas.
Persistent=true
RandomizedDelaySec=5m

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable --now dally-backup.timer
systemctl list-timers dally-backup.timer
```

### Mises à jour automatiques de sécurité

```bash
dpkg-reconfigure --priority=low unattended-upgrades
```

Limiter aux correctifs de sécurité. Ne jamais laisser un serveur de production se
mettre à jour tout seul au-delà de cela.

### Supervision

Sur un VPS dédié, l'ajout d'une stack de supervision devient défendable — ce qui
n'était pas le cas sur la machine partagée (ADR-007). Minimum utile :

| Cible | Contrôle |
|---|---|
| Disponibilité | `GET https://dallytrading.com/` et `https://crm.dallytrading.com/` |
| Odoo | `GET /api/v1/health` avec une clé au périmètre `customers:read` |
| Certificats | expiration < 21 jours → alerte |
| Disque | > 85 % → alerte |
| Sauvegardes | absence depuis > 26 h → alerte |
| Conteneurs | état `unhealthy` → alerte |

Une supervision externe (Uptime Kuma sur une autre machine, ou un service tiers)
est indispensable : une sonde hébergée sur le serveur qu'elle surveille ne peut
pas signaler que ce serveur est tombé.

## 11. Récapitulatif des écarts avec le déploiement Plesk

| Élément | Plesk | VPS dédié |
|---|---|---|
| `infrastructure/nginx/*.conf` | utilisé (collé dans l'interface) | remplacé par `caddy/Caddyfile` |
| `docker-compose.production.yml` | utilisé | complété par `docker-compose.vps.yml` |
| Ports Odoo | 18169 / 18172 | 8069 / 8072 |
| `ODOO_WORKERS` | 4 | 9 (profil 8 vCPU) |
| Next.js | processus hôte | conteneur `web` |
| `ODOO_URL` | `https://crm.dallytrading.com` | `http://odoo:8069` (réseau interne) |
| `allowed_ips` de la clé API | `127.0.0.1` | vide, isolation par réseau Docker |
| Certificats | Plesk | Caddy, automatique |
| Sauvegardes | `cron` | timer systemd |
| Pare-feu | géré par l'hébergeur | UFW + attention au contournement Docker |

Les scripts `backup.sh`, `verify-backup.sh`, `restore.sh`, `render-config.sh` et
`generate-secrets.sh` fonctionnent **sans modification** sur les deux
environnements : ils n'ont volontairement aucune dépendance à Plesk.
