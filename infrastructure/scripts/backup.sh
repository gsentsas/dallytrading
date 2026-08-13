#!/usr/bin/env bash
#
# DALLYTRADING — Sauvegarde cohérente d'une base Odoo et de son filestore.
#
# Produit dans ${BACKUP_DIR}/<tag>/<timestamp>/ :
#   database.dump      pg_dump au format custom
#   filestore.tar.gz   contenu du filestore de la seule base Odoo ciblée
#   manifest.json      identité des ressources, tailles et horodatage logique
#   SHA256SUMS         empreintes des trois artefacts
#   .complete          écrit uniquement quand l'ensemble est terminé
#
set -euo pipefail
umask 0077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

TAG="daily"
CHECK_ONLY=0
while (( $# > 0 )); do
  case "$1" in
    --tag) TAG="${2:?--tag requiert une valeur}"; shift 2 ;;
    --check) CHECK_ONLY=1; shift ;;
    *) printf 'Option inconnue : %s\n' "$1" >&2; exit 2 ;;
  esac
done

log()  { printf '[backup][%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
fail() { printf '[backup] ERREUR : %s\n' "$*" >&2; exit 1; }

valid_identifier() {
  [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]
}

valid_resource_name() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]
}

container_mount() {
  docker inspect "$1" --format "{{range .Mounts}}{{if eq .Destination \"$2\"}}{{.Name}}{{end}}{{end}}" 2>/dev/null
}

container_has_network() {
  docker inspect "$1" --format '{{json .NetworkSettings.Networks}}' 2>/dev/null |
    grep -Fq "\"$2\""
}

[[ -f "${ENV_FILE}" ]] || fail ".env introuvable."
# shellcheck disable=SC1090
set -a; source "${ENV_FILE}"; set +a

: "${POSTGRES_USER:?POSTGRES_USER absent de .env}"
: "${POSTGRES_DB:?POSTGRES_DB absent de .env}"
: "${ODOO_DB_NAME:?ODOO_DB_NAME absent de .env}"

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-dallytrading}"
PG_CONTAINER="${PG_CONTAINER:-dallytrading-postgres}"
ODOO_CONTAINER="${ODOO_CONTAINER:-dallytrading-odoo}"
POSTGRES_VOLUME="${POSTGRES_VOLUME:-dallytrading_postgres_data}"
ODOO_FILESTORE_VOLUME="${ODOO_FILESTORE_VOLUME:-dallytrading_odoo_filestore}"
PRIVATE_NETWORK="${PRIVATE_NETWORK:-dallytrading_private}"
PUBLIC_NETWORK="${PUBLIC_NETWORK:-dallytrading_public}"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"

command -v docker >/dev/null || fail "docker est requis."
command -v python3 >/dev/null || fail "python3 est requis pour le manifeste."
command -v flock >/dev/null || fail "flock est requis pour empêcher deux sauvegardes concurrentes."

[[ "${TAG}" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] || fail "tag invalide : ${TAG}"
valid_identifier "${POSTGRES_USER}" || fail "POSTGRES_USER invalide."
valid_identifier "${POSTGRES_DB}" || fail "POSTGRES_DB invalide."
valid_identifier "${ODOO_DB_NAME}" || fail "ODOO_DB_NAME invalide."
[[ "${POSTGRES_DB}" == "${ODOO_DB_NAME}" ]] ||
  fail "POSTGRES_DB (${POSTGRES_DB}) et ODOO_DB_NAME (${ODOO_DB_NAME}) divergent."

for resource in "${COMPOSE_PROJECT_NAME}" "${PG_CONTAINER}" "${ODOO_CONTAINER}"                 "${POSTGRES_VOLUME}" "${ODOO_FILESTORE_VOLUME}"                 "${PRIVATE_NETWORK}" "${PUBLIC_NETWORK}"; do
  valid_resource_name "${resource}" || fail "nom de ressource invalide : ${resource}"
done

case "${PG_CONTAINER}:${ODOO_CONTAINER}" in
  *odoo_crm*|*sen_containers*) fail "ressource SEN interdite." ;;
esac

[[ "${BACKUP_DIR}" == /* && "${BACKUP_DIR}" != "/" && "${BACKUP_DIR}" != "${ROOT_DIR}" ]] ||
  fail "BACKUP_DIR doit être un chemin absolu dédié, distinct de / et de la racine du projet."

for container in "${PG_CONTAINER}" "${ODOO_CONTAINER}"; do
  [[ "$(docker inspect -f '{{.State.Running}}' "${container}" 2>/dev/null)" == "true" ]] ||
    fail "le conteneur ${container} n'est pas démarré."
  actual_project="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "${container}" 2>/dev/null)"
  [[ "${actual_project}" == "${COMPOSE_PROJECT_NAME}" ]] ||
    fail "${container} appartient au projet « ${actual_project} », pas à « ${COMPOSE_PROJECT_NAME} »."
done

[[ "$(container_mount "${PG_CONTAINER}" /var/lib/postgresql/data)" == "${POSTGRES_VOLUME}" ]] ||
  fail "le volume PostgreSQL monté ne correspond pas à ${POSTGRES_VOLUME}."
[[ "$(container_mount "${ODOO_CONTAINER}" /var/lib/odoo)" == "${ODOO_FILESTORE_VOLUME}" ]] ||
  fail "le volume filestore monté ne correspond pas à ${ODOO_FILESTORE_VOLUME}."
container_has_network "${PG_CONTAINER}" "${PRIVATE_NETWORK}" ||
  fail "${PG_CONTAINER} n'est pas relié à ${PRIVATE_NETWORK}."
container_has_network "${ODOO_CONTAINER}" "${PRIVATE_NETWORK}" ||
  fail "${ODOO_CONTAINER} n'est pas relié à ${PRIVATE_NETWORK}."
container_has_network "${ODOO_CONTAINER}" "${PUBLIC_NETWORK}" ||
  fail "${ODOO_CONTAINER} n'est pas relié à ${PUBLIC_NETWORK}."

DB_EXISTS="$(docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres -tAc   "SELECT 1 FROM pg_database WHERE datname='${ODOO_DB_NAME}';" 2>/dev/null | tr -d '[:space:]')"
[[ "${DB_EXISTS}" == "1" ]] || fail "la base ${ODOO_DB_NAME} n'existe pas dans ${PG_CONTAINER}."

FILESTORE_SOURCE="/var/lib/odoo/filestore/${ODOO_DB_NAME}"
docker exec "${ODOO_CONTAINER}" test -d "${FILESTORE_SOURCE}" ||
  fail "filestore source absent : ${FILESTORE_SOURCE}"

if (( CHECK_ONLY )); then
  log "VALIDATION OK : conteneurs, base, volumes, réseaux et filestore correspondent."
  exit 0
fi

mkdir -p "${BACKUP_DIR}"
# Mode imposé explicitement, pas seulement par l'umask.
#
# `umask 0077` en tête de ce script ne protège que ce que CE script crée. Une
# sauvegarde lancée depuis un shell dont l'umask est 022 produisait des
# répertoires 755 et des fichiers 644 — constaté sur backups/production-release :
# le database.dump complet était lisible par les ~20 comptes d'hébergement de
# cette machine partagée (données clients, notes internes, marges, coûts).
#
# Un chmod explicite ne dépend d'aucun état hérité de l'appelant.
chmod 700 "${BACKUP_DIR}"
exec 9>"${BACKUP_DIR}/.backup.lock"
chmod 600 "${BACKUP_DIR}/.backup.lock"
flock -n 9 || fail "une autre sauvegarde DallyTrading est déjà en cours."

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR}/${TAG}/${TIMESTAMP}"
[[ ! -e "${DEST}" ]] || fail "destination déjà existante : ${DEST}"
mkdir -p "${DEST}"
chmod 700 "${BACKUP_DIR}/${TAG}" "${DEST}"

cleanup_on_error() {
  if [[ -d "${DEST}" && ! -f "${DEST}/.complete" ]]; then
    log "échec détecté — suppression de la sauvegarde incomplète ${DEST}"
    rm -rf -- "${DEST}"
  fi
}
trap cleanup_on_error EXIT

log "source PostgreSQL : ${PG_CONTAINER}/${ODOO_DB_NAME} (${POSTGRES_VOLUME})"
log "source filestore  : ${ODOO_CONTAINER}:${FILESTORE_SOURCE} (${ODOO_FILESTORE_VOLUME})"
log "destination       : ${DEST}"
log "horodatage logique : ${TIMESTAMP}"

log "dump PostgreSQL…"
docker exec "${PG_CONTAINER}" pg_dump   -U "${POSTGRES_USER}" -d "${ODOO_DB_NAME}"   -Fc --no-owner --no-privileges > "${DEST}/database.dump" ||
  fail "pg_dump a échoué."

DB_SIZE="$(stat -c %s "${DEST}/database.dump")"
(( DB_SIZE > 4096 )) || fail "dump suspect : ${DB_SIZE} octets seulement."
log "dump terminé ($(numfmt --to=iec "${DB_SIZE}"))"

log "archivage du filestore dédié à ${ODOO_DB_NAME}…"
docker exec "${ODOO_CONTAINER}"   tar -czf - -C "${FILESTORE_SOURCE}" . > "${DEST}/filestore.tar.gz" ||
  fail "l'archivage du filestore a échoué."

FS_SIZE="$(stat -c %s "${DEST}/filestore.tar.gz")"
(( FS_SIZE > 20 )) || fail "archive filestore suspecte : ${FS_SIZE} octets."
log "filestore archivé ($(numfmt --to=iec "${FS_SIZE}"))"

ODOO_VERSION="$(docker exec "${ODOO_CONTAINER}" odoo --version 2>/dev/null | head -1 || printf inconnue)"
PG_VERSION="$(docker exec "${PG_CONTAINER}" postgres --version 2>/dev/null | head -1 || printf inconnue)"

python3 - "${DEST}/manifest.json" "${TIMESTAMP}" "${TAG}" "${ODOO_DB_NAME}"   "${DB_SIZE}" "${FS_SIZE}" "${ODOO_VERSION}" "${PG_VERSION}"   "${PG_CONTAINER}" "${ODOO_CONTAINER}" "${POSTGRES_VOLUME}"   "${ODOO_FILESTORE_VOLUME}" "${PRIVATE_NETWORK}" <<'PY'
import json
import socket
import sys

(
    path, timestamp, tag, database, db_size, fs_size, odoo_version,
    pg_version, pg_container, odoo_container, pg_volume, fs_volume,
    network,
) = sys.argv[1:]

manifest = {
    "schema_version": 2,
    "timestamp": timestamp,
    "tag": tag,
    "database": {
        "name": database,
        "dump_file": "database.dump",
        "dump_format": "pg_dump-custom",
        "size_bytes": int(db_size),
        "captured_at": timestamp,
    },
    "filestore": {
        "archive": "filestore.tar.gz",
        "layout": "database-directory-contents-v1",
        "database": database,
        "size_bytes": int(fs_size),
        "captured_at": timestamp,
    },
    "resources": {
        "postgres_container": pg_container,
        "odoo_container": odoo_container,
        "postgres_volume": pg_volume,
        "filestore_volume": fs_volume,
        "private_network": network,
    },
    "versions": {"odoo": odoo_version, "postgresql": pg_version},
    "host": socket.gethostname(),
    "created_by": "backup.sh",
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY

log "calcul des empreintes SHA-256…"
(
  cd "${DEST}"
  sha256sum database.dump filestore.tar.gz manifest.json > SHA256SUMS
)
touch "${DEST}/.complete"
# Dernier filet : quel que soit l'umask hérité, rien de cette sauvegarde ne doit
# être lisible par un autre compte du serveur.
chmod 700 "${DEST}"
find "${DEST}" -mindepth 1 -type d -exec chmod 700 {} +
find "${DEST}" -mindepth 1 -type f -exec chmod 600 {} +
log "sauvegarde complète."

if [[ -n "${S3_BUCKET:-}" || -n "${S3_ENDPOINT:-}" ]]; then
  if [[ -z "${S3_BUCKET:-}" || -z "${S3_ENDPOINT:-}" ||
        -z "${S3_ACCESS_KEY:-}" || -z "${S3_SECRET_KEY:-}" ]]; then
    log "AVERTISSEMENT : configuration S3 incomplète — envoi refusé."
  elif ! command -v aws >/dev/null; then
    log "AVERTISSEMENT : S3 configuré mais le client aws est absent — envoi ignoré."
  elif [[ -z "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
    log "AVERTISSEMENT : clé de chiffrement absente — envoi refusé."
  else
    log "chiffrement et envoi vers S3…"
    ARCHIVE="${BACKUP_DIR}/${TAG}-${TIMESTAMP}.tar.gz.enc"
    tar -czf - -C "${BACKUP_DIR}/${TAG}" "${TIMESTAMP}" |
      openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt         -pass env:BACKUP_ENCRYPTION_KEY > "${ARCHIVE}"
    if AWS_ACCESS_KEY_ID="${S3_ACCESS_KEY}" AWS_SECRET_ACCESS_KEY="${S3_SECRET_KEY}"       aws --endpoint-url "${S3_ENDPOINT}" s3 cp         "${ARCHIVE}" "s3://${S3_BUCKET}/odoo/${TAG}/" >/dev/null; then
      log "copie distante envoyée."
      rm -f -- "${ARCHIVE}"
    else
      log "AVERTISSEMENT : envoi S3 échoué — archive chiffrée locale conservée."
    fi
  fi
else
  log "AVERTISSEMENT : aucun stockage hors serveur configuré."
fi

case "${TAG}" in
  daily)   KEEP="${BACKUP_RETENTION_DAILY:-7}" ;;
  weekly)  KEEP="${BACKUP_RETENTION_WEEKLY:-4}" ;;
  monthly) KEEP="${BACKUP_RETENTION_MONTHLY:-6}" ;;
  *)       KEEP=7 ;;
esac
[[ "${KEEP}" =~ ^[1-9][0-9]*$ ]] || fail "rétention invalide : ${KEEP}"

log "rétention « ${TAG} » : ${KEEP} sauvegarde(s)."
mapfile -t ALL < <(find "${BACKUP_DIR}/${TAG}" -mindepth 1 -maxdepth 1 -type d | sort -r)
if (( ${#ALL[@]} > KEEP )); then
  for old in "${ALL[@]:KEEP}"; do
    [[ "${old}" == "${BACKUP_DIR}/${TAG}/"* ]] ||
      fail "refus de supprimer un chemin hors du répertoire de rétention."
    remaining_complete=0
    for candidate in "${ALL[@]}"; do
      [[ "${candidate}" == "${old}" ]] && continue
      [[ -d "${candidate}" && -f "${candidate}/.complete" ]] && (( remaining_complete += 1 ))
    done
    if [[ -f "${old}/.complete" && "${remaining_complete}" -eq 0 ]]; then
      log "conservée : $(basename "${old}") est la dernière sauvegarde complète."
      continue
    fi
    log "suppression de l'ancienne sauvegarde $(basename "${old}")"
    rm -rf -- "${old}"
  done
fi

trap - EXIT
log "TERMINÉ : ${DEST}"
log "Vérifiez-la : ./infrastructure/scripts/verify-backup.sh ${DEST}"
