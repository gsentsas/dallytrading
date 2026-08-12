#!/usr/bin/env bash
#
# Génère odoo/config/odoo.conf depuis odoo.conf.template + .env
#
# Raison d'être : Odoo ne sait pas interpoler de variables
# d'environnement dans son fichier de configuration. L'alternative
# (passer --db_password en ligne de commande) exposerait le mot de
# passe à tout utilisateur du serveur via `ps aux` — fuite constatée
# sur l'autre instance Odoo de cette machine.
#
# Usage : ./infrastructure/scripts/render-config.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ENV_FILE="${ROOT_DIR}/.env"
TEMPLATE="${ROOT_DIR}/odoo/config/odoo.conf.template"
OUTPUT="${ROOT_DIR}/odoo/config/odoo.conf"

log()  { printf '[render-config] %s\n' "$*"; }
fail() { printf '[render-config] ERREUR : %s\n' "$*" >&2; exit 1; }

[[ -f "${ENV_FILE}" ]] || fail ".env introuvable. Faites : cp .env.example .env puis remplissez-le."
[[ -f "${TEMPLATE}" ]] || fail "Modèle introuvable : ${TEMPLATE}"

# Charger .env sans l'exécuter comme du shell arbitraire.
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

# Variables obligatoires : échouer bruyamment plutôt que de produire
# une configuration à moitié vide qui casserait au démarrage.
REQUIRED=(
  ODOO_ADMIN_PASSWD ODOO_DB_NAME
  POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_PASSWORD
  ODOO_WORKERS ODOO_MAX_CRON_THREADS
  ODOO_LIMIT_MEMORY_SOFT ODOO_LIMIT_MEMORY_HARD
  ODOO_LIMIT_TIME_CPU ODOO_LIMIT_TIME_REAL ODOO_LOG_LEVEL
)
missing=()
for var in "${REQUIRED[@]}"; do
  [[ -n "${!var:-}" ]] || missing+=("${var}")
done
if (( ${#missing[@]} > 0 )); then
  fail "variables non définies dans .env : ${missing[*]}"
fi

# Refuser les secrets laissés vides ou manifestement factices.
for secret in ODOO_ADMIN_PASSWD POSTGRES_PASSWORD; do
  value="${!secret}"
  if (( ${#value} < 24 )); then
    fail "${secret} fait ${#value} caractères (minimum 24). Utilisez generate-secrets.sh."
  fi
  case "${value,,}" in
    *changeme*|*password*|*admin*|*secret*|*example*|*openssl*|*rand*|'#'*)
      fail "${secret} contient une valeur factice ou un fragment de commentaire.
       Videz cette ligne dans .env puis relancez generate-secrets.sh." ;;
  esac

  # Les secrets générés sont hexadécimaux : tout autre caractère signale
  # une valeur saisie à la main ou un commentaire mal découpé.
  if [[ ! "${value}" =~ ^[0-9a-fA-F]{24,}$ ]]; then
    fail "${secret} n'est pas une chaîne hexadécimale d'au moins 24 caractères.
       Attendu : sortie de « openssl rand -hex 32 ». Utilisez generate-secrets.sh."
  fi
done

# Substituer uniquement les variables attendues : une occurrence de
# `$` non prévue dans le modèle ne doit pas être avalée.
VARS='${ODOO_ADMIN_PASSWD} ${ODOO_DB_NAME} ${POSTGRES_HOST} ${POSTGRES_PORT}
${POSTGRES_USER} ${POSTGRES_PASSWORD} ${ODOO_WORKERS} ${ODOO_MAX_CRON_THREADS}
${ODOO_LIMIT_MEMORY_SOFT} ${ODOO_LIMIT_MEMORY_HARD} ${ODOO_LIMIT_TIME_CPU}
${ODOO_LIMIT_TIME_REAL} ${ODOO_LOG_LEVEL}'

umask 077
envsubst "${VARS}" < "${TEMPLATE}" > "${OUTPUT}"
chmod 600 "${OUTPUT}"

# Aucun ${...} ne doit subsister : cela signifierait une variable oubliée.
if grep -q '\${' "${OUTPUT}"; then
  grep -n '\${' "${OUTPUT}" >&2
  rm -f "${OUTPUT}"
  fail "des variables n'ont pas été substituées (voir ci-dessus). Fichier supprimé."
fi

log "généré : ${OUTPUT} (0600)"
log "workers=${ODOO_WORKERS} cron=${ODOO_MAX_CRON_THREADS} base=${ODOO_DB_NAME} list_db=False"
log "Rappel : ce fichier contient le mot de passe DB. Jamais dans Git."
