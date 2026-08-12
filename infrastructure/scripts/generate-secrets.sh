#!/usr/bin/env bash
#
# Crée .env depuis .env.example et y injecte des secrets aléatoires.
#
# Idempotent : un secret déjà renseigné n'est JAMAIS écrasé. Régénérer
# POSTGRES_PASSWORD après l'initialisation de la base rendrait Odoo
# incapable de s'y connecter (le rôle PostgreSQL garde l'ancien mot de
# passe), d'où cette protection.
#
# Usage : ./infrastructure/scripts/generate-secrets.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
EXAMPLE_FILE="${ROOT_DIR}/.env.example"

log()  { printf '[generate-secrets] %s\n' "$*"; }
fail() { printf '[generate-secrets] ERREUR : %s\n' "$*" >&2; exit 1; }

command -v openssl >/dev/null || fail "openssl est requis."
[[ -f "${EXAMPLE_FILE}" ]] || fail "introuvable : ${EXAMPLE_FILE}"

umask 077
if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${EXAMPLE_FILE}" "${ENV_FILE}"
  log "créé .env depuis .env.example"
fi
chmod 600 "${ENV_FILE}"

# Secrets à générer : NOM:LONGUEUR_EN_OCTETS (hex → 2× en caractères)
SECRETS=(
  "POSTGRES_PASSWORD:32"
  "ODOO_ADMIN_PASSWD:32"
  "BACKUP_ENCRYPTION_KEY:32"
)

for entry in "${SECRETS[@]}"; do
  key="${entry%%:*}"
  bytes="${entry##*:}"

  # Lecture robuste : on retire un éventuel commentaire de fin de ligne
  # puis les espaces. Sans cela, une ligne « CLE=   # openssl rand -hex 32 »
  # serait interprétée comme un secret déjà renseigné de 43 caractères —
  # et ce commentaire finirait par servir de mot de passe.
  current="$(sed -n -E "s/^${key}=(.*)$/\1/p" "${ENV_FILE}" | head -1)"
  current="${current%%#*}"
  current="$(printf '%s' "${current}" | tr -d '[:space:]')"

  if [[ -n "${current}" ]]; then
    if (( ${#current} < 24 )); then
      fail "${key} contient une valeur trop courte (${#current} caractères) et non générée.
       Videz cette ligne dans .env puis relancez, ou renseignez un secret d'au moins 24 caractères."
    fi
    log "${key} : déjà défini, conservé (${#current} caractères)"
    continue
  fi

  value="$(openssl rand -hex "${bytes}")"

  if grep -qE "^${key}=" "${ENV_FILE}"; then
    # Remplacement via un fichier temporaire dans le même répertoire,
    # pour que le renommage final soit atomique.
    tmp="$(mktemp "${ROOT_DIR}/.env.XXXXXX")"
    chmod 600 "${tmp}"
    # La valeur est du hex : aucun caractère à échapper pour awk.
    awk -v k="${key}" -v v="${value}" \
      'BEGIN{FS=OFS="="} $1==k && !done {print k "=" v; done=1; next} {print}' \
      "${ENV_FILE}" > "${tmp}"
    mv "${tmp}" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi

  log "${key} : généré (${bytes} octets)"
done

chmod 600 "${ENV_FILE}"

echo
log "Terminé. Secrets restant à renseigner MANUELLEMENT dans .env :"
log "  ODOO_API_KEY    — à créer depuis Odoo (cf. docs/API.md), après installation"
log "  SMTP_*          — fournis par votre hébergeur de messagerie"
log "  S3_*            — stockage distant des sauvegardes"
log "  ALERT_EMAIL     — destinataire des alertes de supervision"
echo
log "Vérifiez que .env n'est pas suivi par Git :"
log "  git check-ignore -v .env"
