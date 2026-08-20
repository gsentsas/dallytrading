#!/usr/bin/env bash
# Validation intégrée du lot A E-COMMERCE PRO sur une pile éphémère uniquement.
#
# Le script refuse le worktree de production, prépare les dépendances du worktree
# de développement, monte le harnais Odoo/PostgreSQL/Next jetable déjà éprouvé,
# met à jour dally_shop, exécute sa suite Odoo, vérifie les canaris de sécurité et
# rejoue les régressions navigateur boutique existantes via e2e-freight.sh.
#
# Aucune commande ne vise la base, les conteneurs ou les ports de production.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WEB="$ROOT/apps/web"
HARNESS="$HERE/e2e-freight.sh"
WORK="${FE2E_WORK_DIR:-${TMPDIR:-/tmp}/dallytrading-ecommerce-pro-e2e}"
DB="dallytrading_freight_e2e"
ODOO_CONTAINER="dallytrading-freight-e2e-odoo"
NEXT_PORT="${FE2E_NEXT_PORT:-3042}"
ODOO_PORT="${FE2E_ODOO_PORT:-18479}"
ODOO_TEST_HTTP_PORT="${FE2E_TEST_HTTP_PORT:-18179}"
PRODUCTION_WORKTREE="/var/www/vhosts/dallytrading.com/platform"
EXPECTED_MODULE_VERSION="19.0.1.5.0"

log() { printf '\n\033[1m── %s\033[0m\n' "$*"; }
fail() { echo "ERREUR: $*" >&2; exit 1; }

assert_isolated() {
  [ "$(readlink -f "$ROOT")" != "$PRODUCTION_WORKTREE" ] ||
    fail "recette interdite depuis le worktree production $PRODUCTION_WORKTREE"

  [ "$DB" != "dallytrading" ] || fail "base production interdite"
  [ "$DB" != "odoo_crm" ] || fail "base SEN CONTAINERS interdite"
  [ "$ODOO_CONTAINER" != "dallytrading-odoo" ] || fail "conteneur production interdit"

  case "$NEXT_PORT" in
    3000|3010|80|443) fail "port frontend réservé: $NEXT_PORT" ;;
  esac
  case "$ODOO_PORT" in
    18169|18172|18069|18072|18269|18369) fail "port Odoo réservé: $ODOO_PORT" ;;
  esac
}

assert_worktree_clean() {
  local dirty branch
  branch="$(git -C "$ROOT" branch --show-current)"
  printf '   branche: %s\n' "${branch:-DETACHED}"
  git -C "$ROOT" diff --check || fail "git diff --check"
  dirty="$(git -C "$ROOT" status --porcelain)"
  if [ -n "$dirty" ]; then
    printf '%s\n' "$dirty" >&2
    fail "worktree non propre"
  fi
}

prepare_frontend_dependencies() {
  if [ ! -f "$WEB/node_modules/next/package.json" ]; then
    log "dépendances frontend du worktree de recette"
    (
      cd "$WEB"
      npm ci --no-audit --no-fund
    ) || fail "npm ci du frontend de recette"
  fi
  [ -f "$WEB/node_modules/next/package.json" ] ||
    fail "Next.js absent après préparation des dépendances"
}

static_validation() {
  log "validation statique des addons"
  python3 "$HERE/validate-addons.py" "$ROOT/odoo/custom-addons" ||
    fail "validation statique des addons"
}

cleanup() {
  set +e
  FE2E_WORK_DIR="$WORK" FE2E_NEXT_PORT="$NEXT_PORT" FE2E_ODOO_PORT="$ODOO_PORT" \
    "$HARNESS" down >/dev/null 2>&1
}
trap cleanup EXIT INT TERM

start_stack() {
  log "pile jetable Odoo/PostgreSQL/Next"
  # Le harnais historique affiche la clé véhicule issue de la fixture. Elle est
  # éphémère, mais une recette ne doit jamais apprendre à ses opérateurs que les
  # secrets sont acceptables dans stdout.
  FE2E_WORK_DIR="$WORK" FE2E_NEXT_PORT="$NEXT_PORT" FE2E_ODOO_PORT="$ODOO_PORT" \
    "$HARNESS" up | sed -E 's/^([[:space:]]*VEHICLE_API_KEY=).*/\1<expurgé>/' ||
    fail "montage du harnais E2E"
}

run_odoo_tests() {
  log "upgrade dally_shop + tests Odoo"
  docker exec "$ODOO_CONTAINER" odoo \
    -c /etc/odoo/odoo.conf \
    -d "$DB" \
    -u dally_shop \
    --http-interface=127.0.0.1 \
    --http-port="$ODOO_TEST_HTTP_PORT" \
    --test-enable \
    --test-tags=dally_shop \
    --stop-after-init \
    > "$WORK/ecommerce-pro-tests.log" 2>&1 || {
      tail -140 "$WORK/ecommerce-pro-tests.log" >&2
      fail "tests Odoo dally_shop"
    }

  if grep -Eq 'Failed to load registry| CRITICAL ' "$WORK/ecommerce-pro-tests.log"; then
    grep -E 'Failed to load registry| CRITICAL ' \
      "$WORK/ecommerce-pro-tests.log" | tail -40 >&2
    fail "registre Odoo ou erreur critique pendant les tests"
  fi

  local result_line
  result_line="$(grep -E 'odoo\.tests\.result: [0-9]+ failed, [0-9]+ error\(s\) of [0-9]+ tests' \
    "$WORK/ecommerce-pro-tests.log" | tail -1 || true)"

  [ -n "$result_line" ] || {
    tail -140 "$WORK/ecommerce-pro-tests.log" >&2
    fail "résumé final des tests Odoo introuvable"
  }

  printf '   %s\n' "$result_line"
  printf '%s\n' "$result_line" \
    | grep -Eq 'odoo\.tests\.result: 0 failed, 0 error\(s\) of [1-9][0-9]* tests' \
    || fail "suite Odoo dally_shop non verte"
}

refresh_shop_runtime() {
  log "rafraîchissement runtime Odoo après upgrade"

  # L'upgrade/tests tourne dans un second processus Odoo. Avant d'exercer les
  # routes HTTP du PID 1, on redémarre uniquement le conteneur jetable afin que
  # le serveur long-vivant ouvre un registre construit sur la version qui vient
  # réellement d'être testée.
  docker restart "$ODOO_CONTAINER" >/dev/null || fail "redémarrage Odoo jetable"

  local ready=0
  for _ in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:${ODOO_PORT}/web/health" >/dev/null; then
      ready=1
      break
    fi
    sleep 1
  done
  [ "$ready" -eq 1 ] || {
    docker logs --tail 120 "$ODOO_CONTAINER" >&2 || true
    fail "Odoo jetable non sain après upgrade"
  }

  log "réamorçage boutique après tests"

  # Le harnais amorce la boutique avant les tests Odoo. Une suite de tests peut
  # légitimement créer/faire tourner des clés ou modifier une configuration dans
  # ses transactions. La frontière E2E doit donc repartir d'un état métier
  # déterministe APRES les tests, pas supposer que les secrets/configuration du
  # seed initial ont survécu inchangés.
  docker cp "$HERE/e2e-shop-seed.py" "$ODOO_CONTAINER:/tmp/e2e-seed/shop.py" >/dev/null
  docker exec "$ODOO_CONTAINER" sh -c \
    "odoo shell -c /etc/odoo/odoo.conf -d $DB --no-http < /tmp/e2e-seed/shop.py" \
    > "$WORK/shop-reseed.out" 2>&1 || {
      tail -80 "$WORK/shop-reseed.out" >&2
      fail "réamorçage boutique"
    }

  grep -E '^SHOP_' "$WORK/shop-reseed.out" \
    | sed -E 's/^(SHOP_API_KEY_[A-Z]+=).*/\1<expurgé>/' | sed 's/^/   /'
  grep -q '^SHOP_SEED_OK$' "$WORK/shop-reseed.out" || {
    tail -80 "$WORK/shop-reseed.out" >&2
    fail "marqueur SHOP_SEED_OK absent"
  }

  # Remplace atomiquement les références boutique du seed initial. Le reste des
  # références fret/véhicule/groupage reste intact.
  local refs_tmp="$WORK/freight-refs.new"
  grep -v '^SHOP_' "$WORK/freight-refs" > "$refs_tmp" || true
  grep -E '^SHOP_[A-Z0-9_]+=' "$WORK/shop-reseed.out" >> "$refs_tmp"
  mv "$refs_tmp" "$WORK/freight-refs"
  chmod 600 "$WORK/freight-refs"

  # shellcheck disable=SC1090
  set -a; . "$WORK/freight-refs"; set +a
  [ -n "${SHOP_API_KEY_READ:-}" ] || fail "clé shop:read absente après réamorçage"
  [ -n "${SHOP_API_KEY_CHECKOUT:-}" ] || fail "clé shop:checkout absente après réamorçage"

  # Le serveur Next isolé est lancé plus tard par le harnais et source ce fichier
  # à chaque redémarrage. On remplace donc les deux secrets sans rebuild et sans
  # les imprimer.
  local env_tmp="$WORK/web/.env.local.new"
  awk \
    -v read_key="$SHOP_API_KEY_READ" \
    -v checkout_key="$SHOP_API_KEY_CHECKOUT" '
      /^ODOO_API_KEY_SHOP_READ=/ {
        print "ODOO_API_KEY_SHOP_READ=" read_key
        next
      }
      /^ODOO_API_KEY_SHOP_CHECKOUT=/ {
        print "ODOO_API_KEY_SHOP_CHECKOUT=" checkout_key
        next
      }
      { print }
    ' "$WORK/web/.env.local" > "$env_tmp"
  mv "$env_tmp" "$WORK/web/.env.local"
  chmod 600 "$WORK/web/.env.local"

  # Sonde directe avant Playwright : un échec ici donne le statut de l'API Odoo
  # au lieu de produire trente erreurs UI en cascade.
  local body="$WORK/shop-runtime-probe.json" code
  code="$(curl -sS -o "$body" -w '%{http_code}' \
    -H "X-API-Key: $SHOP_API_KEY_READ" \
    "http://127.0.0.1:${ODOO_PORT}/api/v1/shop/products?limit=5")"
  if [ "$code" != "200" ] || ! grep -q 'e2e-groupe-5kva' "$body"; then
    echo "   HTTP catalogue: $code" >&2
    sed -E 's/[A-Za-z0-9_-]{28,}/<expurgé>/g' "$body" >&2 || true
    fail "sonde catalogue Odoo après tests"
  fi

  echo "   SHOP_RUNTIME_OK"
}

verify_release_models() {
  log "canaris structurels E-commerce Pro Lot A"
  docker exec -i "$ODOO_CONTAINER" \
    odoo shell -c /etc/odoo/odoo.conf -d "$DB" --no-http <<PY
from odoo.tools.safe_eval import safe_eval

module = env['ir.module.module'].search([('name', '=', 'dally_shop')], limit=1)
assert module and module.state == 'installed'
assert module.latest_version == '$EXPECTED_MODULE_VERSION', module.latest_version

operations = env.ref('dally_shop.group_dally_shop_operations')
readonly = env.ref('dally_core.group_dally_readonly')
assert readonly in operations.implied_ids

menu = env.ref('dally_shop.menu_dally_shop_orders')
action = env.ref('dally_shop.dally_shop_order_action')
assert menu.active
assert operations in menu.group_ids
assert action.res_model == 'sale.order'
assert ('dally_shop_order', '=', True) in safe_eval(action.domain)

rule_order = env.ref('dally_shop.rule_shop_operations_orders')
rule_line = env.ref('dally_shop.rule_shop_operations_order_lines')
assert rule_order.active and rule_line.active
assert "dally_shop_order" in rule_order.domain_force
assert "order_id.dally_shop_order" in rule_line.domain_force
assert rule_order.perm_read and not rule_order.perm_write and not rule_order.perm_create and not rule_order.perm_unlink
assert rule_line.perm_read and not rule_line.perm_write and not rule_line.perm_create and not rule_line.perm_unlink

print('ECOMMERCE_PRO_LOT_A_CANARIES_OK')
env.cr.rollback()
PY
}

run_browser_regressions() {
  log "régressions navigateur et base existantes"
  FE2E_WORK_DIR="$WORK" FE2E_NEXT_PORT="$NEXT_PORT" FE2E_ODOO_PORT="$ODOO_PORT" \
    "$HARNESS" test || fail "suite E2E existante"
}

main() {
  assert_isolated
  assert_worktree_clean
  static_validation
  prepare_frontend_dependencies
  start_stack
  run_odoo_tests
  refresh_shop_runtime
  verify_release_models
  run_browser_regressions
  assert_worktree_clean

  printf '\n============================================================\n'
  printf ' ECOMMERCE PRO LOT A — RELEASE CANDIDATE VALIDATED\n'
  printf ' Production touched: NO\n'
  printf ' Production DB: NO\n'
  printf ' Production frontend: NO\n'
  printf '============================================================\n'
}

main "$@"
