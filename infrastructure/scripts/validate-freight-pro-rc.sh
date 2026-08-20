#!/usr/bin/env bash
# Validation intégrée du lot FREIGHT PRO sur une pile éphémère uniquement.
#
# Ce script orchestre le harnais fret existant, installe les nouveaux modules
# DallyTrading sur la base jetable, exécute les tests Odoo du lot, la suite E2E
# existante, puis la spec navigateur du formulaire public structuré.
#
# Aucune commande ne vise la production. Le nettoyage délègue exclusivement à
# e2e-freight.sh, qui détruit son propre projet Docker et ses propres volumes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WEB="$ROOT/apps/web"
HARNESS="$HERE/e2e-freight.sh"
WORK="${FE2E_WORK_DIR:-${TMPDIR:-/tmp}/dallytrading-freight-e2e}"
DB="dallytrading_freight_e2e"
ODOO_CONTAINER="dallytrading-freight-e2e-odoo"
NEXT_PORT="${FE2E_NEXT_PORT:-3030}"
ODOO_PORT="${FE2E_ODOO_PORT:-18379}"
BASE_URL="http://127.0.0.1:${NEXT_PORT}"
PLAYWRIGHT_IMAGE="${FE2E_PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.62.1-noble}"

# Le harnais historique installe déjà le noyau Freight/Portal/Shop. On ajoute
# ici le reste du lot et les deux modules voisins dont la non-régression est
# explicitement exigée par le chantier.
NEW_MODULES="dally_sourcing,dally_trade,dally_freight_data,dally_freight_routing,dally_freight_dashboard,dally_freight_notifications"
TEST_MODULES="dally_core,dally_crm,dally_api,dally_freight,dally_tracking,dally_portal,dally_freight_bridge,dally_shop,dally_sourcing,dally_trade,dally_freight_data,dally_freight_routing,dally_freight_dashboard,dally_freight_notifications"

log() { printf '\n\033[1m── %s\033[0m\n' "$*"; }
fail() { echo "ERREUR: $*" >&2; exit 1; }

assert_isolated() {
  [ "$DB" != "dallytrading" ] || fail "base de production interdite"
  [ "$DB" != "odoo_crm" ] || fail "base SEN CONTAINERS interdite"
  case "$ODOO_PORT" in
    18169|18172|18069|18072|18269|18369) fail "port Odoo réservé: $ODOO_PORT" ;;
  esac
  case "$NEXT_PORT" in
    3000|3010|80|443) fail "port frontend réservé: $NEXT_PORT" ;;
  esac
  [ "$ODOO_CONTAINER" != "dallytrading-odoo" ] || fail "conteneur production interdit"
}

cleanup() {
  set +e
  "$HARNESS" down >/dev/null 2>&1
}
trap cleanup EXIT INT TERM

install_release_modules() {
  log "installation des modules FREIGHT PRO sur la base jetable"
  docker exec "$ODOO_CONTAINER" odoo -c /etc/odoo/odoo.conf -d "$DB" \
    -i "$NEW_MODULES" --stop-after-init > "$WORK/freight-pro-install.log" 2>&1 || {
      tail -80 "$WORK/freight-pro-install.log" >&2
      fail "installation des modules FREIGHT PRO"
    }

  if grep -Eq ' (ERROR|CRITICAL) |Traceback|Failed to load registry' "$WORK/freight-pro-install.log"; then
    grep -E ' (ERROR|CRITICAL) |Traceback|Failed to load registry' \
      "$WORK/freight-pro-install.log" | tail -40 >&2
    fail "journal d'installation non propre"
  fi
}

run_odoo_tests() {
  log "tests Odoo du lot complet"
  docker exec "$ODOO_CONTAINER" odoo -c /etc/odoo/odoo.conf -d "$DB" \
    -u "$TEST_MODULES" \
    --test-enable --test-tags=dally --stop-after-init \
    > "$WORK/freight-pro-tests.log" 2>&1 || {
      tail -120 "$WORK/freight-pro-tests.log" >&2
      fail "tests Odoo"
    }

  if grep -Eq ' (ERROR|CRITICAL) |Traceback|Failed to load registry|FAILED' "$WORK/freight-pro-tests.log"; then
    grep -E ' (ERROR|CRITICAL) |Traceback|Failed to load registry|FAILED' \
      "$WORK/freight-pro-tests.log" | tail -60 >&2
    fail "journal de tests Odoo non propre"
  fi

  grep -E '[0-9]+ tests|0 failed|0 error' "$WORK/freight-pro-tests.log" | tail -10 || true
}

verify_release_models() {
  log "canaris structurels FREIGHT PRO"
  docker exec -i "$ODOO_CONTAINER" \
    odoo shell -c /etc/odoo/odoo.conf -d "$DB" --no-http <<'PY'
Policy = env['dally.freight.state.policy']
Notification = env['dally.shipment.notification']
Port = env['freight.port']
Route = env['freight.frequent.route']

assert Policy.search_count([]) == 14
assert Policy.search_count([('visible_in_portal', '=', True)]) == 13
assert Policy.search_count([('notify_customer', '=', True)]) == 12
assert Port.search_count([('ocean', '=', True)]) >= 19
assert Port.search_count([('air', '=', True)]) >= 9
assert Route.search_count([]) >= 10
assert 'language_code' in Notification._fields
assert 'manual_retry_count' in Notification._fields

cron = env.ref('dally_freight_notifications.ir_cron_dally_freight_notification_delivery')
assert cron.active
assert cron.interval_number == 15
assert cron.interval_type == 'minutes'

vendor_menu = env.ref('tk_freight.dasboard_id')
dally_menu = env.ref('dally_freight_dashboard.menu_dally_freight_dashboard')
assert not vendor_menu.active
assert dally_menu.active

assert env['dally.trade.opportunity']
assert env['dally.sourcing.request']

print('FREIGHT_PRO_CANARIES_OK')
env.cr.rollback()
PY
}

run_browser_suite() {
  log "suite E2E fret existante"
  "$HARNESS" test

  log "E2E formulaire public structuré"
  docker run --rm --network host --label com.dallytrading.freight-e2e=true \
    -v "$WEB:/work:ro" -w /work \
    -e HOME=/tmp \
    -e E2E_BASE_URL="$BASE_URL" \
    --user "$(id -u):$(id -g)" \
    "$PLAYWRIGHT_IMAGE" \
    npx playwright test --output=/tmp/pw-out e2e/17-devis-routing.spec.ts
}

verify_public_routing_submission() {
  log "vérification en base du devis public structuré"
  docker exec -i "$ODOO_CONTAINER" \
    odoo shell -c /etc/odoo/odoo.conf -d "$DB" --no-http <<'PY'
Quote = env['dally.quote.request']
quotes = Quote.search([
    ('origin_port_id.code', '=', 'FRLEH'),
    ('destination_port_id.code', '=', 'SNDKR'),
], order='id desc', limit=5)
assert quotes, 'aucun devis public Le Havre -> Dakar trouvé'
quote = quotes[0]
assert quote.origin_port_id.code == 'FRLEH'
assert quote.destination_port_id.code == 'SNDKR'
if quote.incoterm_id:
    assert quote.incoterm_id.code == 'FOB'
print('FREIGHT_PUBLIC_ROUTING_DB_OK', quote.reference)
env.cr.rollback()
PY
}

assert_worktree_clean() {
  log "garde-fou Git"
  local branch dirty
  branch="$(git -C "$ROOT" branch --show-current)"
  printf '   branche: %s\n' "$branch"
  git -C "$ROOT" diff --check
  dirty="$(git -C "$ROOT" status --porcelain)"
  if [ -n "$dirty" ]; then
    printf '%s\n' "$dirty" >&2
    fail "worktree non propre avant validation"
  fi
}

main() {
  assert_isolated
  assert_worktree_clean

  log "montage de la pile jetable"
  "$HARNESS" up

  install_release_modules
  run_odoo_tests
  verify_release_models
  run_browser_suite
  verify_public_routing_submission

  log "FREIGHT PRO — RELEASE CANDIDATE VALIDATED"
  echo "   Production touched: NO"
  echo "   Vendor upgrade: NO"
  echo "   Legacy draft migration: NO"
}

main "$@"
