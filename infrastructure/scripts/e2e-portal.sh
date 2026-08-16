#!/usr/bin/env bash
#
# Validation E2E de l'espace client — environnement jetable, de bout en bout.
#
#   ./infrastructure/scripts/e2e-portal.sh up        monte l'environnement
#   ./infrastructure/scripts/e2e-portal.sh test      exécute la suite Playwright
#   ./infrastructure/scripts/e2e-portal.sh down      détruit tout
#   ./infrastructure/scripts/e2e-portal.sh all       les trois, à la suite
#
# ─── Isolation ────────────────────────────────────────────────────────────────
#
# Rien ici ne touche la production : ni la base `dallytrading`, ni son serveur
# PostgreSQL, ni le filestore, ni les conteneurs `dallytrading-odoo` /
# `dallytrading-postgres`, ni l'instance Odoo 18 `odoo_crm` (SEN CONTAINERS), ni
# aucun autre voisin de cette machine.
#
# La destruction ne cible QUE les objets portant le label
# `com.dallytrading.e2e=true`. Aucun `docker prune` n'est utilisé : sur une
# machine partagée, une commande globale finit toujours par emporter autre chose.
#
# ─── Secrets ──────────────────────────────────────────────────────────────────
#
# Tous les secrets sont tirés au hasard à chaque `up`, écrits en 0600 dans un
# répertoire de travail hors du dépôt, et détruits par `down`. Aucun n'est
# affiché, aucun ne provient de la production, aucun n'y retourne.
#
# ─── Pourquoi le navigateur tourne dans un conteneur ──────────────────────────
#
# Le Chromium de Playwright réclame neuf bibliothèques système absentes de cet
# hôte ; les installer demanderait les droits d'administration. L'image officielle
# les embarque. Elle partage la pile réseau de l'hôte (`--network host`) pour
# atteindre l'instance Next de test, qui n'écoute que sur la loopback et n'est
# republiée nulle part.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WEB="$ROOT/apps/web"
WORK="${E2E_WORK_DIR:-${TMPDIR:-/tmp}/dallytrading-e2e}"

NEXT_PORT="${E2E_NEXT_PORT:-3020}"
ODOO_PORT="${E2E_ODOO_PORT:-18269}"
BASE_URL="http://127.0.0.1:${NEXT_PORT}"
ODOO_CONTAINER="dallytrading-e2e-odoo"
PLAYWRIGHT_IMAGE="${E2E_PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.62.1-noble}"

SPECS_BEFORE=(01-login 02-session 03-logout 04-redirect-origin 06-network 07-business 08-cross-client 09-canaries 10-profile-write 05a-capture-session)

log() { printf '\n\033[1m── %s\033[0m\n' "$*"; }

# ─────────────────────────────────────────────────────────────────────────────
# Garde-fou : ce script ne doit jamais viser un port ou un conteneur de prod.
# ─────────────────────────────────────────────────────────────────────────────
assert_not_production() {
  case "$NEXT_PORT" in 3000|80|443) echo "Refus : port $NEXT_PORT réservé." >&2; exit 1;; esac
  case "$ODOO_PORT" in 18169|18172|18069|18072) echo "Refus : port $ODOO_PORT appartient à une instance existante." >&2; exit 1;; esac
}

random_secret() { openssl rand -base64 "$1" | tr -d '\n/+=' | cut -c1-"$2"; }

# ─────────────────────────────────────────────────────────────────────────────
up() {
  assert_not_production
  umask 0077
  mkdir -p "$WORK/state"
  chmod 700 "$WORK" "$WORK/state"

  log "secrets éphémères"
  random_secret 33 32 > "$WORK/db-password"
  random_secret 33 32 > "$WORK/admin-password"
  openssl rand -base64 48 | tr -d '\n' > "$WORK/portal-secret"
  for who in A B STAFF; do random_secret 24 20 > "$WORK/pw-$who"; done
  # Uniquement les FICHIERS : `chmod 600` sur le répertoire `state` le rendrait
  # non traversable, et Playwright ne pourrait plus y écrire l'état capturé.
  find "$WORK" -maxdepth 1 -type f -exec chmod 600 {} +

  cat > "$WORK/odoo.conf" <<CONF
[options]
admin_passwd = $(cat "$WORK/admin-password")
list_db = False
dbfilter = ^dallytrading_e2e\$
db_host = dallytrading-e2e-postgres
db_port = 5432
db_user = e2e_odoo
db_password = $(cat "$WORK/db-password")
db_name = dallytrading_e2e
db_maxconn = 8
db_template = template0
addons_path = /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons
data_dir = /var/lib/odoo
proxy_mode = False
http_enable = True
http_interface = 0.0.0.0
http_port = 8069
gevent_port = 8072
workers = 0
max_cron_threads = 1
log_level = info
log_handler = :INFO,werkzeug:WARNING
without_demo = True
server_wide_modules = base,web
CONF
  chmod 600 "$WORK/odoo.conf"

  cat > "$WORK/env" <<ENV
E2E_COMPOSE_PROJECT_NAME=dallytrading-e2e
E2E_PG_CONTAINER=dallytrading-e2e-postgres
E2E_ODOO_CONTAINER=${ODOO_CONTAINER}
E2E_DB_USER=e2e_odoo
E2E_DB_PASSWORD=$(cat "$WORK/db-password")
E2E_RUN_UID=$(id -u)
E2E_RUN_GID=$(id -g)
E2E_ODOO_CONF=${WORK}/odoo.conf
E2E_ODOO_HTTP_PORT=${ODOO_PORT}
ENV
  chmod 600 "$WORK/env"

  log "pile Odoo 19 + PostgreSQL 16 jetable"
  docker compose -p dallytrading-e2e --env-file "$WORK/env" \
    -f "$ROOT/infrastructure/docker-compose.e2e.yml" up -d

  # Le volume neuf appartient à root ; Odoo tourne sous l'uid appelant.
  docker run --rm -v dallytrading_e2e_odoo_filestore:/data alpine:3 \
    chown -R "$(id -u):$(id -g)" /data
  docker restart "$ODOO_CONTAINER" >/dev/null

  log "initialisation de la base et des modules DallyTrading"
  docker exec "$ODOO_CONTAINER" odoo -c /etc/odoo/odoo.conf \
    -d dallytrading_e2e -i base,dally_portal --stop-after-init >/dev/null

  log "comptes synthétiques"
  docker exec "$ODOO_CONTAINER" mkdir -p /tmp/e2e-seed
  for f in pw-A pw-B pw-STAFF; do docker cp "$WORK/$f" "$ODOO_CONTAINER:/tmp/e2e-seed/$f" >/dev/null; done
  docker cp "$HERE/e2e-seed.py" "$ODOO_CONTAINER:/tmp/e2e-seed/seed.py" >/dev/null
  docker exec "$ODOO_CONTAINER" sh -c \
    'odoo shell -c /etc/odoo/odoo.conf -d dallytrading_e2e --no-http < /tmp/e2e-seed/seed.py' \
    2>&1 | grep -E 'SEED_OK|_SHARE=' || { echo "seed échoué" >&2; exit 1; }

  log "frontend Next isolé (copie du dépôt, jamais le répertoire servi par systemd)"
  rm -rf "$WORK/web"; mkdir -p "$WORK/web"
  tar -C "$WEB" --exclude=node_modules --exclude=.next --exclude='.env*' -cf - . \
    | tar -C "$WORK/web" -xf -
  # Liens physiques : même système de fichiers, et Turbopack refuse un lien
  # symbolique pointant hors de la racine du projet.
  cp -al "$WEB/node_modules" "$WORK/web/node_modules"

  cat > "$WORK/web/.env.local" <<ENV
NEXT_PUBLIC_SITE_URL=${BASE_URL}
NEXT_PUBLIC_ENVIRONMENT=development
ENVIRONMENT=development
ODOO_GATEWAY_ADAPTER=dally_api
ODOO_URL=http://127.0.0.1:${ODOO_PORT}
ODOO_DATABASE=dallytrading_e2e
ODOO_API_KEY=e2e-placeholder-integration-key-unused-000
ODOO_TIMEOUT_MS=15000
PORTAL_SESSION_SECRET=$(cat "$WORK/portal-secret")
ENV
  chmod 600 "$WORK/web/.env.local"

  (cd "$WORK/web" && npx next build >/dev/null && npm run postbuild >/dev/null)
  log "environnement prêt — Next sur ${BASE_URL}, Odoo sur 127.0.0.1:${ODOO_PORT}"
}

# ─────────────────────────────────────────────────────────────────────────────
restart_next() {
  # Attendre que l'ancien processus ait RÉELLEMENT rendu le port.
  #
  # La première version faisait `kill` puis `sleep 2` puis sondait /connexion.
  # Si l'ancien processus n'avait pas fini de s'arrêter, c'est LUI qui répondait
  # 200 : la sonde réussissait, le nouveau processus échouait à se lier et
  # mourait, et le serveur continuait avec ses compteurs de limitation de débit
  # déjà chargés. La suite se freinait alors elle-même, par intermittence et
  # sans rapport avec ce qu'elle testait.
  if [ -f "$WORK/next.pid" ]; then
    kill "$(cat "$WORK/next.pid")" 2>/dev/null || true
  fi
  for _ in $(seq 1 30); do
    ss -ltn 2>/dev/null | grep -q ":${NEXT_PORT} " || break
    sleep 1
  done
  if ss -ltn 2>/dev/null | grep -q ":${NEXT_PORT} "; then
    echo "le port ${NEXT_PORT} n'a pas été libéré : arrêt plutôt que de tester" \
      "contre un serveur dont les compteurs ne sont pas neufs" >&2
    exit 1
  fi
  ( cd "$WORK/web"
    set -a; . "$WORK/web/.env.local"; set +a
    HOSTNAME=127.0.0.1 PORT="$NEXT_PORT" NODE_ENV=production \
      node .next/standalone/server.js >> "$WORK/next.log" 2>&1 &
    echo $! > "$WORK/next.pid" )
  for _ in $(seq 1 20); do
    curl -sf -o /dev/null "${BASE_URL}/connexion" && return 0
    sleep 1
  done
  echo "l'instance Next de test n'a pas démarré" >&2
  exit 1
}

playwright() {
  docker run --rm --network host --label com.dallytrading.e2e=true \
    -v "$WEB:/work:ro" -v "$WORK/state:/state" -w /work \
    -e HOME=/tmp \
    -e E2E_BASE_URL="$BASE_URL" \
    -e E2E_STATE_PATH=/state/portal-a.json \
    -e E2E_A_LOGIN=portal.a@e2e-a.invalid \
    -e E2E_B_LOGIN=portal.b@e2e-b.invalid \
    -e E2E_STAFF_LOGIN=staff@e2e-interne.invalid \
    -e E2E_A_PASSWORD="$(cat "$WORK/pw-A")" \
    -e E2E_B_PASSWORD="$(cat "$WORK/pw-B")" \
    -e E2E_STAFF_PASSWORD="$(cat "$WORK/pw-STAFF")" \
    -e E2E_PORTAL_SECRET="$(cat "$WORK/portal-secret")" \
    --user "$(id -u):$(id -g)" \
    "$PLAYWRIGHT_IMAGE" npx playwright test --output=/tmp/pw-out "$@"
}

run_tests() {
  : > "$WORK/next.log"
  local failed=0

  # Un fichier à la fois, avec redémarrage entre chacun.
  #
  # `/api/portal/auth/login` limite à 10 tentatives par IP sur 5 minutes. Une
  # suite E2E parle depuis une seule IP : d'un bloc, elle se freinerait
  # elle-même. La limite n'est pas relâchée — le compteur vit en mémoire d'un
  # seul processus, et le redémarrage le remet à zéro. Ce détour est lui-même la
  # démonstration de la limite documentée au §7 de docs/PORTAL.md.
  for spec in "${SPECS_BEFORE[@]}"; do
    log "$spec"
    restart_next
    playwright "e2e/${spec}.spec.ts" || failed=1
  done

  # Entre les deux moitiés du scénario 05 : la session Odoo est détruite pendant
  # que le cookie du navigateur, lui, reste parfaitement valide.
  log "invalidation des sessions Odoo (conteneur E2E uniquement)"
  local before after
  before=$(docker exec "$ODOO_CONTAINER" sh -c 'find /var/lib/odoo/sessions -type f | wc -l')
  docker exec "$ODOO_CONTAINER" sh -c 'find /var/lib/odoo/sessions -type f -delete'
  after=$(docker exec "$ODOO_CONTAINER" sh -c 'find /var/lib/odoo/sessions -type f | wc -l')
  echo "   fichiers de session : $before → $after"
  [ "$before" -gt 0 ] || { echo "aucune session à invalider : le scénario 05 ne prouverait rien" >&2; failed=1; }

  log "05b-expired-session"
  restart_next
  playwright e2e/05b-expired-session.spec.ts || failed=1

  audit_logs || failed=1
  return "$failed"
}

# ─────────────────────────────────────────────────────────────────────────────
audit_logs() {
  log "audit des journaux"
  local odoo_log status=0
  odoo_log="$(mktemp)"
  docker logs "$ODOO_CONTAINER" > "$odoo_log" 2>&1

  # Contrôle positif d'abord : un journal vide rendrait tout le reste creux.
  if [ "$(grep -c 'Portal' "$WORK/next.log" || true)" -eq 0 ]; then
    echo "   journal Next vide — l'audit ne prouverait rien" >&2
    rm -f "$odoo_log"; return 1
  fi

  local label needle n
  while IFS='|' read -r label needle; do
    for file in "$WORK/next.log" "$odoo_log"; do
      n=$(grep -c -- "$needle" "$file" 2>/dev/null || true)
      if [ "${n:-0}" -ne 0 ]; then
        echo "   FUITE : « $label » apparaît $n fois dans $(basename "$file")" >&2
        status=1
      fi
    done
  done <<AUDIT
mot de passe A|$(cat "$WORK/pw-A")
mot de passe B|$(cat "$WORK/pw-B")
mot de passe Staff|$(cat "$WORK/pw-STAFF")
secret de scellement|$(cat "$WORK/portal-secret")
mot de passe de la base|$(cat "$WORK/db-password")
identifiant de session Odoo|session_id=
cookie du portail|dt_portal_session
en-tête Cookie|Cookie:
en-tête Authorization|Authorization:
clé d'API|x-api-key
valeur téléphone profil|+221 77 123 45 67
valeur adresse profil|42 avenue du Test
AUDIT

  rm -f "$odoo_log"
  [ "$status" -eq 0 ] && echo "   aucune valeur sensible dans les deux journaux"
  return "$status"
}

# ─────────────────────────────────────────────────────────────────────────────
down() {
  log "arrêt de l'instance Next de test"
  [ -f "$WORK/next.pid" ] && kill "$(cat "$WORK/next.pid")" 2>/dev/null || true

  log "destruction des objets Docker portant com.dallytrading.e2e=true"
  # Strictement sélectif. Jamais de `docker prune` : cette machine héberge
  # d'autres piles, et une commande globale finirait par en emporter une.
  local ids
  ids=$(docker ps -aq --filter "label=com.dallytrading.e2e=true")
  [ -n "$ids" ] && docker rm -f $ids >/dev/null
  ids=$(docker volume ls -q --filter "label=com.dallytrading.e2e=true")
  [ -n "$ids" ] && docker volume rm $ids >/dev/null
  ids=$(docker network ls -q --filter "label=com.dallytrading.e2e=true")
  [ -n "$ids" ] && docker network rm $ids >/dev/null

  log "effacement des secrets éphémères"
  # Les fichiers d'état contiennent des cookies de session encore scellés.
  rm -rf "$WORK"
  echo "   $WORK supprimé"
}

case "${1:-}" in
  up)   up ;;
  test) run_tests ;;
  down) down ;;
  all)  up && run_tests; result=$?; down; exit "$result" ;;
  *)    sed -n '2,10p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
