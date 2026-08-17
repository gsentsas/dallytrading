#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# Suite E2E **fret** : navigateur réel → Next → Odoo → pont → tk_freight.
#
# ## Pourquoi un script séparé de e2e-portal.sh
#
# Le harness portail valide douze specs sans moteur fret, et ne doit pas en
# dépendre. Greffer `tk_freight` dessus rendrait fragiles des tests qui n'ont
# rien à voir avec lui, pour la seule économie d'un fichier.
#
# Ce script en reprend en revanche toutes les leçons — redémarrage entre specs
# pour la limitation de débit, restauration par périmètre, audit des journaux
# avec contrôle positif — parce qu'elles ont chacune été payées par un faux
# négatif.
#
# ## Code du fournisseur
#
# `tk_freight` est sous licence OPL-1 et reste hors de ce dépôt public. Le
# workspace privé est monté en lecture seule, et son absence arrête le script
# immédiatement, avec un message explicite : mieux vaut refuser de démarrer que
# d'échouer trente minutes plus tard sur un module introuvable.
#
# Usage :
#   ./e2e-freight.sh up     # monte la pile jetable et l'amorce
#   ./e2e-freight.sh test   # exécute la suite (rejouable sur la même base)
#   ./e2e-freight.sh down   # détruit la pile jetable, et elle seule
#   ./e2e-freight.sh all    # up && test ; down quoi qu'il arrive
# ═══════════════════════════════════════════════════════════════════════════
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WEB="$ROOT/apps/web"
WORK="${FE2E_WORK_DIR:-${TMPDIR:-/tmp}/dallytrading-freight-e2e}"

NEXT_PORT="${FE2E_NEXT_PORT:-3030}"
ODOO_PORT="${FE2E_ODOO_PORT:-18379}"
BASE_URL="http://127.0.0.1:${NEXT_PORT}"
PROJECT="dallytrading-freight-e2e"
DB="dallytrading_freight_e2e"
ODOO_CONTAINER="dallytrading-freight-e2e-odoo"
COMPOSE="$ROOT/infrastructure/docker-compose.freight-e2e.yml"
PLAYWRIGHT_IMAGE="${FE2E_PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.62.1-noble}"

#: Workspace privé contenant `tk_freight`. Jamais dans le dépôt.
VENDOR_ADDONS="${FE2E_VENDOR_ADDONS:-/tmp/dallytrading-tk-freight-dev/vendor-addons}"

#: Specs exécutées, dans l'ordre. Le pont fret d'abord : une régression sur lui
#: doit se voir avant que la spec véhicule ne s'en serve.
SPECS=(12-freight-bridge 13-vehicle-cargo)

log() { printf '\n\033[1m── %s\033[0m\n' "$*"; }

# ─────────────────────────────────────────────────────────────────────────────
assert_not_production() {
  case "$NEXT_PORT" in 3000|80|443) echo "Refus : port $NEXT_PORT réservé." >&2; exit 1;; esac
  case "$ODOO_PORT" in 18169|18172|18069|18072|18269|18369)
    echo "Refus : port $ODOO_PORT appartient à une instance existante." >&2; exit 1;; esac
  case "$DB" in dallytrading|odoo_crm) echo "Refus : base de production." >&2; exit 1;; esac
}

assert_vendor_available() {
  if [ ! -d "$VENDOR_ADDONS/tk_freight" ]; then
    cat >&2 <<MSG

Le module tk_freight est introuvable dans le workspace privé attendu :

    $VENDOR_ADDONS/tk_freight

Ce module est sous licence OPL-1 et n'est pas versionné dans ce dépôt public.
Indiquez le chemin de la copie licenciée :

    FE2E_VENDOR_ADDONS=/chemin/vers/vendor-addons ./e2e-freight.sh up

MSG
    exit 1
  fi
  if [ ! -f "$VENDOR_ADDONS/tk_freight/__manifest__.py" ]; then
    echo "Le répertoire tk_freight existe mais ne contient pas de manifeste." >&2
    exit 1
  fi
}

random_secret() { openssl rand -base64 "$1" | tr -d '\n/+=' | cut -c1-"$2"; }

# ─────────────────────────────────────────────────────────────────────────────
up() {
  assert_not_production
  assert_vendor_available
  umask 0077
  mkdir -p "$WORK/state"
  chmod 700 "$WORK" "$WORK/state"

  log "secrets éphémères"
  random_secret 33 32 > "$WORK/db-password"
  random_secret 33 32 > "$WORK/admin-password"
  openssl rand -base64 48 | tr -d '\n' > "$WORK/portal-secret"
  for who in A B STAFF; do random_secret 24 20 > "$WORK/pw-$who"; done
  find "$WORK" -maxdepth 1 -type f -exec chmod 600 {} +

  cat > "$WORK/odoo.conf" <<CONF
[options]
admin_passwd = $(cat "$WORK/admin-password")
list_db = False
dbfilter = ^${DB}\$
db_host = dallytrading-freight-e2e-postgres
db_port = 5432
db_user = fe2e_odoo
db_password = $(cat "$WORK/db-password")
db_name = ${DB}
db_maxconn = 8
db_template = template0
addons_path = /mnt/vendor-addons,/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons
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
FE2E_PROJECT=${PROJECT}
FE2E_PG_CONTAINER=dallytrading-freight-e2e-postgres
FE2E_ODOO_CONTAINER=${ODOO_CONTAINER}
FE2E_DB_USER=fe2e_odoo
FE2E_DB_PASSWORD=$(cat "$WORK/db-password")
FE2E_RUN_UID=$(id -u)
FE2E_RUN_GID=$(id -g)
FE2E_ODOO_CONF=${WORK}/odoo.conf
FE2E_ODOO_HTTP_PORT=${ODOO_PORT}
FE2E_VENDOR_ADDONS=${VENDOR_ADDONS}
ENV
  chmod 600 "$WORK/env"

  log "pile Odoo 19 + PostgreSQL 16 jetable (fret)"
  docker compose -p "$PROJECT" --env-file "$WORK/env" -f "$COMPOSE" up -d || exit 1

  # Le volume neuf appartient à root ; Odoo tourne sous l'uid appelant.
  docker run --rm -v dallytrading_freight_e2e_filestore:/data alpine:3 \
    chown -R "$(id -u):$(id -g)" /data >/dev/null
  docker restart "$ODOO_CONTAINER" >/dev/null

  log "initialisation : tk_freight + modules DallyTrading + pont"
  docker exec "$ODOO_CONTAINER" odoo -c /etc/odoo/odoo.conf -d "$DB" \
    -i base,tk_freight,dally_core,dally_crm,dally_api,dally_freight,dally_tracking,dally_portal,dally_freight_bridge \
    --stop-after-init > "$WORK/install.log" 2>&1 || {
      echo "installation échouée — voir $WORK/install.log" >&2
      grep -E ' (ERROR|CRITICAL) ' "$WORK/install.log" | tail -5 >&2
      exit 1
    }
  grep -c ' ERROR ' "$WORK/install.log" | sed 's/^/   lignes ERROR : /'

  log "comptes synthétiques"
  docker exec "$ODOO_CONTAINER" mkdir -p /tmp/e2e-seed
  for f in pw-A pw-B pw-STAFF; do
    docker cp "$WORK/$f" "$ODOO_CONTAINER:/tmp/e2e-seed/$f" >/dev/null
  done
  docker cp "$HERE/e2e-seed.py" "$ODOO_CONTAINER:/tmp/e2e-seed/seed.py" >/dev/null
  docker exec "$ODOO_CONTAINER" sh -c \
    "odoo shell -c /etc/odoo/odoo.conf -d $DB --no-http < /tmp/e2e-seed/seed.py" \
    2>&1 | grep -E 'SEED_OK|_LOGIN=' || { echo "seed de base échoué" >&2; exit 1; }

  log "fixtures fret"
  docker cp "$HERE/e2e-freight-seed.py" "$ODOO_CONTAINER:/tmp/e2e-seed/freight.py" >/dev/null
  docker exec "$ODOO_CONTAINER" sh -c \
    "odoo shell -c /etc/odoo/odoo.conf -d $DB --no-http < /tmp/e2e-seed/freight.py" \
    > "$WORK/freight-seed.out" 2>&1
  # Le jeton de suivi est expurgé à l'affichage : il vaut authentification sur
  # le suivi public, et n'a pas à traverser une sortie de terminal ou un journal
  # d'intégration continue. Playwright le lit depuis $WORK/freight-refs, en 0600.
  grep -E '^FREIGHT_' "$WORK/freight-seed.out" \
    | sed 's/^\(FREIGHT_DETAIL_TOKEN=\).*/\1<expurgé>/' | sed 's/^/   /'
  grep -q 'FREIGHT_SEED_OK' "$WORK/freight-seed.out" || {
    echo "seed fret échoué :" >&2; tail -20 "$WORK/freight-seed.out" >&2; exit 1; }
  # Les valeurs utiles à Playwright sont extraites une fois, ici.
  grep -E '^FREIGHT_' "$WORK/freight-seed.out" > "$WORK/freight-refs"
  chmod 600 "$WORK/freight-refs"

  log "fixtures vehicule"
  docker cp "$HERE/e2e-freight-vehicle-seed.py" "$ODOO_CONTAINER:/tmp/e2e-seed/vehicle.py" >/dev/null
  docker exec "$ODOO_CONTAINER" sh -c \
    "odoo shell -c /etc/odoo/odoo.conf -d $DB --no-http < /tmp/e2e-seed/vehicle.py" \
    > "$WORK/vehicle-seed.out" 2>&1
  # Le VIN est expurgé à l'affichage : il sert de sonde de fuite dans les
  # journaux, et l'y écrire nous-mêmes rendrait ce balayage ininterprétable.
  grep -E '^VEHICLE_' "$WORK/vehicle-seed.out" \
    | sed -E 's/^(VEHICLE_VIN_[AB]=).*/\1<expurgé>/' | sed 's/^/   /'
  grep -q 'VEHICLE_SEED_OK' "$WORK/vehicle-seed.out" || {
    echo "seed vehicule échoué :" >&2; tail -20 "$WORK/vehicle-seed.out" >&2; exit 1; }
  grep -E '^VEHICLE_' "$WORK/vehicle-seed.out" >> "$WORK/freight-refs"

  # Charge les références produites par les graines — dont la clé d'API réelle,
  # sans laquelle la page /devis affiche « Formulaire momentanément
  # indisponible » : le catalogue de services passe par l'API serveur, pas par
  # une session portail.
  # shellcheck disable=SC1090
  set -a; . "$WORK/freight-refs"; set +a

  log "frontend Next isolé (copie du dépôt, jamais le répertoire servi par systemd)"
  rm -rf "$WORK/web"; mkdir -p "$WORK/web"
  tar -C "$WEB" --exclude=node_modules --exclude=.next --exclude='.env*' -cf - . \
    | tar -C "$WORK/web" -xf -
  cp -al "$WEB/node_modules" "$WORK/web/node_modules"

  cat > "$WORK/web/.env.local" <<ENV
NEXT_PUBLIC_SITE_URL=${BASE_URL}
NEXT_PUBLIC_ENVIRONMENT=development
ENVIRONMENT=development
ODOO_GATEWAY_ADAPTER=dally_api
ODOO_URL=http://127.0.0.1:${ODOO_PORT}
ODOO_DATABASE=${DB}
ODOO_API_KEY=${VEHICLE_API_KEY:-freight-e2e-placeholder-integration-key-000}
ODOO_TIMEOUT_MS=15000
PORTAL_SESSION_SECRET=$(cat "$WORK/portal-secret")
ENV
  chmod 600 "$WORK/web/.env.local"

  ( cd "$WORK/web" && npx next build >/dev/null && npm run postbuild >/dev/null ) || {
    echo "build Next échoué" >&2; exit 1; }
  log "environnement prêt — Next sur ${BASE_URL}, Odoo sur 127.0.0.1:${ODOO_PORT}"
}

# ─────────────────────────────────────────────────────────────────────────────
restart_next() {
  # Attendre que l'ancien processus ait RÉELLEMENT rendu le port : sinon c'est
  # lui qui répond à la sonde, le nouveau meurt sans se lier, et la suite se
  # freine sur des compteurs de limitation de débit déjà chargés.
  if [ -f "$WORK/next.pid" ]; then
    kill "$(cat "$WORK/next.pid")" 2>/dev/null || true
  fi
  for _ in $(seq 1 30); do
    ss -ltn 2>/dev/null | grep -q ":${NEXT_PORT} " || break
    sleep 1
  done
  if ss -ltn 2>/dev/null | grep -q ":${NEXT_PORT} "; then
    echo "le port ${NEXT_PORT} n'a pas été libéré : arrêt" >&2
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
  # shellcheck disable=SC1090
  set -a; . "$WORK/freight-refs"; set +a
  docker run --rm --network host --label com.dallytrading.freight-e2e=true \
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
    -e E2E_ODOO_URL="http://127.0.0.1:${ODOO_PORT}" \
    -e FREIGHT_DETAIL_REFERENCE="${FREIGHT_DETAIL_REFERENCE:-}" \
    -e FREIGHT_DETAIL_TOKEN="${FREIGHT_DETAIL_TOKEN:-}" \
    -e FREIGHT_PUBLISHED_DOCUMENT="${FREIGHT_PUBLISHED_DOCUMENT:-}" \
    -e VEHICLE_VIN_A="${VEHICLE_VIN_A:-}" \
    -e VEHICLE_VIN_B="${VEHICLE_VIN_B:-}" \
    -e VEHICLE_REGISTRATION_A="${VEHICLE_REGISTRATION_A:-}" \
    --user "$(id -u):$(id -g)" \
    "$PLAYWRIGHT_IMAGE" npx playwright test --output=/tmp/pw-out "$@"
}

#: Restaure le périmètre fret MUTABLE, puis VÉRIFIE la précondition.
#:
#: Un reset global unique ne suffirait pas : il supposerait qu'aucune spec
#: ultérieure ne touche les mêmes données, et cette hypothèse a déjà été fausse.
reset_fixtures() {
  local output
  output="$(docker exec -i "$ODOO_CONTAINER" \
    odoo shell -c /etc/odoo/odoo.conf -d "$DB" --no-http \
    < "$HERE/e2e-freight-reset.py" 2>&1)"
  printf '%s\n' "$output" | grep -E "^PRECONDITION_" | sed 's/^/   /'
  if ! printf '%s' "$output" | grep -q "PRECONDITION_OK"; then
    echo "   précondition fret non satisfaite — arrêt" >&2
    return 1
  fi
}

#: Restaure le périmètre véhicule et vérifie ses préconditions.
reset_vehicle() {
  local output
  output="$(docker exec -i "$ODOO_CONTAINER" \
    odoo shell -c /etc/odoo/odoo.conf -d "$DB" --no-http \
    < "$HERE/e2e-freight-vehicle-reset.py" 2>&1)"
  printf '%s\n' "$output" | grep -E "^PRECONDITION_" | sed 's/^/   /'
  if ! printf '%s' "$output" | grep -q "PRECONDITION_OK vehicle"; then
    echo "   précondition véhicule non satisfaite — arrêt" >&2
    return 1
  fi
}

run_tests() {
  : > "$WORK/next.log"
  local failed=0

  # Borne de l'audit des journaux Odoo.
  #
  # Sans elle, `docker logs` rend tout l'historique du conteneur, démarrage
  # compris — et le démarrage produit légitimement des traces : les sondes de
  # santé et le cron frappent le serveur avant que le registre ne soit chargé,
  # d'où des `KeyError: 'ir.http'`. Les compter comme des erreurs de la suite
  # rendrait l'audit rouge en permanence, donc inutile.
  local depuis
  depuis="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  log "restauration du périmètre fret"
  reset_fixtures || return 1

  log "restauration du périmètre véhicule"
  reset_vehicle || return 1

  # Une spec par invocation, avec redémarrage entre chacune : la limitation de
  # débit sur la connexion vit en mémoire d'un seul processus, et deux specs
  # d'affilée la déclencheraient.
  for spec in "${SPECS[@]}"; do
    log "$spec"
    restart_next
    playwright "e2e/${spec}.spec.ts" || failed=1
  done

  verify_db || failed=1
  audit_logs "$depuis" || failed=1
  return "$failed"
}

#: Compte les enregistrements réellement créés, et non ceux affichés.
#:
#: L'interface est paginée, filtrée et triée : compter des lignes à l'écran ne
#: prouve rien sur l'absence de doublon côté booking ou côté fournisseur.
verify_db() {
  log "vérification en base (idempotence réelle)"
  local output
  output="$(docker exec -i "$ODOO_CONTAINER" \
    odoo shell -c /etc/odoo/odoo.conf -d "$DB" --no-http \
    < "$HERE/e2e-freight-verify.py" 2>&1)"
  printf '%s\n' "$output" | grep -E "^VERIFY" | sed 's/^/   /'
  printf '%s' "$output" | grep -q "VERIFY_OK" || {
    echo "   comptage en base incorrect — arrêt" >&2
    return 1
  }
}

# ─────────────────────────────────────────────────────────────────────────────
audit_logs() {
  log "audit des journaux"
  local depuis="${1:-}" odoo_log status=0
  odoo_log="$(mktemp)"
  if [ -n "$depuis" ]; then
    docker logs --since "$depuis" "$ODOO_CONTAINER" > "$odoo_log" 2>&1
  else
    docker logs "$ODOO_CONTAINER" > "$odoo_log" 2>&1
  fi
  echo "   fenêtre auditée depuis : ${depuis:-le démarrage}"

  # Contrôle positif d'abord : un journal vide rendrait tout le reste creux.
  if [ "$(grep -c 'Portal' "$WORK/next.log" || true)" -eq 0 ]; then
    echo "   journal Next vide — l'audit ne prouverait rien" >&2
    rm -f "$odoo_log"; return 1
  fi
  echo "   journal Next : $(wc -l < "$WORK/next.log") lignes (contrôle positif OK)"

  local label needle n
  while IFS='|' read -r label needle; do
    [ -z "$label" ] && continue
    for file in "$WORK/next.log" "$odoo_log"; do
      n=$(grep -c -- "$needle" "$file" 2>/dev/null || true)
      if [ "${n:-0}" -ne 0 ]; then
        echo "   FUITE : « $label » apparaît $n fois dans $(basename "$file")" >&2
        status=1
      fi
    done
  done <<'NEEDLES'
coût fournisseur|DALLY_E2E_SECRET_VENDOR_COST
marge|DALLY_E2E_SECRET_MARGIN
fournisseur|DALLY_E2E_SECRET_SUPPLIER
commission|DALLY_E2E_SECRET_COMMISSION
note interne|DALLY_E2E_SECRET_INTERNAL_NOTE
document interne|DALLY_E2E_SECRET_INTERNAL_DOCUMENT
note interne vehicule|DALLY_E2E_SECRET_VEHICLE_INTERNAL_NOTE
prix d achat vehicule|DALLY_E2E_SECRET_VEHICLE_PURCHASE_PRICE
prix d achat (montant)|987654
VIN de fixture A|DALLYE2EVIN000001
VIN du formulaire public|DALLYE2EVINPUB001
cookie de session|dt_portal_session=
session Odoo|session_id=
en-tête d'autorisation|Authorization:
NEEDLES

  # Erreurs métier inattendues. Les refus de sécurité sont attendus et ne
  # comptent pas : c'est précisément ce que la suite provoque.
  local motif
  for motif in Traceback "Unhandled" "UniqueViolation" "internal_error"; do
    n=$(grep -c -- "$motif" "$odoo_log" 2>/dev/null || true)
    if [ "${n:-0}" -ne 0 ]; then
      echo "   ERREUR INATTENDUE : « $motif » × $n dans le journal Odoo" >&2
      status=1
    fi
  done

  [ "$status" -eq 0 ] && echo "   aucune fuite, aucune erreur inattendue"
  rm -f "$odoo_log"
  return "$status"
}

# ─────────────────────────────────────────────────────────────────────────────
down() {
  log "destruction de la pile jetable fret (et d'elle seule)"
  if [ -f "$WORK/next.pid" ]; then
    kill "$(cat "$WORK/next.pid")" 2>/dev/null || true
    rm -f "$WORK/next.pid"
  fi
  # Ciblage explicite par projet : jamais de `docker prune`, jamais de `down`
  # global. Cette pile porte son propre nom de projet, et lui seul est visé.
  if [ -f "$WORK/env" ]; then
    docker compose -p "$PROJECT" --env-file "$WORK/env" -f "$COMPOSE" \
      down --volumes --remove-orphans 2>/dev/null || true
  fi
  echo "   conteneurs restants portant le label freight-e2e : $(
    docker ps -aq --filter label=com.dallytrading.freight-e2e=true | wc -l)"
}

case "${1:-}" in
  up)   up ;;
  test) run_tests ;;
  down) down ;;
  all)  up && run_tests; result=$?; down; exit "$result" ;;
  *)    echo "usage: $0 {up|test|down|all}" >&2; exit 2 ;;
esac
