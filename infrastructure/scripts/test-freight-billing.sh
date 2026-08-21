#!/usr/bin/env bash
# =============================================================================
# DallyTrading - RC gate for dally_freight_billing
#
# Runs the module in the existing isolated Freight dev stack. This script never
# connects to the production database/containers and never touches SEN
# CONTAINERS. It creates its own PostgreSQL volume, filestore, database, port and
# Odoo configuration, then destroys only that labelled compose project.
#
# Usage:
#   bash infrastructure/scripts/test-freight-billing.sh
#
# Optional:
#   FBT_KEEP=1 bash infrastructure/scripts/test-freight-billing.sh
#   FBT_PORT=18469 bash infrastructure/scripts/test-freight-billing.sh
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
COMPOSE="$ROOT/infrastructure/docker-compose.freight-dev.yml"

PROJECT="${FBT_PROJECT:-dallytrading-freight-billing-test}"
DB="${FBT_DB:-dallytrading_freight_billing_test}"
PORT="${FBT_PORT:-18469}"
ODOO_CONTAINER="${FBT_ODOO_CONTAINER:-dallytrading-freight-billing-test-odoo}"
PG_CONTAINER="${FBT_PG_CONTAINER:-dallytrading-freight-billing-test-postgres}"
WORK="${FBT_WORK_DIR:-${TMPDIR:-/tmp}/dallytrading-freight-billing-test}"
KEEP="${FBT_KEEP:-0}"

ENV_FILE="$WORK/env"
ODOO_CONF="$WORK/odoo.conf"
TEST_LOG="$WORK/odoo-tests.log"
EMPTY_VENDOR="$WORK/vendor-addons"

log() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

assert_isolated() {
    case "$DB" in
        dallytrading|odoo_crm|sen_containers_crm)
            fail "refusing production/foreign database name: $DB"
            ;;
    esac

    case "$PORT" in
        80|443|18069|18072|18169|18172|3010)
            fail "refusing protected production/SEN port: $PORT"
            ;;
    esac

    case "$PROJECT" in
        dallytrading|dallytrading-e2e|sen-containers|sen_containers)
            fail "refusing protected compose project: $PROJECT"
            ;;
    esac

    case "$ODOO_CONTAINER" in
        dallytrading-odoo|odoo_crm|sen-containers*|sen_containers*)
            fail "refusing protected Odoo container: $ODOO_CONTAINER"
            ;;
    esac

    case "$PG_CONTAINER" in
        dallytrading-postgres|sen-containers*|sen_containers*)
            fail "refusing protected PostgreSQL container: $PG_CONTAINER"
            ;;
    esac

    [ -f "$COMPOSE" ] || fail "missing compose file: $COMPOSE"
    [ -f "$ROOT/odoo/custom-addons/dally_freight_billing/__manifest__.py" ] || \
        fail "dally_freight_billing is missing from this worktree"
}

compose() {
    docker compose \
        -p "$PROJECT" \
        --env-file "$ENV_FILE" \
        -f "$COMPOSE" \
        "$@"
}

cleanup() {
    status=$?
    set +e
    if [ "$KEEP" = "1" ]; then
        echo "FBT_KEEP=1 - isolated stack kept for inspection"
        echo "WORK=$WORK"
    elif [ -f "$ENV_FILE" ]; then
        compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM

assert_isolated

log "immutable source state"
HEAD="$(git -C "$ROOT" rev-parse HEAD)"
BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
STATUS="$(git -C "$ROOT" status --porcelain)"
printf 'BRANCH=%s\nHEAD=%s\n' "$BRANCH" "$HEAD"
[ "$BRANCH" = "feature/freight-billing-sync" ] || \
    fail "run this gate from feature/freight-billing-sync"
[ -z "$STATUS" ] || fail "worktree must be clean before RC tests"

log "ephemeral configuration"
umask 0077
rm -rf "$WORK"
mkdir -p "$WORK" "$EMPTY_VENDOR"

DB_PASSWORD="$(openssl rand -hex 32)"
ADMIN_PASSWORD="$(openssl rand -hex 32)"

cat > "$ODOO_CONF" <<CONF
[options]
admin_passwd = ${ADMIN_PASSWORD}
list_db = False
dbfilter = ^${DB}$
db_host = ${PG_CONTAINER}
db_port = 5432
db_user = fbt_odoo
db_password = ${DB_PASSWORD}
db_name = ${DB}
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
log_level = test
log_handler = :INFO,odoo.tests:INFO
without_demo = True
server_wide_modules = base,web
CONF
chmod 600 "$ODOO_CONF"

cat > "$ENV_FILE" <<ENV
FD_PROJECT=${PROJECT}
FD_PG_CONTAINER=${PG_CONTAINER}
FD_ODOO_CONTAINER=${ODOO_CONTAINER}
FD_DB_USER=fbt_odoo
FD_DB_PASSWORD=${DB_PASSWORD}
FD_RUN_UID=$(id -u)
FD_RUN_GID=$(id -g)
FD_ODOO_CONF=${ODOO_CONF}
FD_ODOO_HTTP_PORT=${PORT}
FD_VENDOR_ADDONS=${EMPTY_VENDOR}
FD_POSTGRES_VOLUME=${PROJECT}_postgres_data
FD_FILESTORE_VOLUME=${PROJECT}_filestore
FD_PRIVATE_NETWORK=${PROJECT}_private
FD_PUBLIC_NETWORK=${PROJECT}_public
ENV
chmod 600 "$ENV_FILE"

log "isolated PostgreSQL and Odoo 19"
compose up -d

# The named filestore volume is initially root-owned while Odoo deliberately
# runs as the invoking unprivileged uid/gid.
docker run --rm \
    -v "${PROJECT}_filestore:/data" \
    alpine:3 \
    chown -R "$(id -u):$(id -g)" /data >/dev/null

docker restart "$ODOO_CONTAINER" >/dev/null

PG_HEALTH=""
for _ in $(seq 1 60); do
    PG_HEALTH="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$PG_CONTAINER" 2>/dev/null || true)"
    [ "$PG_HEALTH" = "healthy" ] && break
    sleep 1
done
[ "$PG_HEALTH" = "healthy" ] || fail "isolated PostgreSQL did not become healthy"

echo "POSTGRES=HEALTHY"

log "install module and execute Odoo tests"
set +e
docker exec "$ODOO_CONTAINER" \
    odoo \
    -c /etc/odoo/odoo.conf \
    -d "$DB" \
    -i dally_freight_billing \
    --test-enable \
    --test-tags /dally_freight_billing \
    --stop-after-init \
    >"$TEST_LOG" 2>&1
TEST_RC=$?
set -e

# Surface useful diagnostics without printing ephemeral secrets.
grep -E '(^| )(ERROR|CRITICAL) |FAIL:|ERROR:|failed,|error\(s\)' "$TEST_LOG" | tail -80 || true

if [ "$TEST_RC" -ne 0 ]; then
    echo "ODOO_TEST_RC=$TEST_RC"
    echo "TEST_LOG=$TEST_LOG"
    tail -120 "$TEST_LOG" || true
    fail "Odoo Freight Billing test command failed"
fi

# Odoo can occasionally exit zero after individual test diagnostics depending on
# the runner path. Treat explicit failure/error summaries as a hard gate too.
if grep -Eq '([1-9][0-9]* failed|[1-9][0-9]* error\(s\)|FAIL:|^ERROR:)' "$TEST_LOG"; then
    echo "TEST_LOG=$TEST_LOG"
    tail -120 "$TEST_LOG" || true
    fail "test log contains failures/errors"
fi

if ! grep -q 'dally_freight_billing' "$TEST_LOG"; then
    tail -120 "$TEST_LOG" || true
    fail "test log does not prove dally_freight_billing was loaded"
fi

echo "ODOO_TEST_RC=0"
echo "DALLY_FREIGHT_BILLING_TESTS=PASS"

log "database module state"
MODULE_STATE="$(
    docker exec "$PG_CONTAINER" \
        psql -U fbt_odoo -d "$DB" -Atc \
        "SELECT state || '|' || COALESCE(latest_version,'') FROM ir_module_module WHERE name='dally_freight_billing';" \
        2>/dev/null || true
)"
echo "DALLY_FREIGHT_BILLING=$MODULE_STATE"
case "$MODULE_STATE" in
    installed\|19.0.1.5.0*) ;;
    *) fail "unexpected installed module state/version: $MODULE_STATE" ;;
esac

log "isolation proof"
# Check names/state only. Never inspect production configuration, files, DBs or
# logs from this RC script.
PROD_ODOO_RUNNING="$(docker inspect -f '{{.State.Running}}' dallytrading-odoo 2>/dev/null || echo unknown)"
PROD_PG_RUNNING="$(docker inspect -f '{{.State.Running}}' dallytrading-postgres 2>/dev/null || echo unknown)"
echo "PRODUCTION_ODOO_RUNNING=$PROD_ODOO_RUNNING"
echo "PRODUCTION_POSTGRES_RUNNING=$PROD_PG_RUNNING"
echo "RC_PROJECT=$PROJECT"
echo "RC_DB=$DB"
echo "RC_PORT=$PORT"

echo
echo "============================================================"
echo " DALLY FREIGHT BILLING - RC TEST GATE PASSED"
echo " HEAD=$HEAD"
echo " MODULE=19.0.1.5.0"
echo " TESTS=PASS"
echo " PRODUCTION_TOUCHED=NO"
echo " SEN_CONTAINERS_TOUCHED=NO"
echo "============================================================"
