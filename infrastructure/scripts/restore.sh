#!/usr/bin/env bash
#
# DALLYTRADING — Restauration Odoo (base + filestore)
#
# ⚠️  OPÉRATION DESTRUCTIVE : écrase la base ET le filestore de la cible.
#
# Trois garde-fous, conformément au §87 (ne pas détruire les données) :
#   1. La sauvegarde est vérifiée AVANT toute écriture.
#   2. Une sauvegarde de sécurité de l'état actuel est prise d'office.
#   3. Confirmation explicite exigée : saisie du nom de la base.
#
# Odoo est arrêté pendant l'opération : restaurer sous une instance
# active corrompt le cache et laisse des verrous incohérents.
#
# Usage :
#   ./restore.sh <chemin_sauvegarde>
#   ./restore.sh <chemin_sauvegarde> --target-db essai_restauration
#   ./restore.sh <chemin_sauvegarde> --yes          # non interactif (CI)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

BACKUP_PATH=""
TARGET_DB=""
ASSUME_YES=0
SKIP_FILESTORE=0

while (( $# > 0 )); do
  case "$1" in
    --target-db)      TARGET_DB="${2:?--target-db requiert une valeur}"; shift 2 ;;
    --yes|-y)         ASSUME_YES=1; shift ;;
    --skip-filestore) SKIP_FILESTORE=1; shift ;;
    -*)               printf 'Option inconnue : %s\n' "$1" >&2; exit 2 ;;
    *)                BACKUP_PATH="$1"; shift ;;
  esac
done

log()  { printf '[restore] %s\n' "$*"; }
fail() { printf '[restore] ERREUR : %s\n' "$*" >&2; exit 1; }

[[ -n "${BACKUP_PATH}" ]] || fail "usage : $0 <chemin_sauvegarde> [--target-db NOM] [--yes]"
[[ -d "${BACKUP_PATH}" ]] || fail "introuvable : ${BACKUP_PATH}"
[[ -f "${ENV_FILE}" ]]    || fail ".env introuvable."

set -a; source "${ENV_FILE}"; set +a
: "${POSTGRES_USER:?absent de .env}"
: "${ODOO_DB_NAME:?absent de .env}"
PG_CONTAINER="${PG_CONTAINER:-dally-postgres}"
ODOO_CONTAINER="${ODOO_CONTAINER:-dally-odoo}"
TARGET_DB="${TARGET_DB:-${ODOO_DB_NAME}}"
COMPOSE_DIR="${ROOT_DIR}/infrastructure"

IS_PRODUCTION=0
[[ "${TARGET_DB}" == "${ODOO_DB_NAME}" ]] && IS_PRODUCTION=1

# ─── 1. Vérifier la sauvegarde AVANT d'écrire quoi que ce soit ─────
log "1/7 — vérification de la sauvegarde source"
if [[ ! -f "${BACKUP_PATH}/.complete" ]]; then
  fail "sauvegarde INCOMPLÈTE (.complete absent). Restauration refusée."
fi
if ! ( cd "${BACKUP_PATH}" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ); then
  fail "EMPREINTES INVALIDES : la sauvegarde est corrompue. Restauration refusée."
fi
log "   sauvegarde intègre."

# ─── 2. Confirmation ──────────────────────────────────────────────
echo
log "2/7 — confirmation"
cat <<EOF

  ┌──────────────────────────────────────────────────────────────┐
  │  RESTAURATION                                                │
  ├──────────────────────────────────────────────────────────────┤
  │  Source      : ${BACKUP_PATH}
  │  Base cible  : ${TARGET_DB}
  │  Filestore   : $( (( SKIP_FILESTORE )) && echo "IGNORÉ" || echo "REMPLACÉ" )
  │  Production  : $( (( IS_PRODUCTION )) && echo "OUI — DONNÉES ACTUELLES DÉTRUITES" || echo "non (base de test)" )
  └──────────────────────────────────────────────────────────────┘

EOF

if (( ASSUME_YES == 0 )); then
  if (( IS_PRODUCTION )); then
    log "Pour confirmer, saisissez exactement le nom de la base : ${TARGET_DB}"
    read -r -p "> " CONFIRM
    [[ "${CONFIRM}" == "${TARGET_DB}" ]] || fail "confirmation incorrecte. Abandon."
  else
    read -r -p "Continuer ? [o/N] " CONFIRM
    [[ "${CONFIRM}" =~ ^[oOyY]$ ]] || fail "abandon."
  fi
else
  log "   --yes : confirmation ignorée (mode non interactif)."
fi

# ─── 3. Sauvegarde de sécurité de l'état actuel ────────────────────
echo; log "3/7 — sauvegarde de sécurité de l'état actuel"
EXISTS="$(docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='${TARGET_DB}';" 2>/dev/null | tr -d '[:space:]')"

if [[ "${EXISTS}" == "1" ]]; then
  SAFETY="${ROOT_DIR}/backups/pre-restore/$(date -u +%Y%m%dT%H%M%SZ)-${TARGET_DB}"
  mkdir -p "${SAFETY}"
  log "   dump de sécurité vers ${SAFETY}"
  if docker exec "${PG_CONTAINER}" pg_dump -U "${POSTGRES_USER}" -d "${TARGET_DB}" \
       -Fc --no-owner --no-privileges > "${SAFETY}/database.dump" 2>/dev/null; then
    log "   dump de sécurité : $(numfmt --to=iec "$(stat -c %s "${SAFETY}/database.dump")")"
  else
    rm -rf "${SAFETY}"
    if (( IS_PRODUCTION )); then
      fail "impossible de sauvegarder l'état actuel. Restauration en production refusée."
    fi
    log "   AVERTISSEMENT : dump de sécurité impossible (base cible non production)."
  fi

  if (( SKIP_FILESTORE == 0 )) && docker inspect -f '{{.State.Running}}' "${ODOO_CONTAINER}" 2>/dev/null | grep -q true; then
    docker exec "${ODOO_CONTAINER}" tar -czf - -C /var/lib/odoo . \
      > "${SAFETY}/filestore.tar.gz" 2>/dev/null \
      && log "   filestore de sécurité archivé" \
      || log "   AVERTISSEMENT : archivage du filestore de sécurité impossible"
  fi
else
  log "   la base ${TARGET_DB} n'existe pas encore : rien à sauvegarder."
fi

# ─── 4. Arrêter Odoo ──────────────────────────────────────────────
echo; log "4/7 — arrêt d'Odoo"
ODOO_WAS_RUNNING=0
if docker inspect -f '{{.State.Running}}' "${ODOO_CONTAINER}" 2>/dev/null | grep -q true; then
  ODOO_WAS_RUNNING=1
  docker stop "${ODOO_CONTAINER}" >/dev/null
  log "   ${ODOO_CONTAINER} arrêté."
else
  log "   déjà arrêté."
fi

# Redémarrer Odoo quoi qu'il arrive : ne jamais laisser le service à terre.
restart_odoo() {
  if (( ODOO_WAS_RUNNING )); then
    log "redémarrage d'Odoo…"
    docker start "${ODOO_CONTAINER}" >/dev/null 2>&1 || \
      log "AVERTISSEMENT : redémarrage automatique impossible. Lancez : docker start ${ODOO_CONTAINER}"
  fi
}
trap restart_odoo EXIT

# ─── 5. Restaurer la base ─────────────────────────────────────────
echo; log "5/7 — restauration de la base"

# Couper les connexions résiduelles, sinon DROP DATABASE échoue.
docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
   WHERE datname='${TARGET_DB}' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true

docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres \
  -c "DROP DATABASE IF EXISTS \"${TARGET_DB}\";" >/dev/null \
  || fail "impossible de supprimer la base ${TARGET_DB}."

docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres \
  -c "CREATE DATABASE \"${TARGET_DB}\" TEMPLATE template0 ENCODING 'UTF8';" >/dev/null \
  || fail "impossible de créer la base ${TARGET_DB}."
log "   base recréée, vide."

if docker exec -i "${PG_CONTAINER}" pg_restore \
     -U "${POSTGRES_USER}" -d "${TARGET_DB}" \
     --no-owner --no-privileges \
     < "${BACKUP_PATH}/database.dump" 2>/dev/null; then
  log "   base restaurée."
else
  # pg_restore renvoie un code non nul pour de simples avertissements :
  # on valide sur le contenu réel plutôt que sur le code de sortie.
  NB="$(docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${TARGET_DB}" -tAc \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d '[:space:]')"
  if [[ "${NB:-0}" -gt 50 ]]; then
    log "   base restaurée avec des avertissements (${NB} tables) — acceptable."
  else
    fail "restauration ÉCHOUÉE (${NB:-0} tables). Sauvegarde de sécurité : ${SAFETY:-aucune}"
  fi
fi

# ─── 6. Restaurer le filestore ────────────────────────────────────
echo; log "6/7 — restauration du filestore"
if (( SKIP_FILESTORE )); then
  log "   ignorée (--skip-filestore). ATTENTION : pièces jointes désynchronisées de la base."
else
  # Le conteneur Odoo est arrêté : on utilise un conteneur jetable
  # monté sur le même volume pour écrire dedans.
  VOLUME="$(docker inspect "${ODOO_CONTAINER}" \
    --format '{{range .Mounts}}{{if eq .Destination "/var/lib/odoo"}}{{.Name}}{{end}}{{end}}' 2>/dev/null)"
  [[ -n "${VOLUME}" ]] || fail "volume du filestore introuvable sur ${ODOO_CONTAINER}."
  log "   volume : ${VOLUME}"

  # Vider puis extraire, en préservant la propriété attendue par Odoo (uid 101).
  docker run --rm -i \
    -v "${VOLUME}:/restore" \
    --entrypoint sh \
    "${POSTGRES_IMAGE:-postgres:16-alpine}" -c \
    'set -e; rm -rf /restore/* /restore/.[!.]* 2>/dev/null || true; tar -xzf - -C /restore; chown -R 101:101 /restore' \
    < "${BACKUP_PATH}/filestore.tar.gz" \
    || fail "restauration du filestore échouée."
  log "   filestore restauré."
fi

# ─── 7. Redémarrer et contrôler ───────────────────────────────────
echo; log "7/7 — redémarrage et contrôle de bon fonctionnement"
trap - EXIT
if (( ODOO_WAS_RUNNING )); then
  docker start "${ODOO_CONTAINER}" >/dev/null
else
  ( cd "${COMPOSE_DIR}" && docker compose --env-file "${ENV_FILE}" \
      -f docker-compose.yml -f docker-compose.production.yml up -d odoo >/dev/null )
fi

log "   attente de la disponibilité d'Odoo (jusqu'à 180 s)…"
HEALTHY=0
for _ in $(seq 1 36); do
  sleep 5
  if curl -sf -m 5 "http://127.0.0.1:${ODOO_HTTP_PORT:-18169}/web/health" >/dev/null 2>&1; then
    HEALTHY=1; break
  fi
done

echo
if (( HEALTHY )); then
  log "SUCCÈS : Odoo répond sur 127.0.0.1:${ODOO_HTTP_PORT:-18169}"
  log "Base restaurée : ${TARGET_DB}"
  [[ -n "${SAFETY:-}" ]] && log "Sauvegarde de l'état précédent conservée : ${SAFETY}"
  echo
  log "À contrôler manuellement (§62) : connexion, ouverture d'un enregistrement,"
  log "affichage d'une pièce jointe (valide la cohérence base ↔ filestore)."
else
  log "AVERTISSEMENT : Odoo ne répond pas encore. Consultez les journaux :"
  log "  docker logs --tail 100 ${ODOO_CONTAINER}"
  [[ -n "${SAFETY:-}" ]] && log "Retour arrière possible depuis : ${SAFETY}"
  exit 1
fi
