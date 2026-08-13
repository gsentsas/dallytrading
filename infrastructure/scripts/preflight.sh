#!/usr/bin/env bash
# Contrôle de pré-vol avant déploiement DallyTrading.
#
# STRICTEMENT EN LECTURE SEULE. N'écrit rien, ne démarre rien, ne modifie rien.
# Conçu pour être exécuté par l'administrateur AVANT la première commande
# privilégiée, et rejoué après pour vérifier le résultat.
#
# Ce serveur héberge une vingtaine de domaines en production et une instance Odoo
# tierce (SEN CONTAINERS). Chaque contrôle ci-dessous existe parce que se tromper
# sur ce point casserait quelque chose qui n'appartient pas à DallyTrading.
#
#   bash infrastructure/scripts/preflight.sh

set -u

PLATFORM="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OK=0; WARN=0; KO=0

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; OK=$((OK+1)); }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
ko()   { printf '  \033[31m✗\033[0m %s\n' "$1"; KO=$((KO+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# ─── 1. Identité et privilèges ────────────────────────────────────────
head_ "1. Identité et privilèges"
echo "     utilisateur : $(id -un) (uid=$(id -u), groupes: $(id -Gn | tr ' ' ','))"
if [ "$(id -u)" -eq 0 ]; then
  ok "exécuté en root : les opérations privilégiées sont possibles"
elif sudo -n true 2>/dev/null; then
  ok "sudo sans mot de passe disponible"
else
  warn "ni root ni sudo — seuls les contrôles de lecture aboutiront"
fi

if docker info >/dev/null 2>&1; then
  ok "accès au démon Docker"
else
  ko "pas d'accès au démon Docker (socket refusé ou daemon arrêté)"
fi

# ─── 2. Ressources ────────────────────────────────────────────────────
head_ "2. Ressources"
MEM_MB=$(free -m | awk '/^Mem:/ {print $2}')
AVAIL_MB=$(free -m | awk '/^Mem:/ {print $7}')
[ "$AVAIL_MB" -ge 3000 ] \
  && ok "mémoire disponible : ${AVAIL_MB} Mo sur ${MEM_MB} Mo" \
  || ko "mémoire disponible insuffisante : ${AVAIL_MB} Mo (3 000 Mo attendus)"

DISK_AVAIL=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
[ "$DISK_AVAIL" -ge 20 ] \
  && ok "espace disque libre : ${DISK_AVAIL} Go" \
  || ko "espace disque insuffisant : ${DISK_AVAIL} Go"

SWAP_MB=$(free -m | awk '/^Swap:/ {print $2}')
if [ "$SWAP_MB" -eq 0 ]; then
  # Cf. DT-004 dans docs/SECURITY-FINDINGS.md. Sans swap, un pic mémoire fait
  # intervenir l'OOM killer, qui choisit sa victime parmi TOUS les processus de
  # la machine — y compris ceux des autres abonnements.
  warn "aucun swap configuré (DT-004 : 4 Gio recommandés sur cette machine partagée)"
else
  ok "swap : ${SWAP_MB} Mo"
fi

# ─── 3. Ports ─────────────────────────────────────────────────────────
head_ "3. Ports"
listening() { ss -lntH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"; }

for P in 18169 18172 3010; do
  listening "$P" \
    && warn "port $P déjà occupé — vérifier qu'il s'agit bien du service DallyTrading attendu" \
    || ok "port $P libre"
done

# SEN CONTAINERS. On vérifie sa présence pour NE PAS y toucher, pas pour l'utiliser.
if listening 18069; then
  ok "instance tierce SEN CONTAINERS détectée sur 18069 — à ne jamais modifier"
else
  warn "aucun service sur 18069 : l'instance SEN CONTAINERS semble arrêtée (ne pas intervenir)"
fi

# ─── 4. PostgreSQL non exposé ─────────────────────────────────────────
head_ "4. Exposition réseau"
if ss -lntH 2>/dev/null | awk '{print $4}' | grep -qE '^(0\.0\.0\.0|\[?::\]?):5432$'; then
  ko "PostgreSQL écoute sur toutes les interfaces — exposition publique"
else
  ok "aucun PostgreSQL sur 0.0.0.0:5432"
fi

if ss -lntH 2>/dev/null | awk '{print $4}' | grep -qE '^(0\.0\.0\.0|\[?::\]?):(18169|18172|3010)$'; then
  ko "un service DallyTrading écoute au-delà de la loopback"
else
  ok "aucun service DallyTrading au-delà de la loopback"
fi

# ─── 5. Secrets ───────────────────────────────────────────────────────
head_ "5. Secrets"
check_secret() {
  local key="$1" file="$2" min="$3"
  local val
  val=$(grep -E "^${key}=" "$file" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' ')
  if [ -z "$val" ]; then
    warn "$key vide dans $(basename "$file")"
  elif [ "${#val}" -lt "$min" ]; then
    ko "$key trop court (${#val} < $min) — probable valeur d'exemple"
  else
    ok "$key défini (${#val} caractères)"
  fi
}

if [ -f "$PLATFORM/.env" ]; then
  ok ".env présent"
  [ "$(stat -c '%a' "$PLATFORM/.env")" = "600" ] \
    && ok ".env en 0600" || ko ".env n'est pas en 0600"
  check_secret POSTGRES_PASSWORD "$PLATFORM/.env" 32
  check_secret ODOO_ADMIN_PASSWD "$PLATFORM/.env" 32
  check_secret BACKUP_ENCRYPTION_KEY "$PLATFORM/.env" 32
else
  ko ".env absent — exécuter infrastructure/scripts/generate-secrets.sh"
fi

if [ -f "$PLATFORM/odoo/config/odoo.conf" ]; then
  ok "odoo.conf généré"
  [ "$(stat -c '%a' "$PLATFORM/odoo/config/odoo.conf")" = "600" ] \
    && ok "odoo.conf en 0600" || ko "odoo.conf n'est pas en 0600"
  grep -qE '^list_db[[:space:]]*=[[:space:]]*False' "$PLATFORM/odoo/config/odoo.conf" \
    && ok "list_db = False" || ko "list_db n'est pas à False"
  grep -qE '^dbfilter[[:space:]]*=[[:space:]]*\^dallytrading\$' "$PLATFORM/odoo/config/odoo.conf" \
    && ok "dbfilter verrouillé sur dallytrading" || ko "dbfilter incorrect"
  grep -qE '^proxy_mode[[:space:]]*=[[:space:]]*True' "$PLATFORM/odoo/config/odoo.conf" \
    && ok "proxy_mode = True" || ko "proxy_mode n'est pas à True"
else
  ko "odoo.conf absent — exécuter infrastructure/scripts/render-config.sh"
fi

# ─── 6. Secrets hors de Git ───────────────────────────────────────────
head_ "6. Étanchéité Git"
cd "$PLATFORM" || exit 1
for F in .env odoo/config/odoo.conf apps/web/.env.production; do
  if git check-ignore -q "$F" 2>/dev/null; then
    ok "$F ignoré par Git"
  else
    ko "$F N'EST PAS ignoré par Git"
  fi
done

if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  ko ".env est SUIVI par Git"
else
  ok "aucun .env suivi par Git"
fi

# ─── 7. Frontend ──────────────────────────────────────────────────────
head_ "7. Frontend"
if [ -f "$PLATFORM/apps/web/.next/standalone/server.js" ]; then
  ok "build autonome présent (.next/standalone/server.js)"
else
  warn "build absent — exécuter npm run build dans apps/web"
fi

if [ -f "$PLATFORM/apps/web/.env.production" ]; then
  ok ".env.production présent"
  KEY=$(grep -E '^ODOO_API_KEY=' "$PLATFORM/apps/web/.env.production" | cut -d= -f2- | tr -d ' ')
  [ "${#KEY}" -ge 24 ] \
    && ok "ODOO_API_KEY renseignée" \
    || warn "ODOO_API_KEY vide — à créer dans Odoo après installation (le service refusera de démarrer sans elle)"
else
  ko "apps/web/.env.production absent"
fi

# ─── 8. Domaines ──────────────────────────────────────────────────────
head_ "8. Domaines"
for H in dallytrading.com www.dallytrading.com crm.dallytrading.com; do
  IP=$(getent hosts "$H" 2>/dev/null | awk '{print $1}' | head -1)
  [ -n "$IP" ] && ok "$H → $IP" || ko "$H ne résout pas"
done

for H in dallytrading.com crm.dallytrading.com; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$H/" 2>/dev/null)
  case "$CODE" in
    200) ok "https://$H/ → 200" ;;
    403) warn "https://$H/ → 403 (TLS valide, mais rien n'est servi)" ;;
    502|503) warn "https://$H/ → $CODE (proxy configuré, service arrêté)" ;;
    000) ko "https://$H/ injoignable ou erreur TLS" ;;
    *)   warn "https://$H/ → $CODE" ;;
  esac
done

EXP=$(echo | openssl s_client -servername dallytrading.com -connect dallytrading.com:443 2>/dev/null \
      | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$EXP" ]; then
  DAYS=$(( ( $(date -d "$EXP" +%s) - $(date +%s) ) / 86400 ))
  [ "$DAYS" -gt 21 ] \
    && ok "certificat TLS valide encore $DAYS jours" \
    || ko "certificat TLS expire dans $DAYS jours"
fi

# ─── Bilan ────────────────────────────────────────────────────────────
printf '\n──────────────────────────────────────\n'
printf '  %s OK · %s avertissement(s) · %s bloquant(s)\n' "$OK" "$WARN" "$KO"
[ "$KO" -eq 0 ] || exit 1
