#!/usr/bin/env bash
# Validation intégrée E-COMMERCE PRO Lot C sur une pile éphémère uniquement.
#
# Le Lot C ajoute méthodes de remise, adresse, frais et autorisation explicite de
# préparation. Le checkout et la validation commerciale doivent rester sans effet
# Sale/Stock/Facturation ; seule l'autorisation de préparation peut confirmer la
# vente native. La recette refuse le worktree de production, upgrade dally_shop,
# exécute ses tests, contrôle les canaris Lot B + C puis rejoue les régressions.
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
EXPECTED_MODULE_VERSION="19.0.1.7.0"

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

frontend_validation() {
  log "validation frontend E-commerce Pro Lot C"
  (
    cd "$WEB"
    npm run verify
  ) || fail "validation frontend"
}

cleanup() {
  set +e
  FE2E_WORK_DIR="$WORK" FE2E_NEXT_PORT="$NEXT_PORT" FE2E_ODOO_PORT="$ODOO_PORT" \
    "$HARNESS" down >/dev/null 2>&1
}
trap cleanup EXIT INT TERM

start_stack() {
  log "pile jetable Odoo/PostgreSQL/Next"
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
      tail -180 "$WORK/ecommerce-pro-tests.log" >&2
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
    tail -180 "$WORK/ecommerce-pro-tests.log" >&2
    fail "résumé final des tests Odoo introuvable"
  }

  printf '   %s\n' "$result_line"
  printf '%s\n' "$result_line" \
    | grep -Eq 'odoo\.tests\.result: 0 failed, 0 error\(s\) of [1-9][0-9]* tests' \
    || fail "suite Odoo dally_shop non verte"
}

refresh_shop_runtime() {
  log "rafraîchissement runtime Odoo après upgrade"
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
  docker cp "$HERE/e2e-shop-seed.py" "$ODOO_CONTAINER:/tmp/e2e-seed/shop.py" >/dev/null
  docker exec "$ODOO_CONTAINER" sh -c \
    "odoo shell -c /etc/odoo/odoo.conf -d $DB --no-http < /tmp/e2e-seed/shop.py" \
    > "$WORK/shop-reseed.out" 2>&1 || {
      tail -100 "$WORK/shop-reseed.out" >&2
      fail "réamorçage boutique"
    }

  grep -E '^SHOP_' "$WORK/shop-reseed.out" \
    | sed -E 's/^(SHOP_API_KEY_[A-Z]+=).*/\1<expurgé>/' | sed 's/^/   /'
  grep -q '^SHOP_SEED_OK$' "$WORK/shop-reseed.out" || {
    tail -100 "$WORK/shop-reseed.out" >&2
    fail "marqueur SHOP_SEED_OK absent"
  }

  local refs_tmp="$WORK/freight-refs.new"
  grep -v '^SHOP_' "$WORK/freight-refs" > "$refs_tmp" || true
  grep -E '^SHOP_[A-Z0-9_]+=' "$WORK/shop-reseed.out" >> "$refs_tmp"
  mv "$refs_tmp" "$WORK/freight-refs"
  chmod 600 "$WORK/freight-refs"

  # shellcheck disable=SC1090
  set -a; . "$WORK/freight-refs"; set +a
  [ -n "${SHOP_API_KEY_READ:-}" ] || fail "clé shop:read absente après réamorçage"
  [ -n "${SHOP_API_KEY_CHECKOUT:-}" ] || fail "clé shop:checkout absente après réamorçage"

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

  local body="$WORK/shop-runtime-probe.json" code
  code="$(curl -sS -o "$body" -w '%{http_code}' \
    -H "X-API-Key: $SHOP_API_KEY_READ" \
    "http://127.0.0.1:${ODOO_PORT}/api/v1/shop/products?limit=5")"
  if [ "$code" != "200" ] || ! grep -q 'e2e-groupe-5kva' "$body"; then
    echo "   HTTP catalogue: $code" >&2
    sed -E 's/[A-Za-z0-9_-]{28,}/<expurgé>/g' "$body" >&2 || true
    fail "sonde catalogue Odoo après tests"
  fi

  local delivery_body="$WORK/shop-delivery-methods.json" delivery_code
  delivery_code="$(curl -sS -o "$delivery_body" -w '%{http_code}' \
    -H "X-API-Key: $SHOP_API_KEY_READ" \
    "http://127.0.0.1:${ODOO_PORT}/api/v1/shop/delivery-methods")"
  if [ "$delivery_code" != "200" ] || \
     ! grep -q '"code":"pickup"' "$delivery_body" || \
     ! grep -q '"code":"delivery_to_confirm"' "$delivery_body"; then
    echo "   HTTP méthodes de remise: $delivery_code" >&2
    cat "$delivery_body" >&2 || true
    fail "sonde méthodes de remise Odoo"
  fi

  echo "   SHOP_RUNTIME_OK"
  echo "   SHOP_DELIVERY_RUNTIME_OK"
}

verify_release_models() {
  log "canaris structurels E-commerce Pro Lots B + C"
  docker exec -i "$ODOO_CONTAINER" \
    odoo shell -c /etc/odoo/odoo.conf -d "$DB" --no-http <<PY
import uuid
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
rule_transition = env.ref('dally_shop.rule_shop_operations_transitions')
for rule in (rule_order, rule_line, rule_transition):
    assert rule.active
    assert rule.perm_read
    assert not rule.perm_write and not rule.perm_create and not rule.perm_unlink

Order = env['sale.order']
Transition = env['dally.shop.order.transition']
DeliveryMethod = env['dally.shop.delivery.method']
FulfillmentEvent = env['dally.shop.fulfillment.event']

assert set(dict(Order._fields['dally_shop_workflow_state'].selection)) == {
    'received', 'validated', 'rejected', 'cancelled'
}
assert set(dict(Order._fields['dally_shop_delivery_fee_state'].selection)) == {
    'free', 'fixed', 'pending_quote', 'quoted'
}
assert set(dict(Order._fields['dally_shop_fulfillment_state'].selection)) == {
    'pending', 'preparing', 'ready', 'out_for_delivery', 'delivered', 'picked_up'
}
for field_name in (
    'dally_shop_delivery_method_id',
    'dally_shop_delivery_fee',
    'dally_shop_shipping_street',
    'dally_shop_fulfillment_authorized',
    'dally_shop_fulfillment_event_ids',
):
    assert field_name in Order._fields
assert Transition._name == 'dally.shop.order.transition'
assert FulfillmentEvent._name == 'dally.shop.fulfillment.event'

pickup = env.ref('dally_shop.delivery_method_pickup')
delivery = env.ref('dally_shop.delivery_method_delivery_to_confirm')
assert pickup.active and pickup.code == 'pickup'
assert pickup.kind == 'pickup' and pickup.fee_policy == 'free'
assert not pickup.requires_address
assert delivery.active and delivery.code == 'delivery_to_confirm'
assert delivery.kind == 'delivery' and delivery.fee_policy == 'quote'
assert delivery.requires_address
public_methods = DeliveryMethod._dally_shop_public_methods()
assert {'pickup', 'delivery_to_confirm'} <= {item['code'] for item in public_methods}
assert all('id' not in item for item in public_methods)

form_arch = env.ref('dally_shop.view_dally_shop_order_form').arch_db
for method in (
    'action_dally_shop_validate',
    'action_dally_shop_open_reject',
    'action_dally_shop_open_cancel',
    'action_dally_shop_open_delivery_fee',
    'action_dally_shop_authorize_fulfillment',
    'action_dally_shop_mark_ready',
    'action_dally_shop_dispatch',
    'action_dally_shop_complete_fulfillment',
):
    assert method in form_arch
assert 'action_confirm' not in form_arch

product = env['product.template'].search([
    ('dally_shop_slug', '=', 'e2e-groupe-5kva'),
    ('dally_published', '=', True),
], limit=1)
assert product
partner = env['res.partner'].create({
    'name': 'Canari Livraison Lot C',
    'email': 'delivery-canary@e2e.invalid',
    'phone': '+221770000009',
    'street': '1 rue du Canari',
    'city': 'Dakar',
})
lines = env['product.template']._dally_shop_resolve_lines([
    (product.dally_shop_slug, 1),
])
order = Order.dally_shop_place_order(
    str(uuid.uuid4()),
    partner,
    lines,
    'delivery_to_confirm',
    invite=False,
)

# Checkout : workflow reçu, frais inconnus, aucun effet natif.
assert order.state == 'draft'
assert order.dally_shop_workflow_state == 'received'
assert order.dally_shop_delivery_method_id == delivery
assert order.dally_shop_delivery_fee_state == 'pending_quote'
assert order.dally_shop_delivery_fee == 0
assert order.dally_shop_shipping_street == partner.street
assert order.dally_shop_shipping_city == partner.city
assert order.dally_shop_fulfillment_state == 'pending'
assert not order.dally_shop_fulfillment_authorized
assert order._dally_shop_delivery_grand_total() is None
assert not order.invoice_ids
assert not env['stock.picking'].search_count([('origin', '=', order.name)])

projection = order._dally_shop_projection()
assert projection['deliveryMode'] == 'delivery_to_confirm'
assert projection['delivery']['fee']['status'] == 'pending_quote'
assert projection['delivery']['fee']['amount'] is None
assert projection['delivery']['shippingAddress']['street'] == partner.street
assert projection['grandTotal'] is None
assert 'partner_id' not in str(projection)
assert 'delivery_method_id' not in str(projection)

# Validation commerciale Lot B : toujours aucun effet natif.
order.action_dally_shop_validate()
assert order.state == 'draft'
assert order.dally_shop_workflow_state == 'validated'
assert Transition.search_count([
    ('order_id', '=', order.id), ('to_state', '=', 'validated')
]) == 1
assert not order.invoice_ids
assert not env['stock.picking'].search_count([('origin', '=', order.name)])

# Cotation : total connu, mais vente toujours brouillon.
order._dally_shop_set_delivery_fee(3500.0)
assert order.dally_shop_delivery_fee_state == 'quoted'
assert order.dally_shop_delivery_fee == 3500.0
assert order._dally_shop_delivery_grand_total() == order.amount_total + 3500.0
assert order.state == 'draft'
assert not order.invoice_ids
assert not env['stock.picking'].search_count([('origin', '=', order.name)])

# Autorisation explicite : seul moment du canari où la vente native est confirmée.
order.action_dally_shop_authorize_fulfillment()
assert order.state == 'sale'
assert order.dally_shop_fulfillment_authorized
assert order.dally_shop_fulfillment_state == 'preparing'
assert order.dally_shop_fulfillment_authorized_at
assert FulfillmentEvent.search_count([
    ('order_id', '=', order.id), ('to_state', '=', 'preparing')
]) == 1
assert not order.invoice_ids

# Rejeu : aucune seconde autorisation ni second événement.
before_events = FulfillmentEvent.search_count([('order_id', '=', order.id)])
order.action_dally_shop_authorize_fulfillment()
assert FulfillmentEvent.search_count([('order_id', '=', order.id)]) == before_events

# Parcours livraison borné.
order.action_dally_shop_mark_ready()
assert order.dally_shop_fulfillment_state == 'ready'
order.action_dally_shop_dispatch()
assert order.dally_shop_fulfillment_state == 'out_for_delivery'
order.action_dally_shop_complete_fulfillment()
assert order.dally_shop_fulfillment_state == 'delivered'

print('ECOMMERCE_PRO_LOT_C_CANARIES_OK')
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
  frontend_validation
  start_stack
  run_odoo_tests
  refresh_shop_runtime
  verify_release_models
  run_browser_regressions
  assert_worktree_clean

  printf '\n============================================================\n'
  printf ' ECOMMERCE PRO LOT C — RELEASE CANDIDATE VALIDATED\n'
  printf ' Production touched: NO\n'
  printf ' Production DB: NO\n'
  printf ' Production frontend: NO\n'
  printf ' Checkout native sale confirmation: NO\n'
  printf ' Commercial validation native sale confirmation: NO\n'
  printf ' Delivery fee quote native sale confirmation: NO\n'
  printf ' Explicit fulfillment authorization may confirm Sale: YES\n'
  printf ' Automatic invoice / payment: NO\n'
  printf '============================================================\n'
}

main "$@"
