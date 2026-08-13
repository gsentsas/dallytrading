#!/usr/bin/env bash
#
# DALLYTRADING — Restauration explicite et cloisonnée.
#
# Aucun mode n'est implicite. Il faut choisir exactement l'un de :
#   --isolated-test  cible exclusivement les ressources restore dédiées
#   --production     cible exclusivement les ressources DallyTrading de production
#
# Le filestore n'est jamais modifié par défaut. Son remplacement exige
# --replace-filestore ET la répétition exacte du nom du volume.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
START_EPOCH="${SECONDS}"

BACKUP_PATH=""
MODE=""
TARGET_DB=""
TARGET_PG_CONTAINER=""
TARGET_ODOO_CONTAINER=""
TARGET_PG_VOLUME=""
TARGET_FILESTORE_VOLUME=""
TARGET_NETWORK=""
TARGET_DB_USER=""
TARGET_DB_OWNER=""
REPLACE_FILESTORE=0
ACK_DB_ONLY=0
ASSUME_YES=0
CONFIRM_FILESTORE_VOLUME=""
CONFIRM_PRODUCTION_DB=""

while (( $# > 0 )); do
  case "$1" in
    --isolated-test) MODE="isolated"; shift ;;
    --production) MODE="production"; shift ;;
    --target-db) TARGET_DB="${2:?--target-db requiert une valeur}"; shift 2 ;;
    --target-pg-container) TARGET_PG_CONTAINER="${2:?valeur requise}"; shift 2 ;;
    --target-odoo-container) TARGET_ODOO_CONTAINER="${2:?valeur requise}"; shift 2 ;;
    --target-pg-volume) TARGET_PG_VOLUME="${2:?valeur requise}"; shift 2 ;;
    --target-filestore-volume) TARGET_FILESTORE_VOLUME="${2:?valeur requise}"; shift 2 ;;
    --target-network) TARGET_NETWORK="${2:?valeur requise}"; shift 2 ;;
    --target-db-user) TARGET_DB_USER="${2:?valeur requise}"; shift 2 ;;
    --target-db-owner) TARGET_DB_OWNER="${2:?valeur requise}"; shift 2 ;;
    --replace-filestore) REPLACE_FILESTORE=1; shift ;;
    --skip-filestore) REPLACE_FILESTORE=0; shift ;;
    --acknowledge-db-only) ACK_DB_ONLY=1; shift ;;
    --confirm-filestore-volume)
      CONFIRM_FILESTORE_VOLUME="${2:?valeur requise}"; shift 2 ;;
    --confirm-production-db)
      CONFIRM_PRODUCTION_DB="${2:?valeur requise}"; shift 2 ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -*) printf 'Option inconnue : %s\n' "$1" >&2; exit 2 ;;
    *)
      [[ -z "${BACKUP_PATH}" ]] || {
        printf 'Un seul chemin de sauvegarde est accepté.\n' >&2
        exit 2
      }
      BACKUP_PATH="$1"
      shift
      ;;
  esac
done

log()  { printf '[restore] %s\n' "$*"; }
fail() { printf '[restore] ERREUR : %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage :
  restore.sh <backup> --isolated-test --replace-filestore \
    --confirm-filestore-volume dallytrading_restore_odoo_filestore [--yes]

  restore.sh <backup> --production --confirm-production-db dallytrading \
    --replace-filestore --confirm-filestore-volume dallytrading_odoo_filestore
EOF
}

valid_identifier() {
  [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]
}

valid_resource_name() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]
}

container_mount() {
  docker inspect "$1" --format "{{range .Mounts}}{{if eq .Destination \"$2\"}}{{.Name}}{{end}}{{end}}" 2>/dev/null
}

container_networks() {
  docker inspect "$1" --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' 2>/dev/null
}

container_has_no_ports() {
  local bindings
  bindings="$(docker inspect "$1" --format '{{json .HostConfig.PortBindings}}' 2>/dev/null)"
  [[ "${bindings}" == "{}" || "${bindings}" == "null" ]]
}

[[ -n "${BACKUP_PATH}" ]] || { usage >&2; fail "chemin de sauvegarde requis."; }
[[ "${MODE}" == "isolated" || "${MODE}" == "production" ]] ||
  { usage >&2; fail "choisissez explicitement --isolated-test ou --production."; }
[[ -d "${BACKUP_PATH}" ]] || fail "sauvegarde introuvable : ${BACKUP_PATH}"
[[ ! -L "${BACKUP_PATH}" ]] || fail "un chemin de sauvegarde symbolique est refusé."
[[ -f "${ENV_FILE}" ]] || fail ".env introuvable."

# shellcheck disable=SC1090
set -a; source "${ENV_FILE}"; set +a

: "${POSTGRES_USER:?POSTGRES_USER absent de .env}"
: "${POSTGRES_DB:?POSTGRES_DB absent de .env}"
: "${ODOO_DB_NAME:?ODOO_DB_NAME absent de .env}"

PROD_PROJECT="${COMPOSE_PROJECT_NAME:-dallytrading}"
PROD_PG_CONTAINER="${PG_CONTAINER:-dallytrading-postgres}"
PROD_ODOO_CONTAINER="${ODOO_CONTAINER:-dallytrading-odoo}"
PROD_PG_VOLUME="${POSTGRES_VOLUME:-dallytrading_postgres_data}"
PROD_FILESTORE_VOLUME="${ODOO_FILESTORE_VOLUME:-dallytrading_odoo_filestore}"
PROD_PRIVATE_NETWORK="${PRIVATE_NETWORK:-dallytrading_private}"
PROD_PUBLIC_NETWORK="${PUBLIC_NETWORK:-dallytrading_public}"

if [[ "${MODE}" == "isolated" ]]; then
  TARGET_DB="${TARGET_DB:-${RESTORE_DB_NAME:-dallytrading_restore}}"
  TARGET_PG_CONTAINER="${TARGET_PG_CONTAINER:-${RESTORE_PG_CONTAINER:-dallytrading-restore-postgres}}"
  TARGET_ODOO_CONTAINER="${TARGET_ODOO_CONTAINER:-${RESTORE_ODOO_CONTAINER:-dallytrading-restore-odoo}}"
  TARGET_PG_VOLUME="${TARGET_PG_VOLUME:-${RESTORE_POSTGRES_VOLUME:-dallytrading_restore_postgres_data}}"
  TARGET_FILESTORE_VOLUME="${TARGET_FILESTORE_VOLUME:-${RESTORE_FILESTORE_VOLUME:-dallytrading_restore_odoo_filestore}}"
  TARGET_NETWORK="${TARGET_NETWORK:-${RESTORE_NETWORK:-dallytrading_restore_private}}"
  TARGET_DB_USER="${TARGET_DB_USER:-${RESTORE_DB_USER:-postgres}}"
  TARGET_DB_OWNER="${TARGET_DB_OWNER:-${RESTORE_DB_USER:-postgres}}"
else
  TARGET_DB="${TARGET_DB:-${ODOO_DB_NAME}}"
  TARGET_PG_CONTAINER="${TARGET_PG_CONTAINER:-${PROD_PG_CONTAINER}}"
  TARGET_ODOO_CONTAINER="${TARGET_ODOO_CONTAINER:-${PROD_ODOO_CONTAINER}}"
  TARGET_PG_VOLUME="${TARGET_PG_VOLUME:-${PROD_PG_VOLUME}}"
  TARGET_FILESTORE_VOLUME="${TARGET_FILESTORE_VOLUME:-${PROD_FILESTORE_VOLUME}}"
  TARGET_NETWORK="${TARGET_NETWORK:-${PROD_PRIVATE_NETWORK}}"
  TARGET_DB_USER="${TARGET_DB_USER:-postgres}"
  TARGET_DB_OWNER="${TARGET_DB_OWNER:-${POSTGRES_USER}}"
fi

for identifier in "${TARGET_DB}" "${TARGET_DB_USER}" "${TARGET_DB_OWNER}"; do
  valid_identifier "${identifier}" || fail "identifiant PostgreSQL invalide : ${identifier}"
done
for resource in "${TARGET_PG_CONTAINER}" "${TARGET_ODOO_CONTAINER}"                 "${TARGET_PG_VOLUME}" "${TARGET_FILESTORE_VOLUME}"                 "${TARGET_NETWORK}"; do
  valid_resource_name "${resource}" || fail "nom de ressource invalide : ${resource}"
done

case "${TARGET_PG_CONTAINER}:${TARGET_ODOO_CONTAINER}:${TARGET_PG_VOLUME}:${TARGET_FILESTORE_VOLUME}:${TARGET_NETWORK}" in
  *odoo_crm*|*sen_containers*) fail "toute ressource SEN est interdite." ;;
esac

command -v docker >/dev/null || fail "docker est requis."
command -v python3 >/dev/null || fail "python3 est requis."

log "1/8 — validation de la sauvegarde"
for file in .complete database.dump filestore.tar.gz manifest.json SHA256SUMS; do
  [[ -f "${BACKUP_PATH}/${file}" ]] || fail "${file} absent."
done
for file in database.dump filestore.tar.gz manifest.json SHA256SUMS; do
  [[ -s "${BACKUP_PATH}/${file}" ]] || fail "${file} est vide."
done

python3 - "${BACKUP_PATH}" <<'PY'
import json
import os
import re
import sys

path = sys.argv[1]
with open(os.path.join(path, "manifest.json"), encoding="utf-8") as handle:
    manifest = json.load(handle)

timestamp = manifest.get("timestamp")
if not isinstance(timestamp, str) or not re.fullmatch(r"\d{8}T\d{6}Z", timestamp):
    raise SystemExit("timestamp de manifeste invalide")
if os.path.basename(os.path.realpath(path)) != timestamp:
    raise SystemExit("le timestamp du répertoire ne correspond pas au manifeste")
if manifest.get("schema_version") != 2:
    raise SystemExit("schema_version=2 requis")
database = manifest.get("database", {})
filestore = manifest.get("filestore", {})
if database.get("dump_file") != "database.dump":
    raise SystemExit("dump_file inattendu")
if filestore.get("archive") != "filestore.tar.gz":
    raise SystemExit("archive filestore inattendue")
if filestore.get("layout") != "database-directory-contents-v1":
    raise SystemExit("format de filestore non cloisonnable")
if database.get("name") != filestore.get("database"):
    raise SystemExit("base et filestore concernent des bases différentes")
if database.get("captured_at") != timestamp or filestore.get("captured_at") != timestamp:
    raise SystemExit("timestamps PostgreSQL/filestore incohérents")
if database.get("size_bytes") != os.path.getsize(os.path.join(path, "database.dump")):
    raise SystemExit("taille du dump incohérente")
if filestore.get("size_bytes") != os.path.getsize(os.path.join(path, "filestore.tar.gz")):
    raise SystemExit("taille du filestore incohérente")

expected = {"database.dump", "filestore.tar.gz", "manifest.json"}
seen = set()
with open(os.path.join(path, "SHA256SUMS"), encoding="utf-8") as handle:
    for raw in handle:
        parts = raw.rstrip("\n").split(maxsplit=1)
        if len(parts) != 2:
            raise SystemExit("ligne SHA256SUMS invalide")
        name = parts[1].lstrip("*")
        if name not in expected or "/" in name:
            raise SystemExit("cible SHA256SUMS inattendue")
        seen.add(name)
if seen != expected:
    raise SystemExit("SHA256SUMS incomplet")
PY

(
  cd "${BACKUP_PATH}"
  sha256sum -c SHA256SUMS >/dev/null
) || fail "empreintes invalides."
gzip -t "${BACKUP_PATH}/filestore.tar.gz" || fail "archive filestore corrompue."
while IFS= read -r member; do
  case "${member}" in
    /*|../*|*/../*|*/..) fail "chemin dangereux dans le filestore : ${member}" ;;
  esac
done < <(tar -tzf "${BACKUP_PATH}/filestore.tar.gz")
SOURCE_DB="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["database"]["name"])'   "${BACKUP_PATH}/manifest.json")"
[[ -n "${SOURCE_DB}" ]] || fail "base source absente du manifeste."
log "   backup intègre ; base source=${SOURCE_DB} ; timestamps cohérents."

log "2/8 — validation de la cible"
for container in "${TARGET_PG_CONTAINER}" "${TARGET_ODOO_CONTAINER}"; do
  [[ "$(docker inspect -f '{{.State.Running}}' "${container}" 2>/dev/null)" == "true" ]] ||
    fail "conteneur cible absent ou arrêté : ${container}"
done
[[ "$(container_mount "${TARGET_PG_CONTAINER}" /var/lib/postgresql/data)" == "${TARGET_PG_VOLUME}" ]] ||
  fail "le montage PostgreSQL cible n'est pas ${TARGET_PG_VOLUME}."
[[ "$(container_mount "${TARGET_ODOO_CONTAINER}" /var/lib/odoo)" == "${TARGET_FILESTORE_VOLUME}" ]] ||
  fail "le montage filestore cible n'est pas ${TARGET_FILESTORE_VOLUME}."

PG_NETWORKS="$(container_networks "${TARGET_PG_CONTAINER}")"
ODOO_NETWORKS="$(container_networks "${TARGET_ODOO_CONTAINER}")"
[[ " ${PG_NETWORKS} " == *" ${TARGET_NETWORK} "* ]] ||
  fail "PostgreSQL n'est pas relié au réseau cible."
[[ " ${ODOO_NETWORKS} " == *" ${TARGET_NETWORK} "* ]] ||
  fail "le conteneur filestore n'est pas relié au réseau cible."

if [[ "${MODE}" == "isolated" ]]; then
  [[ "${TARGET_DB}" != "${ODOO_DB_NAME}" ]] ||
    fail "le mode test refuse le nom de base de production."
  [[ "${TARGET_PG_CONTAINER}" != "${PROD_PG_CONTAINER}" &&
     "${TARGET_ODOO_CONTAINER}" != "${PROD_ODOO_CONTAINER}" ]] ||
    fail "le mode test refuse les conteneurs de production."
  [[ "${TARGET_PG_VOLUME}" != "${PROD_PG_VOLUME}" &&
     "${TARGET_FILESTORE_VOLUME}" != "${PROD_FILESTORE_VOLUME}" ]] ||
    fail "le mode test refuse les volumes de production."
  [[ "${TARGET_NETWORK}" != "${PROD_PRIVATE_NETWORK}" &&
     "${TARGET_NETWORK}" != "${PROD_PUBLIC_NETWORK}" ]] ||
    fail "le mode test refuse les réseaux de production."

  for network in ${PG_NETWORKS} ${ODOO_NETWORKS}; do
    [[ "${network}" == "${TARGET_NETWORK}" ]] ||
      fail "réseau inattendu sur une cible isolée : ${network}"
  done

  for container in "${TARGET_PG_CONTAINER}" "${TARGET_ODOO_CONTAINER}"; do
    [[ "$(docker inspect -f '{{index .Config.Labels "com.dallytrading.restore"}}' "${container}" 2>/dev/null)" == "true" ]] ||
      fail "${container} ne porte pas le label de restauration."
    container_has_no_ports "${container}" ||
      fail "${container} publie un port : isolation refusée."
  done
  [[ "$(docker volume inspect -f '{{index .Labels "com.dallytrading.restore"}}' "${TARGET_PG_VOLUME}" 2>/dev/null)" == "true" ]] ||
    fail "volume PostgreSQL sans label de restauration."
  [[ "$(docker volume inspect -f '{{index .Labels "com.dallytrading.restore"}}' "${TARGET_FILESTORE_VOLUME}" 2>/dev/null)" == "true" ]] ||
    fail "volume filestore sans label de restauration."
  [[ "$(docker network inspect -f '{{.Internal}}' "${TARGET_NETWORK}" 2>/dev/null)" == "true" ]] ||
    fail "le réseau de restauration n'est pas interne."
  [[ "$(docker network inspect -f '{{index .Labels "com.dallytrading.restore"}}' "${TARGET_NETWORK}" 2>/dev/null)" == "true" ]] ||
    fail "réseau sans label de restauration."
else
  for network in ${PG_NETWORKS}; do
    [[ "${network}" == "${PROD_PRIVATE_NETWORK}" ]] ||
      fail "réseau PostgreSQL production inattendu : ${network}"
  done
  for network in ${ODOO_NETWORKS}; do
    [[ "${network}" == "${PROD_PRIVATE_NETWORK}" || "${network}" == "${PROD_PUBLIC_NETWORK}" ]] ||
      fail "réseau Odoo production inattendu : ${network}"
  done
  [[ "${TARGET_DB}" == "${ODOO_DB_NAME}" &&
     "${TARGET_PG_CONTAINER}" == "${PROD_PG_CONTAINER}" &&
     "${TARGET_ODOO_CONTAINER}" == "${PROD_ODOO_CONTAINER}" &&
     "${TARGET_PG_VOLUME}" == "${PROD_PG_VOLUME}" &&
     "${TARGET_FILESTORE_VOLUME}" == "${PROD_FILESTORE_VOLUME}" &&
     "${TARGET_NETWORK}" == "${PROD_PRIVATE_NETWORK}" ]] ||
    fail "le mode production exige exactement les ressources DallyTrading déclarées."
  [[ "${SOURCE_DB}" == "${ODOO_DB_NAME}" ]] ||
    fail "le backup ne provient pas de la base de production attendue."
  [[ "${CONFIRM_PRODUCTION_DB}" == "${TARGET_DB}" ]] ||
    fail "--confirm-production-db doit répéter exactement ${TARGET_DB}."
  if (( REPLACE_FILESTORE == 0 && ACK_DB_ONLY == 0 )); then
    fail "restauration DB seule refusée sans --acknowledge-db-only."
  fi
fi

if (( REPLACE_FILESTORE )); then
  [[ "${CONFIRM_FILESTORE_VOLUME}" == "${TARGET_FILESTORE_VOLUME}" ]] ||
    fail "--confirm-filestore-volume doit répéter exactement ${TARGET_FILESTORE_VOLUME}."
fi

docker exec -i "${TARGET_PG_CONTAINER}" pg_restore --list   < "${BACKUP_PATH}/database.dump" >/dev/null ||
  fail "le conteneur cible ne peut pas lire le dump."

cat <<EOF

  Mode             : ${MODE}
  Base source      : ${SOURCE_DB}
  Base cible       : ${TARGET_DB}
  PostgreSQL cible : ${TARGET_PG_CONTAINER} / ${TARGET_PG_VOLUME}
  Filestore cible  : ${TARGET_ODOO_CONTAINER} / ${TARGET_FILESTORE_VOLUME}
  Réseau cible     : ${TARGET_NETWORK}
  Filestore        : $( (( REPLACE_FILESTORE )) && printf 'REMPLACEMENT EXPLICITE' || printf 'NON MODIFIÉ' )

EOF

if (( ASSUME_YES == 0 )); then
  if [[ "${MODE}" == "production" ]]; then
    log "Saisissez RESTORE-PRODUCTION-${TARGET_DB} pour confirmer :"
    read -r CONFIRM
    [[ "${CONFIRM}" == "RESTORE-PRODUCTION-${TARGET_DB}" ]] ||
      fail "confirmation de production incorrecte."
  else
    log "Saisissez RESTORE-ISOLATED-${TARGET_DB} pour confirmer :"
    read -r CONFIRM
    [[ "${CONFIRM}" == "RESTORE-ISOLATED-${TARGET_DB}" ]] ||
      fail "confirmation de test incorrecte."
  fi
fi

log "3/8 — sauvegarde de sécurité"
if [[ "${MODE}" == "production" ]]; then
  "${SCRIPT_DIR}/backup.sh" --tag pre-restore ||
    fail "la sauvegarde de sécurité a échoué ; restauration refusée."
  log "   sauvegarde complète production créée avant toute destruction."
else
  log "   cible éphémère isolée : aucune donnée de production à sauvegarder."
fi

log "4/8 — arrêt du seul conteneur Odoo cible"
ODOO_WAS_RUNNING=0
if [[ "$(docker inspect -f '{{.State.Running}}' "${TARGET_ODOO_CONTAINER}")" == "true" ]]; then
  ODOO_WAS_RUNNING=1
  docker stop "${TARGET_ODOO_CONTAINER}" >/dev/null
fi

restart_target() {
  if (( ODOO_WAS_RUNNING )); then
    docker start "${TARGET_ODOO_CONTAINER}" >/dev/null 2>&1 ||
      log "AVERTISSEMENT : redémarrage de ${TARGET_ODOO_CONTAINER} impossible."
  fi
}
trap restart_target EXIT

log "5/8 — recréation de la base cible"
docker exec "${TARGET_PG_CONTAINER}" psql -U "${TARGET_DB_USER}" -d postgres -v ON_ERROR_STOP=1   -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${TARGET_DB}' AND pid <> pg_backend_pid();"   >/dev/null
docker exec "${TARGET_PG_CONTAINER}" psql -U "${TARGET_DB_USER}" -d postgres -v ON_ERROR_STOP=1   -c "DROP DATABASE IF EXISTS \"${TARGET_DB}\";" >/dev/null
docker exec "${TARGET_PG_CONTAINER}" psql -U "${TARGET_DB_USER}" -d postgres -v ON_ERROR_STOP=1   -c "CREATE DATABASE \"${TARGET_DB}\" WITH OWNER \"${TARGET_DB_OWNER}\" TEMPLATE template0 ENCODING 'UTF8';"   >/dev/null

log "6/8 — restauration PostgreSQL"
docker exec -i "${TARGET_PG_CONTAINER}" pg_restore   -U "${TARGET_DB_USER}" -d "${TARGET_DB}"   --no-owner --no-privileges --exit-on-error   < "${BACKUP_PATH}/database.dump" >/dev/null ||
  fail "pg_restore a échoué."

NB_TABLES="$(docker exec "${TARGET_PG_CONTAINER}" psql -U "${TARGET_DB_USER}" -d "${TARGET_DB}"   -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" |
  tr -d '[:space:]')"
[[ "${NB_TABLES:-0}" -gt 50 ]] ||
  fail "restauration suspecte : ${NB_TABLES:-0} tables."
log "   ${NB_TABLES} tables restaurées."

log "7/8 — filestore"
if (( REPLACE_FILESTORE )); then
  FILE_UID="${ODOO_RUN_UID:-101}"
  FILE_GID="${ODOO_RUN_GID:-101}"
  [[ "${FILE_UID}" =~ ^[0-9]+$ && "${FILE_GID}" =~ ^[0-9]+$ ]] ||
    fail "UID/GID filestore invalides."
  WORKER="dallytrading-restore-filestore-$$"
  docker run --rm -i --name "${WORKER}" --network none     --label com.dallytrading.restore=true     -e TARGET_DB="${TARGET_DB}" -e FILE_UID="${FILE_UID}" -e FILE_GID="${FILE_GID}"     -v "${TARGET_FILESTORE_VOLUME}:/restore"     --entrypoint sh "${POSTGRES_IMAGE:-postgres:16-alpine}" -c     'set -eu
     target="/restore/filestore/$TARGET_DB"
     rm -rf -- "$target"
     mkdir -p -- "$target"
     tar -xzf - -C "$target"
     chown -R "$FILE_UID:$FILE_GID" "$target"'     < "${BACKUP_PATH}/filestore.tar.gz" ||
    fail "restauration du filestore échouée."
  log "   filestore remplacé dans le seul répertoire filestore/${TARGET_DB}."
else
  log "   non modifié (comportement sûr par défaut)."
fi

log "8/8 — contrôles"
MODULES="$(docker exec "${TARGET_PG_CONTAINER}" psql -U "${TARGET_DB_USER}" -d "${TARGET_DB}" -tAc   "SELECT count(*) FROM ir_module_module WHERE name LIKE 'dally_%' AND state='installed';" |
  tr -d '[:space:]')"
[[ "${MODULES:-0}" -gt 0 ]] || fail "aucun module dally_* installé dans la base restaurée."
if (( REPLACE_FILESTORE )); then
  docker start "${TARGET_ODOO_CONTAINER}" >/dev/null
  ODOO_WAS_RUNNING=0
  docker exec "${TARGET_ODOO_CONTAINER}" test -r "/var/lib/odoo/filestore/${TARGET_DB}" ||
    fail "filestore restauré illisible depuis le conteneur cible."
else
  restart_target
  ODOO_WAS_RUNNING=0
fi

if [[ "${MODE}" == "production" ]]; then
  HEALTHY=0
  for _ in $(seq 1 36); do
    sleep 5
    if curl -sf -m 5 "http://127.0.0.1:${ODOO_HTTP_PORT:-18169}/web/health" >/dev/null 2>&1; then
      HEALTHY=1
      break
    fi
  done
  (( HEALTHY )) || fail "Odoo ne répond pas après restauration."
fi

trap - EXIT
DURATION="$(( SECONDS - START_EPOCH ))"
log "SUCCÈS : base=${TARGET_DB}, tables=${NB_TABLES}, modules_dally=${MODULES}, durée=${DURATION}s"
