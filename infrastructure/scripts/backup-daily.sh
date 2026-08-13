#!/usr/bin/env bash
# Lance une sauvegarde quotidienne DallyTrading et vérifie exactement l'artefact créé.
set -euo pipefail
umask 0077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="${SCRIPT_DIR}/backup.sh"
VERIFY_SCRIPT="${SCRIPT_DIR}/verify-backup.sh"

log()  { printf '[backup-daily][%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERREUR : $*" >&2; exit 1; }

case "${1:-}" in
  "") ;;
  --check)
    [[ -x "${BACKUP_SCRIPT}" ]] || fail "backup.sh absent ou non exécutable."
    [[ -x "${VERIFY_SCRIPT}" ]] || fail "verify-backup.sh absent ou non exécutable."
    "${BACKUP_SCRIPT}" --check
    log "VALIDATION OK : lanceur, sources et vérificateur disponibles."
    exit 0
    ;;
  *) fail "option inconnue : $1" ;;
esac

for command_name in mktemp tee sed tail; do
  command -v "${command_name}" >/dev/null || fail "${command_name} est requis."
done
[[ -x "${BACKUP_SCRIPT}" ]] || fail "backup.sh absent ou non exécutable."
[[ -x "${VERIFY_SCRIPT}" ]] || fail "verify-backup.sh absent ou non exécutable."

CAPTURE="$(mktemp "${TMPDIR:-/tmp}/dallytrading-backup.XXXXXX")"
cleanup() { rm -f -- "${CAPTURE}"; }
trap cleanup EXIT

log "début de la sauvegarde quotidienne."
set +e
"${BACKUP_SCRIPT}" --tag daily 2>&1 | tee "${CAPTURE}"
backup_status="${PIPESTATUS[0]}"
set -e
(( backup_status == 0 )) || fail "backup.sh a échoué avec le statut ${backup_status}."

BACKUP_PATH="$(sed -n 's/^\[backup\].*TERMINÉ : //p' "${CAPTURE}" | tail -n 1)"
[[ -n "${BACKUP_PATH}" ]] || fail "backup.sh n'a pas annoncé le chemin produit."
[[ "${BACKUP_PATH}" == /*/daily/20??????T??????Z ]] ||
  fail "chemin de sauvegarde quotidien inattendu : ${BACKUP_PATH}"
[[ -d "${BACKUP_PATH}" && -f "${BACKUP_PATH}/.complete" ]] ||
  fail "sauvegarde absente ou incomplète : ${BACKUP_PATH}"

log "vérification de ${BACKUP_PATH}."
"${VERIFY_SCRIPT}" "${BACKUP_PATH}"
log "SUCCÈS : sauvegarde quotidienne créée et vérifiée : ${BACKUP_PATH}"
