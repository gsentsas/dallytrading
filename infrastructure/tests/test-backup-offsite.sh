#!/usr/bin/env bash
# Tests isolés de la sémantique fail-closed du backup offsite.
# Aucun conteneur, endpoint S3 ou backup de production n'est utilisé.
set -euo pipefail
umask 0077

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${TEST_DIR}/../.." && pwd)"
BACKUP_SOURCE="${ROOT_DIR}/infrastructure/scripts/backup.sh"
DAILY_SOURCE="${ROOT_DIR}/infrastructure/scripts/backup-daily.sh"
VERIFY_SOURCE="${ROOT_DIR}/infrastructure/scripts/verify-backup.sh"
BASH_BIN="$(command -v bash)"
TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/dallytrading-backup-tests.XXXXXX")"

cleanup() {
  rm -rf -- "${TEST_TMP}"
}
trap cleanup EXIT

PASS_COUNT=0
FAIL_COUNT=0

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf 'PASS %s\n' "$1"
}

fail_test() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf 'FAIL %s\n' "$1" >&2
}

link_required_tools() {
  local target_dir="$1"
  local tool source
  for tool in dirname date python3 flock chmod mkdir stat numfmt head tar sha256sum \
      gzip grep tr touch find sort basename rm mktemp tee sed tail; do
    source="$(command -v "${tool}")"
    ln -s "${source}" "${target_dir}/${tool}"
  done
}

make_case_root() {
  local name="$1"
  local mode="$2"
  local case_root="${TEST_TMP}/${name}"

  mkdir -p "${case_root}/infrastructure/scripts" "${case_root}/mock-bin" \
    "${case_root}/fixture" "${case_root}/state" "${case_root}/backups"
  cp "${BACKUP_SOURCE}" "${case_root}/infrastructure/scripts/backup.sh"
  cp "${DAILY_SOURCE}" "${case_root}/infrastructure/scripts/backup-daily.sh"
  cp "${VERIFY_SOURCE}" "${case_root}/infrastructure/scripts/verify-backup.sh"
  chmod 755 "${case_root}/infrastructure/scripts/"*.sh
  printf 'fixture\n' > "${case_root}/fixture/item.txt"

  cat > "${case_root}/.env" <<ENVFILE
POSTGRES_USER=test_user
POSTGRES_DB=testdb
ODOO_DB_NAME=testdb
COMPOSE_PROJECT_NAME=dallytrading-test
PG_CONTAINER=dallytrading-test-postgres
ODOO_CONTAINER=dallytrading-test-odoo
POSTGRES_VOLUME=dallytrading_test_postgres
ODOO_FILESTORE_VOLUME=dallytrading_test_filestore
PRIVATE_NETWORK=dallytrading_test_private
PUBLIC_NETWORK=dallytrading_test_public
BACKUP_DIR=${case_root}/backups
BACKUP_RETENTION_DAILY=7
BACKUP_RETENTION_WEEKLY=4
BACKUP_RETENTION_MONTHLY=6
ENVFILE

  case "${mode}" in
    disabled)
      cat >> "${case_root}/.env" <<'ENVFILE'
S3_ENDPOINT=
S3_BUCKET=
S3_REGION=
S3_ACCESS_KEY=
S3_SECRET_KEY=
BACKUP_ENCRYPTION_KEY=fixture-encryption-key-present-but-offsite-disabled
ENVFILE
      ;;
    partial)
      cat >> "${case_root}/.env" <<'ENVFILE'
S3_ENDPOINT=
S3_BUCKET=dally-test-bucket
S3_REGION=
S3_ACCESS_KEY=
S3_SECRET_KEY=
BACKUP_ENCRYPTION_KEY=fixture-encryption-key-32-characters-minimum
ENVFILE
      ;;
    enabled)
      cat >> "${case_root}/.env" <<'ENVFILE'
S3_ENDPOINT=https://s3.eu-central-003.example.invalid
S3_BUCKET=dally-test-bucket
S3_REGION=eu-central-003
S3_ACCESS_KEY=fixture-access-key
S3_SECRET_KEY=fixture-secret-key
BACKUP_ENCRYPTION_KEY=fixture-encryption-key-32-characters-minimum
ENVFILE
      ;;
    *)
      printf 'mode de test inconnu\n' >&2
      return 1
      ;;
  esac
  chmod 600 "${case_root}/.env"

  link_required_tools "${case_root}/mock-bin"

  cat > "${case_root}/mock-bin/docker" <<'DOCKER'
#!/bin/bash
set -euo pipefail

if [[ "${1:-}" == "inspect" ]]; then
  shift
  if [[ "${1:-}" == "-f" ]]; then
    format="$2"
    target="$3"
  else
    target="$1"
    shift
    [[ "${1:-}" == "--format" ]]
    format="$2"
  fi

  case "${format}" in
    *State.Running*)
      printf 'true\n'
      ;;
    *com.docker.compose.project*)
      printf '%s\n' "${COMPOSE_PROJECT_NAME}"
      ;;
    *Mounts*)
      if [[ "${target}" == "${PG_CONTAINER}" ]]; then
        printf '%s\n' "${POSTGRES_VOLUME}"
      else
        printf '%s\n' "${ODOO_FILESTORE_VOLUME}"
      fi
      ;;
    *NetworkSettings.Networks*)
      printf '{"%s":{},"%s":{}}\n' "${PRIVATE_NETWORK}" "${PUBLIC_NETWORK}"
      ;;
    *)
      exit 90
      ;;
  esac
  exit 0
fi

if [[ "${1:-}" == "exec" ]]; then
  shift
  if [[ "${1:-}" == "-i" ]]; then
    shift
  fi
  container="$1"
  shift
  command_name="${1:-}"
  shift || true

  case "${command_name}" in
    psql)
      printf '1\n'
      ;;
    test)
      exit 0
      ;;
    pg_dump)
      /bin/dd if=/dev/zero bs=8192 count=1 2>/dev/null
      ;;
    tar)
      /bin/tar -czf - -C "${MOCK_FIXTURE_DIR}" .
      ;;
    odoo)
      printf 'Odoo Server 19.0\n'
      ;;
    postgres)
      printf 'postgres (PostgreSQL) 16.0\n'
      ;;
    pg_restore)
      /bin/cat >/dev/null
      printf '1; 0 0 TABLE DATA public mock test_user\n'
      ;;
    *)
      printf 'unexpected docker exec command for %s: %s\n' \
        "${container}" "${command_name}" >&2
      exit 91
      ;;
  esac
  exit 0
fi

printf 'unexpected docker command\n' >&2
exit 92
DOCKER

  cat > "${case_root}/mock-bin/openssl" <<'OPENSSL'
#!/bin/bash
set -euo pipefail
expected='enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_ENCRYPTION_KEY'
[[ "$*" == "${expected}" ]] || exit 81
[[ -n "${BACKUP_ENCRYPTION_KEY:-}" ]] || exit 82
if [[ "${MOCK_OPENSSL_FAIL:-0}" == "1" ]]; then
  /bin/cat >/dev/null
  exit 83
fi
/bin/cat
OPENSSL

  cat > "${case_root}/mock-bin/aws" <<'AWS'
#!/bin/bash
set -euo pipefail
[[ "${AWS_ACCESS_KEY_ID:-}" == "fixture-access-key" ]] || exit 71
[[ "${AWS_SECRET_ACCESS_KEY:-}" == "fixture-secret-key" ]] || exit 72
[[ "${AWS_DEFAULT_REGION:-}" == "eu-central-003" ]] || exit 73
[[ "${1:-}" == "--endpoint-url" ]] || exit 74
shift 2

case "${1:-}" in
  s3)
    shift
    [[ "${1:-}" == "cp" ]] || exit 75
    source_file="$2"
    destination="$3"
    [[ "${MOCK_AWS_UPLOAD_FAIL:-0}" != "1" ]] || exit 76
    stat -c %s "${source_file}" > "${MOCK_AWS_STATE}/remote-size"
    printf '%s\n' "${destination}" > "${MOCK_AWS_STATE}/destination"
    ;;
  s3api)
    shift
    [[ "${1:-}" == "head-object" ]] || exit 77
    [[ "${MOCK_AWS_VERIFY_FAIL:-0}" != "1" ]] || exit 78
    [[ -f "${MOCK_AWS_STATE}/remote-size" ]] || exit 79
    remote_size="$(< "${MOCK_AWS_STATE}/remote-size")"
    if [[ "${MOCK_AWS_SIZE_MISMATCH:-0}" == "1" ]]; then
      remote_size=$((remote_size + 1))
    fi
    printf '%s\n' "${remote_size}"
    ;;
  *)
    exit 80
    ;;
esac
AWS

  chmod 755 "${case_root}/mock-bin/docker" \
    "${case_root}/mock-bin/openssl" "${case_root}/mock-bin/aws"
  printf '%s\n' "${case_root}"
}

RUN_STATUS=0
RUN_DEST=""
RUN_LOG=""

run_backup() {
  local case_root="$1"
  local failure_mode="${2:-none}"
  local openssl_fail=0
  local upload_fail=0
  local verify_fail=0
  local size_mismatch=0

  case "${failure_mode}" in
    none) ;;
    openssl) openssl_fail=1 ;;
    upload) upload_fail=1 ;;
    verify) verify_fail=1 ;;
    size-mismatch) size_mismatch=1 ;;
    *) return 2 ;;
  esac

  RUN_LOG="${case_root}/backup.log"
  set +e
  PATH="${case_root}/mock-bin" \
    MOCK_FIXTURE_DIR="${case_root}/fixture" \
    MOCK_AWS_STATE="${case_root}/state" \
    MOCK_OPENSSL_FAIL="${openssl_fail}" \
    MOCK_AWS_UPLOAD_FAIL="${upload_fail}" \
    MOCK_AWS_VERIFY_FAIL="${verify_fail}" \
    MOCK_AWS_SIZE_MISMATCH="${size_mismatch}" \
    "${BASH_BIN}" "${case_root}/infrastructure/scripts/backup.sh" --tag daily \
      > "${RUN_LOG}" 2>&1
  RUN_STATUS=$?
  set -e

  RUN_DEST=""
  if [[ -d "${case_root}/backups/daily" ]]; then
    RUN_DEST="$(find "${case_root}/backups/daily" -mindepth 1 -maxdepth 1 \
      -type d | sort | tail -n 1)"
  fi
}

local_backup_complete() {
  local destination="$1"
  local file
  [[ -n "${destination}" && -d "${destination}" ]] || return 1
  for file in database.dump filestore.tar.gz manifest.json SHA256SUMS .complete; do
    [[ -f "${destination}/${file}" ]] || return 1
  done
}

case1_root="$(make_case_root case1 disabled)"
run_backup "${case1_root}"
if (( RUN_STATUS == 0 )) && local_backup_complete "${RUN_DEST}" &&
    grep -Fq 'LOCAL BACKUP COMPLETE' "${RUN_LOG}" &&
    grep -Fq 'OFFSITE DISABLED: not configured' "${RUN_LOG}"; then
  pass "CASE 1 local-only success"
else
  fail_test "CASE 1 local-only success"
fi

case2_root="$(make_case_root case2 enabled)"
run_backup "${case2_root}"
case2_timestamp="$(basename "${RUN_DEST}")"
expected_destination="s3://dally-test-bucket/odoo/daily/daily-${case2_timestamp}.tar.gz.enc"
actual_destination="$(< "${case2_root}/state/destination")"
if (( RUN_STATUS == 0 )) && local_backup_complete "${RUN_DEST}" &&
    grep -Fq 'OFFSITE UPLOAD SUCCESS' "${RUN_LOG}" &&
    grep -Fq 'OFFSITE VERIFY SUCCESS' "${RUN_LOG}" &&
    [[ "${actual_destination}" == "${expected_destination}" ]] &&
    [[ -z "$(find "${case2_root}/backups" -name '*.enc' -print -quit)" ]]; then
  pass "CASE 2 offsite upload and verify success"
else
  fail_test "CASE 2 offsite upload and verify success"
fi

case3_root="$(make_case_root case3 enabled)"
rm -f -- "${case3_root}/mock-bin/aws"
run_backup "${case3_root}"
if (( RUN_STATUS != 0 )) && local_backup_complete "${RUN_DEST}" &&
    grep -Fq 'aws client is missing' "${RUN_LOG}" &&
    grep -Fq 'BACKUP JOB FAILED' "${RUN_LOG}"; then
  pass "CASE 3 aws missing is fatal"
else
  fail_test "CASE 3 aws missing is fatal"
fi

case4_root="$(make_case_root case4 partial)"
run_backup "${case4_root}"
if (( RUN_STATUS != 0 )) && local_backup_complete "${RUN_DEST}" &&
    grep -Fq 'OFFSITE CONFIGURATION FAILED' "${RUN_LOG}" &&
    grep -Fq 'BACKUP JOB FAILED' "${RUN_LOG}"; then
  pass "CASE 4 partial offsite configuration is fatal"
else
  fail_test "CASE 4 partial offsite configuration is fatal"
fi

case5_root="$(make_case_root case5 enabled)"
run_backup "${case5_root}" openssl
if (( RUN_STATUS != 0 )) && local_backup_complete "${RUN_DEST}" &&
    grep -Fq 'OFFSITE ENCRYPTION FAILED' "${RUN_LOG}" &&
    [[ -z "$(find "${case5_root}/backups" -name '*.enc' -print -quit)" ]]; then
  pass "CASE 5 encryption failure is fatal"
else
  fail_test "CASE 5 encryption failure is fatal"
fi

case6_root="$(make_case_root case6 enabled)"
run_backup "${case6_root}" upload
case6_log="${RUN_LOG}"
if (( RUN_STATUS != 0 )) && local_backup_complete "${RUN_DEST}" &&
    grep -Fq 'OFFSITE UPLOAD FAILED' "${RUN_LOG}" &&
    grep -Fq 'LOCAL BACKUP PRESERVED' "${RUN_LOG}"; then
  pass "CASE 6 upload failure is fatal"
else
  fail_test "CASE 6 upload failure is fatal"
fi

case7_root="$(make_case_root case7 enabled)"
run_backup "${case7_root}" verify
case7_dest="${RUN_DEST}"
if (( RUN_STATUS != 0 )) && local_backup_complete "${RUN_DEST}" &&
    grep -Fq 'OFFSITE UPLOAD SUCCESS' "${RUN_LOG}" &&
    grep -Fq 'OFFSITE VERIFY FAILED' "${RUN_LOG}"; then
  pass "CASE 7 remote verification failure is fatal"
else
  fail_test "CASE 7 remote verification failure is fatal"
fi

set +e
PATH="${case7_root}/mock-bin" \
  MOCK_FIXTURE_DIR="${case7_root}/fixture" \
  "${BASH_BIN}" "${case7_root}/infrastructure/scripts/verify-backup.sh" \
    "${case7_dest}" > "${case7_root}/verify.log" 2>&1
verify_status=$?
set -e
if (( verify_status == 0 )) && local_backup_complete "${case7_dest}"; then
  pass "CASE 8 failed offsite preserves a verifiable local backup"
else
  fail_test "CASE 8 failed offsite preserves a verifiable local backup"
fi

if ! grep -Fq 'fixture-access-key' "${case6_log}" &&
    ! grep -Fq 'fixture-secret-key' "${case6_log}" &&
    ! grep -Fq 'fixture-encryption-key-32-characters-minimum' "${case6_log}"; then
  pass "CASE 9 offsite failure logs contain no secret"
else
  fail_test "CASE 9 offsite failure logs contain no secret"
fi

case10_root="$(make_case_root case10 disabled)"
cat > "${case10_root}/infrastructure/scripts/backup.sh" <<'BACKUP_STUB'
#!/bin/bash
printf '[backup] simulated required offsite failure\n'
exit 23
BACKUP_STUB
cat > "${case10_root}/infrastructure/scripts/verify-backup.sh" <<'VERIFY_STUB'
#!/bin/bash
touch "${MOCK_VERIFY_CALLED}"
exit 0
VERIFY_STUB
chmod 755 "${case10_root}/infrastructure/scripts/backup.sh" \
  "${case10_root}/infrastructure/scripts/verify-backup.sh"
mkdir -p "${case10_root}/tmp"
set +e
PATH="${case10_root}/mock-bin" TMPDIR="${case10_root}/tmp" \
  MOCK_VERIFY_CALLED="${case10_root}/verify-called" \
  "${BASH_BIN}" "${case10_root}/infrastructure/scripts/backup-daily.sh" \
    > "${case10_root}/daily.log" 2>&1
daily_status=$?
set -e
if (( daily_status != 0 )) &&
    grep -Fq 'backup.sh a échoué avec le statut 23' "${case10_root}/daily.log" &&
    [[ ! -e "${case10_root}/verify-called" ]]; then
  pass "CASE 10 backup-daily propagates a non-zero backup status"
else
  fail_test "CASE 10 backup-daily propagates a non-zero backup status"
fi

case11_root="$(make_case_root case11 enabled)"
run_backup "${case11_root}" size-mismatch
if (( RUN_STATUS != 0 )) && local_backup_complete "${RUN_DEST}" &&
    grep -Fq 'remote object missing or size mismatch' "${RUN_LOG}"; then
  pass "CASE 11 remote size mismatch is fatal"
else
  fail_test "CASE 11 remote size mismatch is fatal"
fi

case12_root="$(make_case_root case12 disabled)"
cat >> "${case12_root}/.env" <<'ENVFILE'
BACKUP_RETENTION_DAILY=1
ENVFILE
old_backup="${case12_root}/backups/daily/20200101T000000Z"
mkdir -p "${old_backup}"
touch "${old_backup}/.complete"
chmod 700 "${case12_root}/backups" "${case12_root}/backups/daily" "${old_backup}"
chmod 600 "${old_backup}/.complete"
run_backup "${case12_root}"
permissions_ok=1
while IFS= read -r path; do
  [[ "$(stat -c %a "${path}")" == "700" ]] || permissions_ok=0
done < <(find "${case12_root}/backups" -type d)
while IFS= read -r path; do
  [[ "$(stat -c %a "${path}")" == "600" ]] || permissions_ok=0
done < <(find "${case12_root}/backups" -type f)
if (( RUN_STATUS == 0 && permissions_ok == 1 )) &&
    local_backup_complete "${RUN_DEST}" && [[ ! -e "${old_backup}" ]]; then
  pass "CASE 12 retention and 700/600 permissions are preserved"
else
  fail_test "CASE 12 retention and 700/600 permissions are preserved"
fi

printf 'RESULT pass=%d fail=%d total=%d\n' \
  "${PASS_COUNT}" "${FAIL_COUNT}" "$((PASS_COUNT + FAIL_COUNT))"
(( FAIL_COUNT == 0 ))
