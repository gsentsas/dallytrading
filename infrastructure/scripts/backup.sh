#!/usr/bin/env bash
#
# DALLYTRADING — Sauvegarde Odoo (base + filestore, atomique)
#
# RÈGLE FONDAMENTALE : la base PostgreSQL et le filestore Odoo doivent
# constituer UNE SEULE sauvegarde logique. Un dump de base sans le
# filestore correspondant produit des pièces jointes orphelines : les
# enregistrements référencent des fichiers absents. Les deux artefacts
# portent donc le même horodatage et vivent dans le même répertoire.
#
# Produit, dans ${BACKUP_DIR}/<horodatage>/ :
#   database.dump      pg_dump format custom (compressé, restauration sélective)
#   filestore.tar.gz   /var/lib/odoo du conteneur Odoo
#   manifest.json      métadonnées : versions, tailles, empreintes
#   SHA256SUMS         empreintes vérifiables
#
# Usage :
#   ./infrastructure/scripts/backup.sh              # sauvegarde quotidienne
#   ./infrastructure/scripts/backup.sh --tag weekly # étiquette de rétention
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

TAG="daily"
while (( $# > 0 )); do
  case "$1" in
    --tag) TAG="${2:?--tag requiert une valeur}"; shift 2 ;;
    *) printf 'Option inconnue : %s\n' "$1" >&2; exit 2 ;;
  esac
done

log()  { printf '[backup][%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
fail() { printf '[backup] ERREUR : %s\n' "$*" >&2; exit 1; }

[[ -f "${ENV_FILE}" ]] || fail ".env introuvable."
set -a; source "${ENV_FILE}"; set +a

: "${POSTGRES_USER:?absent de .env}"
: "${POSTGRES_DB:?absent de .env}"
: "${ODOO_DB_NAME:?absent de .env}"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
PG_CONTAINER="${PG_CONTAINER:-dally-postgres}"
ODOO_CONTAINER="${ODOO_CONTAINER:-dally-odoo}"

command -v docker >/dev/null || fail "docker est requis."

for c in "${PG_CONTAINER}" "${ODOO_CONTAINER}"; do
  docker inspect -f '{{.State.Running}}' "${c}" 2>/dev/null | grep -q true \
    || fail "le conteneur ${c} n'est pas démarré."
done

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR}/${TAG}/${TIMESTAMP}"
mkdir -p "${DEST}"

# Nettoyage si le script échoue en cours de route : une sauvegarde
# partielle est plus dangereuse qu'une sauvegarde absente, car elle
# inspire une confiance injustifiée.
cleanup_on_error() {
  if [[ -d "${DEST}" && ! -f "${DEST}/.complete" ]]; then
    log "échec détecté — suppression de la sauvegarde incomplète ${DEST}"
    rm -rf "${DEST}"
  fi
}
trap cleanup_on_error EXIT

log "destination : ${DEST}"

# ─── 1. Base de données ───────────────────────────────────────────
# Format custom (-Fc) : compressé et restaurable sélectivement.
# --no-owner / --no-privileges : la restauration ne dépend pas de
# l'existence du même rôle sur la cible (utile en environnement de test).
log "dump PostgreSQL de la base « ${ODOO_DB_NAME} »…"
if ! docker exec "${PG_CONTAINER}" pg_dump \
      -U "${POSTGRES_USER}" \
      -d "${ODOO_DB_NAME}" \
      -Fc --no-owner --no-privileges \
      > "${DEST}/database.dump"; then
  fail "pg_dump a échoué."
fi

DB_SIZE="$(stat -c %s "${DEST}/database.dump")"
(( DB_SIZE > 4096 )) || fail "dump suspect : ${DB_SIZE} octets seulement."
log "dump terminé ($(numfmt --to=iec "${DB_SIZE}"))"

# ─── 2. Filestore ─────────────────────────────────────────────────
log "archivage du filestore Odoo…"
if ! docker exec "${ODOO_CONTAINER}" \
      tar -czf - -C /var/lib/odoo . \
      > "${DEST}/filestore.tar.gz" 2>/dev/null; then
  fail "l'archivage du filestore a échoué."
fi

FS_SIZE="$(stat -c %s "${DEST}/filestore.tar.gz")"
log "filestore archivé ($(numfmt --to=iec "${FS_SIZE}"))"

# ─── 3. Empreintes et manifeste ───────────────────────────────────
log "calcul des empreintes SHA-256…"
( cd "${DEST}" && sha256sum database.dump filestore.tar.gz > SHA256SUMS )

ODOO_VERSION="$(docker exec "${ODOO_CONTAINER}" odoo --version 2>/dev/null | head -1 || echo inconnue)"
PG_VERSION="$(docker exec "${PG_CONTAINER}" postgres --version 2>/dev/null | head -1 || echo inconnue)"

cat > "${DEST}/manifest.json" <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "tag": "${TAG}",
  "database": {
    "name": "${ODOO_DB_NAME}",
    "dump_file": "database.dump",
    "dump_format": "pg_dump-custom",
    "size_bytes": ${DB_SIZE}
  },
  "filestore": {
    "archive": "filestore.tar.gz",
    "size_bytes": ${FS_SIZE}
  },
  "versions": {
    "odoo": "${ODOO_VERSION}",
    "postgresql": "${PG_VERSION}"
  },
  "host": "$(hostname)",
  "created_by": "backup.sh"
}
EOF

touch "${DEST}/.complete"
log "sauvegarde complète et cohérente."

# ─── 4. Copie distante chiffrée ───────────────────────────────────
# Une sauvegarde uniquement locale ne protège pas de la perte du
# serveur. Le chiffrement est appliqué AVANT l'envoi : le prestataire
# de stockage ne doit jamais voir les données en clair.
if [[ -n "${S3_BUCKET:-}" && -n "${S3_ENDPOINT:-}" ]]; then
  if ! command -v aws >/dev/null; then
    log "AVERTISSEMENT : S3 configuré mais le client aws est absent — envoi ignoré."
  elif [[ -z "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
    log "AVERTISSEMENT : BACKUP_ENCRYPTION_KEY vide — envoi ignoré (jamais d'envoi en clair)."
  else
    log "chiffrement et envoi vers S3…"
    ARCHIVE="${BACKUP_DIR}/${TAG}-${TIMESTAMP}.tar.gz.enc"
    tar -czf - -C "${BACKUP_DIR}/${TAG}" "${TIMESTAMP}" \
      | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
          -pass env:BACKUP_ENCRYPTION_KEY \
      > "${ARCHIVE}"
    if AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY}" \
       AWS_SECRET_ACCESS_KEY="${S3_SECRET_KEY}" \
       aws --endpoint-url "${S3_ENDPOINT}" s3 cp \
           "${ARCHIVE}" "s3://${S3_BUCKET}/odoo/${TAG}/" >/dev/null; then
      log "envoyé : s3://${S3_BUCKET}/odoo/${TAG}/$(basename "${ARCHIVE}")"
      rm -f "${ARCHIVE}"
    else
      log "AVERTISSEMENT : l'envoi S3 a échoué — copie locale conservée : ${ARCHIVE}"
    fi
  fi
else
  log "AVERTISSEMENT : aucun stockage distant configuré. La sauvegarde n'existe QUE sur ce serveur."
fi

# ─── 5. Rétention ─────────────────────────────────────────────────
case "${TAG}" in
  daily)   KEEP="${BACKUP_RETENTION_DAILY:-7}" ;;
  weekly)  KEEP="${BACKUP_RETENTION_WEEKLY:-4}" ;;
  monthly) KEEP="${BACKUP_RETENTION_MONTHLY:-6}" ;;
  *)       KEEP=7 ;;
esac

log "rétention « ${TAG} » : conservation des ${KEEP} dernières."

# Les répertoires sont horodatés en UTC (format triable), donc l'ordre
# lexicographique décroissant est l'ordre chronologique décroissant.
mapfile -t ALL < <(find "${BACKUP_DIR}/${TAG}" -mindepth 1 -maxdepth 1 -type d | sort -r)

if (( ${#ALL[@]} > KEEP )); then
  for old in "${ALL[@]:KEEP}"; do
    # Garde-fou : ne jamais supprimer la DERNIÈRE sauvegarde complète
    # restante, même si la rétention l'exige. Mieux vaut dépasser le
    # quota que se retrouver sans aucune sauvegarde restaurable.
    remaining_complete=0
    for candidate in "${ALL[@]}"; do
      [[ "${candidate}" == "${old}" ]] && continue
      [[ -d "${candidate}" ]] || continue          # déjà supprimée dans cette boucle
      [[ -f "${candidate}/.complete" ]] && (( remaining_complete++ ))
    done

    if [[ -f "${old}/.complete" ]] && (( remaining_complete == 0 )); then
      log "CONSERVÉE : $(basename "${old}") est la dernière sauvegarde complète."
      continue
    fi

    log "suppression de l'ancienne sauvegarde $(basename "${old}")"
    rm -rf "${old}"
  done
fi

trap - EXIT
echo
log "TERMINÉ : ${DEST}"
log "Rappel (§62) : une sauvegarde non restaurée n'est pas une sauvegarde."
log "Vérifiez-la : ./infrastructure/scripts/verify-backup.sh ${DEST}"
