#!/usr/bin/env bash
#
# DALLYTRADING — Vérification d'une sauvegarde
#
# Vérifie l'intégrité SANS TOUCHER à la production. Deux niveaux :
#
#   rapide (défaut) : présence des fichiers, empreintes SHA-256,
#                     manifeste, lisibilité de l'en-tête du dump,
#                     intégrité de l'archive du filestore.
#
#   --deep          : restaure réellement le dump dans une base
#                     JETABLE, compte les tables et les enregistrements
#                     clés, puis supprime la base. Seul niveau qui
#                     prouve qu'une sauvegarde est restaurable (§62).
#
# Usage :
#   ./verify-backup.sh                            # vérifie la plus récente
#   ./verify-backup.sh <chemin_sauvegarde>
#   ./verify-backup.sh <chemin_sauvegarde> --deep
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

BACKUP_PATH=""
DEEP=0
while (( $# > 0 )); do
  case "$1" in
    --deep) DEEP=1; shift ;;
    *)      BACKUP_PATH="$1"; shift ;;
  esac
done

log()  { printf '[verify] %s\n' "$*"; }
ok()   { printf '[verify]   ✓ %s\n' "$*"; }
bad()  { printf '[verify]   ✗ %s\n' "$*" >&2; FAILURES=$((FAILURES+1)); }
fail() { printf '[verify] ERREUR : %s\n' "$*" >&2; exit 1; }

FAILURES=0

[[ -f "${ENV_FILE}" ]] || fail ".env introuvable."
set -a; source "${ENV_FILE}"; set +a
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
PG_CONTAINER="${PG_CONTAINER:-dally-postgres}"

# Sauvegarde la plus récente, toutes étiquettes confondues.
if [[ -z "${BACKUP_PATH}" ]]; then
  BACKUP_PATH="$(find "${BACKUP_DIR}" -mindepth 2 -maxdepth 2 -type d 2>/dev/null | sort -r | head -1)"
  [[ -n "${BACKUP_PATH}" ]] || fail "aucune sauvegarde trouvée dans ${BACKUP_DIR}"
  log "sauvegarde la plus récente : ${BACKUP_PATH}"
fi

[[ -d "${BACKUP_PATH}" ]] || fail "introuvable : ${BACKUP_PATH}"
log "vérification de ${BACKUP_PATH}"
echo

# ─── 1. Complétude ────────────────────────────────────────────────
log "1/5 — complétude"
if [[ -f "${BACKUP_PATH}/.complete" ]]; then
  ok "marqueur de complétude présent"
else
  bad "marqueur .complete ABSENT — sauvegarde interrompue, ne pas s'y fier"
fi

for f in database.dump filestore.tar.gz manifest.json SHA256SUMS; do
  if [[ -s "${BACKUP_PATH}/${f}" ]]; then
    ok "${f} présent ($(numfmt --to=iec "$(stat -c %s "${BACKUP_PATH}/${f}")"))"
  else
    bad "${f} absent ou vide"
  fi
done

# ─── 2. Empreintes ────────────────────────────────────────────────
echo; log "2/5 — empreintes SHA-256"
if [[ -f "${BACKUP_PATH}/SHA256SUMS" ]]; then
  if ( cd "${BACKUP_PATH}" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ); then
    ok "toutes les empreintes concordent"
  else
    bad "EMPREINTE INVALIDE — corruption des données"
    ( cd "${BACKUP_PATH}" && sha256sum -c SHA256SUMS 2>&1 | grep -v ': OK$' >&2 || true )
  fi
else
  bad "SHA256SUMS absent : intégrité invérifiable"
fi

# ─── 3. Manifeste ─────────────────────────────────────────────────
echo; log "3/5 — manifeste"
if [[ -f "${BACKUP_PATH}/manifest.json" ]]; then
  if command -v python3 >/dev/null; then
    if python3 -c "import json,sys; json.load(open('${BACKUP_PATH}/manifest.json'))" 2>/dev/null; then
      ok "JSON valide"
      python3 - "${BACKUP_PATH}/manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
print(f"[verify]     base       : {m['database']['name']}")
print(f"[verify]     horodatage : {m['timestamp']}")
print(f"[verify]     Odoo       : {m['versions']['odoo']}")
print(f"[verify]     PostgreSQL : {m['versions']['postgresql']}")
PY
    else
      bad "manifeste JSON illisible"
    fi
  fi
else
  bad "manifest.json absent"
fi

# ─── 4. Lisibilité des artefacts ──────────────────────────────────
echo; log "4/5 — lisibilité"
if docker inspect -f '{{.State.Running}}' "${PG_CONTAINER}" 2>/dev/null | grep -q true; then
  # pg_restore --list lit l'en-tête sans rien écrire : non destructif.
  if TABLES="$(docker exec -i "${PG_CONTAINER}" pg_restore --list < "${BACKUP_PATH}/database.dump" 2>/dev/null | grep -c 'TABLE DATA' || true)"; then
    if [[ "${TABLES:-0}" -gt 0 ]]; then
      ok "dump lisible — ${TABLES} tables contenant des données"
    else
      bad "dump lisible mais AUCUNE table de données : sauvegarde vide"
    fi
  else
    bad "pg_restore ne parvient pas à lire le dump"
  fi
else
  log "   (conteneur ${PG_CONTAINER} arrêté — contrôle du dump ignoré)"
fi

if gzip -t "${BACKUP_PATH}/filestore.tar.gz" 2>/dev/null; then
  COUNT="$(tar -tzf "${BACKUP_PATH}/filestore.tar.gz" 2>/dev/null | wc -l)"
  ok "archive filestore intègre — ${COUNT} entrées"
else
  bad "archive filestore CORROMPUE"
fi

# ─── 5. Restauration réelle (--deep) ──────────────────────────────
echo; log "5/5 — restauration réelle"
if (( DEEP == 0 )); then
  log "   ignorée (utilisez --deep). Sans ce contrôle, la restaurabilité n'est PAS prouvée."
else
  docker inspect -f '{{.State.Running}}' "${PG_CONTAINER}" 2>/dev/null | grep -q true \
    || fail "--deep exige que ${PG_CONTAINER} soit démarré."

  TEST_DB="verify_$(date -u +%Y%m%d%H%M%S)_$$"
  log "   base de test jetable : ${TEST_DB}"

  # La base de production n'est jamais touchée : on écrit exclusivement
  # dans TEST_DB, systématiquement supprimée en sortie.
  cleanup_test_db() {
    log "   suppression de la base de test ${TEST_DB}"
    docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres \
      -c "DROP DATABASE IF EXISTS \"${TEST_DB}\";" >/dev/null 2>&1 || true
  }
  trap cleanup_test_db EXIT

  if ! docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres \
        -c "CREATE DATABASE \"${TEST_DB}\";" >/dev/null 2>&1; then
    bad "impossible de créer la base de test (le rôle a-t-il CREATEDB ?)"
  else
    ok "base de test créée"

    # pg_restore signale des avertissements bénins (extensions, rôles) :
    # on juge sur le résultat, pas sur le code de sortie.
    docker exec -i "${PG_CONTAINER}" pg_restore \
        -U "${POSTGRES_USER}" -d "${TEST_DB}" \
        --no-owner --no-privileges --exit-on-error \
        < "${BACKUP_PATH}/database.dump" >/dev/null 2>&1 \
      && ok "dump restauré sans erreur" \
      || bad "la restauration a échoué (--exit-on-error)"

    query() {
      docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${TEST_DB}" \
        -tAc "$1" 2>/dev/null | tr -d '[:space:]'
    }

    NB_TABLES="$(query "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")"
    if [[ "${NB_TABLES:-0}" -gt 50 ]]; then
      ok "${NB_TABLES} tables restaurées"
    else
      bad "seulement ${NB_TABLES:-0} tables : une base Odoo en compte plusieurs centaines"
    fi

    # Contrôles métier : une base Odoo restaurée doit contenir ces données.
    for check in "res_users:utilisateurs" "res_partner:contacts" "ir_module_module:modules"; do
      table="${check%%:*}"; label="${check##*:}"
      n="$(query "SELECT count(*) FROM ${table};")"
      if [[ -n "${n}" && "${n}" -gt 0 ]]; then
        ok "${label} : ${n} enregistrement(s)"
      else
        bad "${label} : table ${table} vide ou absente"
      fi
    done
  fi

  cleanup_test_db
  trap - EXIT
fi

# ─── Verdict ──────────────────────────────────────────────────────
echo
if (( FAILURES == 0 )); then
  if (( DEEP == 1 )); then
    log "RÉSULTAT : sauvegarde VALIDE et restaurabilité PROUVÉE."
  else
    log "RÉSULTAT : contrôles rapides OK. Restaurabilité non prouvée — relancez avec --deep."
  fi
  exit 0
else
  log "RÉSULTAT : ${FAILURES} ÉCHEC(S). Cette sauvegarde n'est pas fiable."
  exit 1
fi
