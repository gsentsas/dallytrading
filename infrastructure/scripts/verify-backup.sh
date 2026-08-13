#!/usr/bin/env bash
#
# DALLYTRADING — Vérification non destructive d'une sauvegarde.
#
# Le mode rapide vérifie fichiers, manifeste, horodatages, empreintes,
# archive et catalogue pg_restore. Le mode --deep ne restaure rien :
# il contrôle une restauration déjà effectuée dans l'environnement
# dédié créé par docker-compose.restore.yml.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

BACKUP_PATH=""
DEEP=0
TARGET_PG_CONTAINER=""
TARGET_ODOO_CONTAINER=""
TARGET_PG_VOLUME=""
TARGET_FILESTORE_VOLUME=""
TARGET_NETWORK=""
TARGET_DB=""
TARGET_DB_USER=""

while (( $# > 0 )); do
  case "$1" in
    --deep) DEEP=1; shift ;;
    --pg-container) TARGET_PG_CONTAINER="${2:?valeur requise}"; shift 2 ;;
    --odoo-container) TARGET_ODOO_CONTAINER="${2:?valeur requise}"; shift 2 ;;
    --pg-volume) TARGET_PG_VOLUME="${2:?valeur requise}"; shift 2 ;;
    --filestore-volume) TARGET_FILESTORE_VOLUME="${2:?valeur requise}"; shift 2 ;;
    --network) TARGET_NETWORK="${2:?valeur requise}"; shift 2 ;;
    --target-db) TARGET_DB="${2:?valeur requise}"; shift 2 ;;
    --db-user) TARGET_DB_USER="${2:?valeur requise}"; shift 2 ;;
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

log()  { printf '[verify] %s\n' "$*"; }
ok()   { printf '[verify]   ✓ %s\n' "$*"; }
bad()  { printf '[verify]   ✗ %s\n' "$*" >&2; FAILURES=$((FAILURES + 1)); }
fail() { printf '[verify] ERREUR : %s\n' "$*" >&2; exit 1; }

valid_identifier() {
  [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]
}

container_mount() {
  docker inspect "$1" --format "{{range .Mounts}}{{if eq .Destination \"$2\"}}{{.Name}}{{end}}{{end}}" 2>/dev/null
}

container_networks() {
  docker inspect "$1" --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' 2>/dev/null
}

FAILURES=0
[[ -f "${ENV_FILE}" ]] || fail ".env introuvable."
# shellcheck disable=SC1090
set -a; source "${ENV_FILE}"; set +a

BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
PROD_PROJECT="${COMPOSE_PROJECT_NAME:-dallytrading}"
PROD_PG_CONTAINER="${PG_CONTAINER:-dallytrading-postgres}"
PROD_ODOO_CONTAINER="${ODOO_CONTAINER:-dallytrading-odoo}"
PROD_PG_VOLUME="${POSTGRES_VOLUME:-dallytrading_postgres_data}"
PROD_FILESTORE_VOLUME="${ODOO_FILESTORE_VOLUME:-dallytrading_odoo_filestore}"
PROD_PRIVATE_NETWORK="${PRIVATE_NETWORK:-dallytrading_private}"
PROD_PUBLIC_NETWORK="${PUBLIC_NETWORK:-dallytrading_public}"

if [[ -z "${BACKUP_PATH}" ]]; then
  BACKUP_PATH="$(find "${BACKUP_DIR}" -mindepth 2 -maxdepth 2 -type d 2>/dev/null |
    sort -r | head -1)"
  [[ -n "${BACKUP_PATH}" ]] || fail "aucune sauvegarde trouvée dans ${BACKUP_DIR}."
fi

[[ -d "${BACKUP_PATH}" ]] || fail "introuvable : ${BACKUP_PATH}"
[[ ! -L "${BACKUP_PATH}" ]] || fail "un chemin symbolique est refusé."
log "vérification de ${BACKUP_PATH}"

log "1/5 — complétude"
for file in .complete database.dump filestore.tar.gz manifest.json SHA256SUMS; do
  if [[ -f "${BACKUP_PATH}/${file}" && ( "${file}" == ".complete" || -s "${BACKUP_PATH}/${file}" ) ]]; then
    ok "${file} présent"
  else
    bad "${file} absent ou vide"
  fi
done

log "2/5 — manifeste et cohérence logique"
if python3 - "${BACKUP_PATH}" <<'PY'
import json
import os
import re
import sys

path = sys.argv[1]
with open(os.path.join(path, "manifest.json"), encoding="utf-8") as handle:
    manifest = json.load(handle)
timestamp = manifest.get("timestamp")
assert isinstance(timestamp, str) and re.fullmatch(r"\d{8}T\d{6}Z", timestamp)
assert os.path.basename(os.path.realpath(path)) == timestamp
assert manifest.get("schema_version") == 2
database = manifest["database"]
filestore = manifest["filestore"]
assert database["dump_file"] == "database.dump"
assert database["dump_format"] == "pg_dump-custom"
assert filestore["archive"] == "filestore.tar.gz"
assert filestore["layout"] == "database-directory-contents-v1"
assert database["name"] == filestore["database"]
assert database["captured_at"] == timestamp
assert filestore["captured_at"] == timestamp
assert database["size_bytes"] == os.path.getsize(os.path.join(path, "database.dump"))
assert filestore["size_bytes"] == os.path.getsize(os.path.join(path, "filestore.tar.gz"))
expected = {"database.dump", "filestore.tar.gz", "manifest.json"}
seen = set()
with open(os.path.join(path, "SHA256SUMS"), encoding="utf-8") as handle:
    for line in handle:
        parts = line.rstrip("\n").split(maxsplit=1)
        assert len(parts) == 2
        name = parts[1].lstrip("*")
        assert name in expected and "/" not in name
        seen.add(name)
assert seen == expected
print(f"[verify]     base={database['name']} timestamp={timestamp}")
PY
then
  ok "manifeste v2 valide ; PostgreSQL et filestore partagent le même timestamp"
else
  bad "manifeste invalide ou incohérent"
fi

log "3/5 — empreintes SHA-256"
if (
  cd "${BACKUP_PATH}"
  sha256sum -c SHA256SUMS >/dev/null 2>&1
); then
  ok "toutes les empreintes concordent"
else
  bad "empreinte invalide"
fi

log "4/5 — lisibilité des artefacts"
if (( DEEP )); then
  READ_CONTAINER="${TARGET_PG_CONTAINER:-${RESTORE_PG_CONTAINER:-dallytrading-restore-postgres}}"
  [[ "${READ_CONTAINER}" != "${PROD_PG_CONTAINER}" ]] ||
    fail "--deep refuse le conteneur PostgreSQL de production."
  READ_IDENTITY_OK="$(docker inspect -f '{{index .Config.Labels "com.dallytrading.restore"}}' "${READ_CONTAINER}" 2>/dev/null)"
  EXPECTED_IDENTITY="true"
else
  READ_CONTAINER="${PROD_PG_CONTAINER}"
  READ_IDENTITY_OK="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "${READ_CONTAINER}" 2>/dev/null)"
  EXPECTED_IDENTITY="${PROD_PROJECT}"
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "${READ_CONTAINER}" 2>/dev/null)" == "true" ]]; then
  if [[ "${READ_IDENTITY_OK}" != "${EXPECTED_IDENTITY}" ]]; then
    bad "identité Docker inattendue pour ${READ_CONTAINER}"
  elif TABLES="$(docker exec -i "${READ_CONTAINER}" pg_restore --list < "${BACKUP_PATH}/database.dump" 2>/dev/null | grep -c 'TABLE DATA' || true)" &&
      [[ "${TABLES:-0}" -gt 0 ]]; then
    ok "dump lisible — ${TABLES} entrées TABLE DATA"
  else
    bad "catalogue pg_restore illisible ou vide"
  fi
else
  bad "conteneur de lecture ${READ_CONTAINER} arrêté"
fi

if gzip -t "${BACKUP_PATH}/filestore.tar.gz" 2>/dev/null; then
  UNSAFE=0
  COUNT=0
  while IFS= read -r member; do
    COUNT=$((COUNT + 1))
    case "${member}" in
      /*|../*|*/../*|*/..) UNSAFE=1 ;;
    esac
  done < <(tar -tzf "${BACKUP_PATH}/filestore.tar.gz")
  if (( UNSAFE )); then
    bad "archive filestore contenant un chemin dangereux"
  else
    ok "archive filestore intègre et sûre — ${COUNT} entrée(s)"
  fi
else
  bad "archive filestore corrompue"
fi

log "5/5 — validation profonde de la cible isolée"
if (( DEEP == 0 )); then
  log "   non demandée ; utilisez --deep après restore.sh --isolated-test."
else
  TARGET_PG_CONTAINER="${TARGET_PG_CONTAINER:-${RESTORE_PG_CONTAINER:-dallytrading-restore-postgres}}"
  TARGET_ODOO_CONTAINER="${TARGET_ODOO_CONTAINER:-${RESTORE_ODOO_CONTAINER:-dallytrading-restore-odoo}}"
  TARGET_PG_VOLUME="${TARGET_PG_VOLUME:-${RESTORE_POSTGRES_VOLUME:-dallytrading_restore_postgres_data}}"
  TARGET_FILESTORE_VOLUME="${TARGET_FILESTORE_VOLUME:-${RESTORE_FILESTORE_VOLUME:-dallytrading_restore_odoo_filestore}}"
  TARGET_NETWORK="${TARGET_NETWORK:-${RESTORE_NETWORK:-dallytrading_restore_private}}"
  TARGET_DB="${TARGET_DB:-${RESTORE_DB_NAME:-dallytrading_restore}}"
  TARGET_DB_USER="${TARGET_DB_USER:-${RESTORE_DB_USER:-postgres}}"

  valid_identifier "${TARGET_DB}" || fail "base cible invalide."
  valid_identifier "${TARGET_DB_USER}" || fail "utilisateur cible invalide."
  [[ "${TARGET_DB}" != "${ODOO_DB_NAME}" ]] || fail "la cible profonde ne peut pas être la base production."
  [[ "${TARGET_PG_CONTAINER}" != "${PROD_PG_CONTAINER}" &&
     "${TARGET_ODOO_CONTAINER}" != "${PROD_ODOO_CONTAINER}" &&
     "${TARGET_PG_VOLUME}" != "${PROD_PG_VOLUME}" &&
     "${TARGET_FILESTORE_VOLUME}" != "${PROD_FILESTORE_VOLUME}" &&
     "${TARGET_NETWORK}" != "${PROD_PRIVATE_NETWORK}" &&
     "${TARGET_NETWORK}" != "${PROD_PUBLIC_NETWORK}" ]] ||
    fail "une ressource profonde recoupe la production."

  for container in "${TARGET_PG_CONTAINER}" "${TARGET_ODOO_CONTAINER}"; do
    [[ "$(docker inspect -f '{{.State.Running}}' "${container}" 2>/dev/null)" == "true" ]] ||
      fail "conteneur isolé absent : ${container}"
    [[ "$(docker inspect -f '{{index .Config.Labels "com.dallytrading.restore"}}' "${container}" 2>/dev/null)" == "true" ]] ||
      fail "label restore absent sur ${container}"
    PORTS="$(docker inspect -f '{{json .HostConfig.PortBindings}}' "${container}")"
    [[ "${PORTS}" == "{}" || "${PORTS}" == "null" ]] ||
      fail "port publié sur ${container}"
    for network in $(container_networks "${container}"); do
      [[ "${network}" == "${TARGET_NETWORK}" ]] ||
        fail "réseau inattendu ${network} sur ${container}"
    done
  done

  [[ "$(container_mount "${TARGET_PG_CONTAINER}" /var/lib/postgresql/data)" == "${TARGET_PG_VOLUME}" ]] ||
    fail "volume PostgreSQL isolé inattendu."
  [[ "$(container_mount "${TARGET_ODOO_CONTAINER}" /var/lib/odoo)" == "${TARGET_FILESTORE_VOLUME}" ]] ||
    fail "volume filestore isolé inattendu."
  [[ "$(docker network inspect -f '{{.Internal}}' "${TARGET_NETWORK}" 2>/dev/null)" == "true" ]] ||
    fail "réseau isolé non interne."

  query() {
    docker exec "${TARGET_PG_CONTAINER}" psql -U "${TARGET_DB_USER}" -d "${TARGET_DB}"       -tAc "$1" 2>/dev/null | tr -d '[:space:]'
  }

  NB_TABLES="$(query "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")"
  MODULES="$(query "SELECT count(*) FROM ir_module_module WHERE name LIKE 'dally_%' AND state='installed';")"
  USERS="$(query "SELECT count(*) FROM res_users;")"
  PARTNERS="$(query "SELECT count(*) FROM res_partner;")"
  BUSINESS_TABLES="$(query "SELECT count(*) FROM pg_class WHERE relkind='r' AND relname LIKE 'dally_%';")"

  [[ "${NB_TABLES:-0}" -gt 50 ]] && ok "${NB_TABLES} tables restaurées" ||
    bad "nombre de tables insuffisant : ${NB_TABLES:-0}"
  [[ "${MODULES:-0}" -gt 0 ]] && ok "${MODULES} module(s) dally_* installé(s)" ||
    bad "aucun module dally_* installé"
  [[ "${USERS:-0}" -gt 0 && "${PARTNERS:-0}" -gt 0 ]] &&
    ok "objets essentiels : ${USERS} utilisateur(s), ${PARTNERS} partenaire(s)" ||
    bad "objets Odoo essentiels absents"
  [[ "${BUSINESS_TABLES:-0}" -gt 0 ]] && ok "${BUSINESS_TABLES} table(s) métier dally_*" ||
    bad "tables métier dally_* absentes"

  if docker exec "${TARGET_ODOO_CONTAINER}" test -r "/var/lib/odoo/filestore/${TARGET_DB}"; then
    FS_ENTRIES="$(docker exec "${TARGET_ODOO_CONTAINER}" sh -c       "find '/var/lib/odoo/filestore/${TARGET_DB}' -mindepth 1 -print | wc -l" |
      tr -d '[:space:]')"
    ok "filestore lisible — ${FS_ENTRIES:-0} entrée(s)"
  else
    bad "filestore cible illisible"
  fi
  ok "isolation : aucun conteneur, volume, réseau ou port de production utilisé"
fi

if (( FAILURES == 0 )); then
  if (( DEEP )); then
    log "RÉSULTAT : sauvegarde et restauration isolée VALIDÉES."
  else
    log "RÉSULTAT : contrôles rapides OK."
  fi
  exit 0
fi
log "RÉSULTAT : ${FAILURES} ÉCHEC(S)."
exit 1
