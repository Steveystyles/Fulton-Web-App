#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly CANONICAL_APP_REPO_URL="https://github.com/Steveystyles/Fulton-Web-App.git"
readonly CANONICAL_IMAGE_REPOSITORY="ghcr.io/steveystyles/fulton-web-app"
readonly COSIGN_CERTIFICATE_IDENTITY_REGEXP='^https://github\.com/Steveystyles/Fulton-Web-App/\.github/workflows/build\.yml@refs/heads/main$'
readonly COSIGN_CERTIFICATE_OIDC_ISSUER='https://token.actions.githubusercontent.com'
readonly SHA_PATTERN='^[0-9a-f]{40}$'
readonly DIGEST_IMAGE_PATTERN='^[A-Za-z0-9._:/-]+@sha256:[0-9a-f]{64}$'

APP_COMMIT="${1:-}"
APP_REPO_URL="${APP_REPO_URL:-${CANONICAL_APP_REPO_URL}}"
COMPOSE_DIR="${COMPOSE_DIR:-${HOME}/fulton-web-app-deploy}"
COMPOSE_ENV_FILE="${COMPOSE_DIR}/.env"

read_compose_path_setting() {
  python3 - "${1:?dotenv path required}" "${2:?key required}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
if not path.exists():
    raise SystemExit(0)
if path.is_symlink() or not path.is_file():
    raise SystemExit("compose dotenv must be a regular, non-symlink file")
found = []
for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    candidate, value = line.split("=", 1)
    if candidate.strip() != key:
        continue
    value = value.strip()
    if not value or len(value) > 4096:
        raise SystemExit(f"invalid {key} in compose dotenv")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SystemExit(f"invalid {key} in compose dotenv")
    found.append(value)
if len(found) > 1:
    raise SystemExit(f"duplicate {key} in compose dotenv")
if found:
    print(found[0])
PY
}

configured_src_dir="$(read_compose_path_setting "${COMPOSE_ENV_FILE}" "FULTONS_SRC_DIR")"
configured_env_file="$(read_compose_path_setting "${COMPOSE_ENV_FILE}" "FULTONS_ENV_FILE")"
configured_data_dir="$(read_compose_path_setting "${COMPOSE_ENV_FILE}" "FULTONS_HOST_DATA_DIR")"
configured_offhost_required="$(read_compose_path_setting "${COMPOSE_ENV_FILE}" "FULTONS_OFFHOST_BACKUP_REQUIRED")"
configured_offhost_command="$(read_compose_path_setting "${COMPOSE_ENV_FILE}" "FULTONS_OFFHOST_BACKUP_COMMAND")"
SRC_DIR="${SRC_DIR:-${configured_src_dir:-${HOME}/fulton-web-app}}"
DATA_DIR="${DATA_DIR:-${FULTONS_HOST_DATA_DIR:-${configured_data_dir:-/srv/storage/appdata/fultons-quiz}}}"
BACKUP_ROOT="${BACKUP_ROOT:-/srv/storage/backups/fultons-quiz}"
ENV_FILE="${ENV_FILE:-${FULTONS_ENV_FILE:-${configured_env_file:-${DATA_DIR}/app.env}}}"
DEPLOY_IMAGE="${FULTONS_DEPLOY_IMAGE:-}"
OFFHOST_BACKUP_REQUIRED="${FULTONS_OFFHOST_BACKUP_REQUIRED:-${configured_offhost_required:-0}}"
OFFHOST_BACKUP_COMMAND="${FULTONS_OFFHOST_BACKUP_COMMAND:-${configured_offhost_command:-}}"
# This is deliberately process-only: persisting the bootstrap gate in deploy/.env
# would turn a one-shot reviewed exception into an ambient deployment capability.
ALLOW_DATABASE_BOOTSTRAP="${FULTONS_ALLOW_DATABASE_BOOTSTRAP:-0}"
LOCAL_BUILD_DEV_OVERRIDE="${FULTONS_ALLOW_LOCAL_BUILD_DEV_OVERRIDE:-0}"
ALLOW_UNREACHABLE_COMMIT="${FULTONS_ALLOW_UNREACHABLE_COMMIT:-0}"
REVIEWED_COMMIT="${FULTONS_REVIEWED_COMMIT:-}"
HEALTH_ATTEMPTS="${FULTONS_DEPLOY_HEALTH_ATTEMPTS:-30}"
HEALTH_INTERVAL_SEC="${FULTONS_DEPLOY_HEALTH_INTERVAL_SEC:-2}"

COMPOSE_FILE=""
BACKUP_DIR=""
PREVIOUS_IMAGE=""
PREVIOUS_REVISION=""
ROLLOUT_STARTED=0
DEPLOY_SUCCEEDED=0
ROLLBACK_RUNNING=0
PREVIOUS_COMPOSE_FILE=""
PREVIOUS_COMPOSE_ENV_FILE=""
BOOTSTRAP_MODE=0
BOOTSTRAP_STAGE=""

log() {
  printf '[fultons-deploy] %s\n' "$*"
}

fail() {
  log "ERROR: $*"
  return 1
}

require_boolean() {
  local name="${1:?name required}"
  local value="${2-}"
  case "${value}" in
    0|1) ;;
    *) fail "${name} must be 0 or 1 (received ${value})." ;;
  esac
}

require_positive_integer() {
  local name="${1:?name required}"
  local value="${2-}"
  [[ "${value}" =~ ^[1-9][0-9]*$ ]] || fail "${name} must be a positive integer."
}

resolve_abs_path() {
  python3 - "${1:?path required}" <<'PY'
import os
import re
import sys

raw = sys.argv[1]
if not raw or any(ord(character) < 32 or ord(character) == 127 for character in raw):
    raise SystemExit("deployment path contains control characters")
if not re.fullmatch(r"/[A-Za-z0-9._/-]+", raw):
    raise SystemExit("deployment path contains unsupported characters")
print(os.path.realpath(raw))
PY
}

require_safe_directory_path() {
  local name="${1:?name required}"
  local path="${2:?path required}"
  case "${path}" in
    /|/home|/srv|/var|/tmp|"${HOME}") fail "${name} is too broad: ${path}" ;;
  esac
  [[ "${path}" = /* ]] || fail "${name} must be absolute: ${path}"
}

atomic_upsert_env_var() {
  local file="${1:?file required}"
  local key="${2:?key required}"
  local value="${3-}"
  python3 - "${file}" "${key}" "${value}" <<'PY'
import os
import stat
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
if path.is_symlink() or (path.exists() and not path.is_file()):
    raise SystemExit(f"environment path is not a regular, non-symlink file: {path}")
prefix = f"{key}="
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
result = []
updated = False
for line in lines:
    candidate = line.split("=", 1)[0].strip() if "=" in line else ""
    if candidate == key:
        if not updated:
            result.append(prefix + value)
            updated = True
    else:
        result.append(line)
if not updated:
    result.append(prefix + value)

path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
try:
    os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        descriptor = -1
        handle.write("\n".join(result).rstrip("\n") + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
finally:
    if descriptor >= 0:
        os.close(descriptor)
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

validate_bootstrap_environment() {
  python3 - "${ENV_FILE}" "${DATA_DIR}" <<'PY'
import os
import sys
from pathlib import Path

environment_path = Path(sys.argv[1])
data_dir = Path(sys.argv[2])
if environment_path.is_symlink() or not environment_path.is_file():
    raise SystemExit("bootstrap environment must be a regular, non-symlink file")

allowed_path = environment_path.resolve(strict=True)
for entry in data_dir.iterdir():
    if entry.is_symlink():
        raise SystemExit(f"bootstrap data directory contains a link: {entry.name}")
    try:
        is_environment = entry.resolve(strict=True) == allowed_path
    except OSError as error:
        raise SystemExit(f"cannot inspect bootstrap data entry {entry.name}: {error}") from error
    if not is_environment:
        raise SystemExit(
            f"bootstrap requires an otherwise empty data directory; found {entry.name}"
        )

required = {
    "FULTONS_REQUIRE_EXISTING_DB": "0",
    "FULTONS_MIN_DB_USERS": "0",
    "FULTONS_SEED_DEMO_USERS": "0",
}
secrets = {
    "FULTONS_BOOTSTRAP_ADMIN_USERNAME",
    "FULTONS_BOOTSTRAP_ADMIN_PASSWORD",
}
values = {}
for raw_line in environment_path.read_text(encoding="utf-8-sig").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    if key not in required and key not in secrets:
        continue
    if key in values:
        raise SystemExit(f"bootstrap environment contains duplicate {key}")
    values[key] = value.strip()

for key, expected in required.items():
    if values.get(key) != expected:
        raise SystemExit(f"bootstrap requires {key}={expected}")
for key in secrets:
    value = values.get(key, "")
    if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SystemExit(f"bootstrap requires a non-empty, single-line {key}")
PY
}

finalize_bootstrap_environment() {
  python3 - "${ENV_FILE}" <<'PY'
import os
import stat
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
if path.is_symlink() or not path.is_file():
    raise SystemExit("bootstrap environment must be a regular, non-symlink file")
updates = {
    "FULTONS_REQUIRE_EXISTING_DB": "1",
    "FULTONS_MIN_DB_USERS": "1",
    "FULTONS_SEED_DEMO_USERS": "0",
    "FULTONS_BOOTSTRAP_ADMIN_USERNAME": "",
    "FULTONS_BOOTSTRAP_ADMIN_PASSWORD": "",
}
result = []
written = set()
for line in path.read_text(encoding="utf-8-sig").splitlines():
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in updates:
        if key not in written:
            result.append(f"{key}={updates[key]}")
            written.add(key)
        continue
    result.append(line)
for key, value in updates.items():
    if key not in written:
        result.append(f"{key}={value}")

descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
try:
    os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        descriptor = -1
        handle.write("\n".join(result).rstrip("\n") + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
finally:
    if descriptor >= 0:
        os.close(descriptor)
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

compose() {
  docker compose --env-file "${COMPOSE_ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

container_exists() {
  docker container inspect fultons-quiz >/dev/null 2>&1
}

container_is_healthy() {
  docker exec fultons-quiz python -c \
    "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=3)); raise SystemExit(0 if data.get('ok') else 1)" \
    >/dev/null 2>&1
}

wait_for_health() {
  local label="${1:?health label required}"
  local attempt
  for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt += 1)); do
    if container_is_healthy; then
      log "${label} health check passed"
      return 0
    fi
    sleep "${HEALTH_INTERVAL_SEC}"
  done
  docker logs --tail 80 fultons-quiz || true
  fail "${label} health check failed after ${HEALTH_ATTEMPTS} attempts."
}

rollback_deployment() {
  local original_status="${1:-1}"
  trap - ERR INT TERM
  if [ "${ROLLBACK_RUNNING}" = "1" ]; then
    exit "${original_status}"
  fi
  ROLLBACK_RUNNING=1

  if [ "${ROLLOUT_STARTED}" != "1" ] || [ "${DEPLOY_SUCCEEDED}" = "1" ]; then
    exit "${original_status}"
  fi
  if [ -z "${PREVIOUS_IMAGE}" ]; then
    log "Rollback unavailable: no previous healthy container image was recorded."
    exit "${original_status}"
  fi

  log "Rolling back to immutable image ${PREVIOUS_IMAGE}"
  if [ -n "${PREVIOUS_COMPOSE_FILE}" ] && [ -f "${PREVIOUS_COMPOSE_FILE}" ]; then
    if ! cp -p "${PREVIOUS_COMPOSE_FILE}" "${COMPOSE_FILE}"; then
      log "CRITICAL: could not restore the previous compose definition."
      exit "${original_status}"
    fi
  fi
  if [ -n "${PREVIOUS_COMPOSE_ENV_FILE}" ] && [ -f "${PREVIOUS_COMPOSE_ENV_FILE}" ]; then
    if ! cp -p "${PREVIOUS_COMPOSE_ENV_FILE}" "${COMPOSE_ENV_FILE}"; then
      log "CRITICAL: could not restore the previous compose environment."
      exit "${original_status}"
    fi
  else
    if ! atomic_upsert_env_var "${COMPOSE_ENV_FILE}" "FULTONS_IMAGE" "${PREVIOUS_IMAGE}"; then
      log "CRITICAL: could not restore the previous compose image selection."
      exit "${original_status}"
    fi
  fi
  unset FULTONS_SRC_DIR FULTONS_ENV_FILE FULTONS_HOST_DATA_DIR
  export FULTONS_IMAGE="${PREVIOUS_IMAGE}"
  if ! compose up -d --no-build --force-recreate quiz-app; then
    log "CRITICAL: compose rollback failed."
    exit "${original_status}"
  fi
  if ! wait_for_health "Rollback"; then
    log "CRITICAL: rollback container did not become healthy. Manual recovery is required."
    exit "${original_status}"
  fi
  local rollback_image
  rollback_image="$(docker inspect fultons-quiz --format '{{.Image}}')"
  if [ "${rollback_image}" != "${PREVIOUS_IMAGE}" ]; then
    log "CRITICAL: rollback image ${rollback_image:-unknown} does not match ${PREVIOUS_IMAGE}."
    exit "${original_status}"
  fi
  if [ -n "${PREVIOUS_REVISION}" ]; then
    local rollback_revision
    rollback_revision="$(docker inspect fultons-quiz --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
    if [ "${rollback_revision}" != "${PREVIOUS_REVISION}" ]; then
      log "CRITICAL: rollback revision ${rollback_revision:-unknown} does not match ${PREVIOUS_REVISION}."
      exit "${original_status}"
    fi
  fi
  log "Rollback health and revision verification passed."
  exit "${original_status}"
}

on_error() {
  local status=$?
  local line="${BASH_LINENO[0]:-unknown}"
  log "Deployment failed at line ${line} (status ${status})."
  rollback_deployment "${status}"
}

trap on_error ERR
trap 'rollback_deployment 130' INT
trap 'rollback_deployment 143' TERM

require_boolean "FULTONS_OFFHOST_BACKUP_REQUIRED" "${OFFHOST_BACKUP_REQUIRED}"
require_boolean "FULTONS_ALLOW_DATABASE_BOOTSTRAP" "${ALLOW_DATABASE_BOOTSTRAP}"
require_boolean "FULTONS_ALLOW_LOCAL_BUILD_DEV_OVERRIDE" "${LOCAL_BUILD_DEV_OVERRIDE}"
require_boolean "FULTONS_ALLOW_UNREACHABLE_COMMIT" "${ALLOW_UNREACHABLE_COMMIT}"
require_positive_integer "FULTONS_DEPLOY_HEALTH_ATTEMPTS" "${HEALTH_ATTEMPTS}"
require_positive_integer "FULTONS_DEPLOY_HEALTH_INTERVAL_SEC" "${HEALTH_INTERVAL_SEC}"

[[ "${APP_COMMIT}" =~ ${SHA_PATTERN} ]] || fail \
  "Usage: homeserver-update.sh <full-lowercase-40-character-commit-sha>"
if [ "${APP_REPO_URL}" != "${CANONICAL_APP_REPO_URL}" ]; then
  fail "APP_REPO_URL must be the canonical OCI source ${CANONICAL_APP_REPO_URL}."
fi
if [ "${ALLOW_UNREACHABLE_COMMIT}" = "1" ] && [ "${REVIEWED_COMMIT}" != "${APP_COMMIT}" ]; then
  fail "Unreachable-commit override requires FULTONS_REVIEWED_COMMIT=${APP_COMMIT}."
fi
if [ "${LOCAL_BUILD_DEV_OVERRIDE}" = "1" ] && [ "${REVIEWED_COMMIT}" != "${APP_COMMIT}" ]; then
  fail "Local-build development override requires FULTONS_REVIEWED_COMMIT=${APP_COMMIT}."
fi

SRC_DIR="$(resolve_abs_path "${SRC_DIR}")"
DATA_DIR="$(resolve_abs_path "${DATA_DIR}")"
BACKUP_ROOT="$(resolve_abs_path "${BACKUP_ROOT}")"
COMPOSE_DIR="$(resolve_abs_path "${COMPOSE_DIR}")"
ENV_FILE="$(resolve_abs_path "${ENV_FILE}")"
COMPOSE_FILE="${COMPOSE_DIR}/compose.yaml"
COMPOSE_ENV_FILE="${COMPOSE_DIR}/.env"
require_safe_directory_path "SRC_DIR" "${SRC_DIR}"
require_safe_directory_path "DATA_DIR" "${DATA_DIR}"
require_safe_directory_path "BACKUP_ROOT" "${BACKUP_ROOT}"
require_safe_directory_path "COMPOSE_DIR" "${COMPOSE_DIR}"

mkdir -p -m 700 "${DATA_DIR}" "${BACKUP_ROOT}" "${COMPOSE_DIR}" "$(dirname "${ENV_FILE}")"
chmod 700 "${BACKUP_ROOT}" "${COMPOSE_DIR}" || true
command -v flock >/dev/null 2>&1 || fail "flock is required to serialize deployments."
exec 9>"${COMPOSE_DIR}/.deploy.lock"
chmod 600 "${COMPOSE_DIR}/.deploy.lock"
flock -n 9 || fail "Another Fulton deployment is already running."
if [ -f "${COMPOSE_FILE}" ]; then
  PREVIOUS_COMPOSE_FILE="${COMPOSE_DIR}/.compose.yaml.rollback"
  install -m 600 "${COMPOSE_FILE}" "${PREVIOUS_COMPOSE_FILE}"
fi
if [ -f "${COMPOSE_ENV_FILE}" ]; then
  PREVIOUS_COMPOSE_ENV_FILE="${COMPOSE_DIR}/.env.rollback"
  install -m 600 "${COMPOSE_ENV_FILE}" "${PREVIOUS_COMPOSE_ENV_FILE}"
fi

if [ ! -d "${SRC_DIR}/.git" ]; then
  fail "A pre-existing canonical Git checkout is required at ${SRC_DIR}; cloning during deployment is disabled."
fi
actual_origin="$(git -C "${SRC_DIR}" remote get-url origin)"
if [ "${actual_origin}" != "${CANONICAL_APP_REPO_URL}" ]; then
  fail "Source checkout origin is ${actual_origin}; expected ${CANONICAL_APP_REPO_URL}."
fi

log "Fetching canonical refs without changing the healthy checkout"
git -C "${SRC_DIR}" fetch --tags --prune origin
git -C "${SRC_DIR}" cat-file -e "${APP_COMMIT}^{commit}"
actual_head="$(git -C "${SRC_DIR}" rev-parse HEAD)"
if [ "${actual_head}" != "${APP_COMMIT}" ]; then
  fail "Source checkout HEAD ${actual_head} does not match requested commit ${APP_COMMIT}."
fi
if [ -n "$(git -C "${SRC_DIR}" status --porcelain --untracked-files=all)" ]; then
  fail "Source checkout must be clean so deployment helpers match the reviewed commit."
fi
if ! git -C "${SRC_DIR}" merge-base --is-ancestor "${APP_COMMIT}" "origin/main"; then
  if [ "${ALLOW_UNREACHABLE_COMMIT}" != "1" ]; then
    fail "Commit ${APP_COMMIT} is not reachable from origin/main. A reviewed override is required."
  fi
  log "Using explicit reviewed override for commit not reachable from origin/main."
fi

if [ -L "${ENV_FILE}" ] || [ ! -f "${ENV_FILE}" ]; then
  fail "Private application environment is missing at ${ENV_FILE}; deployment will not synthesize credentials."
fi
chmod 600 "${ENV_FILE}"

if container_exists; then
  if [ ! -f "${COMPOSE_FILE}" ] || [ ! -f "${COMPOSE_ENV_FILE}" ]; then
    fail "A healthy deployment requires its compose.yaml and .env for verified rollback."
  fi
  container_is_healthy || fail "Existing fultons-quiz container is not healthy; repair it before deploying."
  # Docker's immutable local content ID remains a valid rollback target even
  # when the legacy compose file originally selected a mutable tag.
  PREVIOUS_IMAGE="$(docker inspect fultons-quiz --format '{{.Image}}')"
  PREVIOUS_REVISION="$(docker inspect fultons-quiz --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
  if [ -z "${PREVIOUS_IMAGE}" ]; then
    fail "Could not record the current healthy container image for rollback."
  fi
  [[ "${PREVIOUS_IMAGE}" =~ ^sha256:[0-9a-f]{64}$ ]] || fail \
    "The healthy current deployment did not expose an immutable image ID for rollback."
  log "Recorded healthy rollback image ${PREVIOUS_IMAGE}"
fi

if [ -L "${DATA_DIR}/fultons.db" ]; then
  fail "Runtime database cannot be a symbolic link."
fi
if [ ! -f "${DATA_DIR}/fultons.db" ]; then
  [ "${ALLOW_DATABASE_BOOTSTRAP}" = "1" ] || fail \
    "Required runtime database is missing; set FULTONS_ALLOW_DATABASE_BOOTSTRAP=1 only for a reviewed first deployment."
  [ "${LOCAL_BUILD_DEV_OVERRIDE}" = "0" ] || fail \
    "Database bootstrap requires a signed registry digest; local-build override is not accepted."
  [ "${REVIEWED_COMMIT}" = "${APP_COMMIT}" ] || fail \
    "Database bootstrap requires FULTONS_REVIEWED_COMMIT=${APP_COMMIT}."
  if container_exists; then
    fail "Database bootstrap is forbidden while a fultons-quiz container exists."
  fi
  validate_bootstrap_environment
  BOOTSTRAP_MODE=1
fi

if [ "${LOCAL_BUILD_DEV_OVERRIDE}" = "1" ]; then
  log "Building locally under explicit development override; production must supply a registry digest."
  local_tag="local/fulton-web-app:dev-${APP_COMMIT}"
  git -C "${SRC_DIR}" archive --format=tar "${APP_COMMIT}" | docker build --pull \
    --build-arg "FULTONS_BUILD_COMMIT=${APP_COMMIT}" \
    --label "org.opencontainers.image.source=${CANONICAL_APP_REPO_URL}" \
    --label "org.opencontainers.image.revision=${APP_COMMIT}" \
    -t "${local_tag}" -
  local_image_id="$(docker image inspect "${local_tag}" --format '{{.Id}}')"
  [[ "${local_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "Local build did not produce a content-addressed image ID."
  DEPLOY_IMAGE="${local_image_id}"
else
  [[ "${DEPLOY_IMAGE}" =~ ${DIGEST_IMAGE_PATTERN} ]] || fail \
    "FULTONS_DEPLOY_IMAGE must be an immutable registry reference ending @sha256:<64 hex>."
  image_repository="${DEPLOY_IMAGE%@sha256:*}"
  if [ "${image_repository}" != "${CANONICAL_IMAGE_REPOSITORY}" ]; then
    fail "FULTONS_DEPLOY_IMAGE must use canonical repository ${CANONICAL_IMAGE_REPOSITORY}."
  fi
  command -v cosign >/dev/null 2>&1 || fail \
    "cosign is required to verify the signed production image."
  log "Verifying keyless GitHub Actions signature for immutable image"
  cosign verify \
    --certificate-identity-regexp "${COSIGN_CERTIFICATE_IDENTITY_REGEXP}" \
    --certificate-oidc-issuer "${COSIGN_CERTIFICATE_OIDC_ISSUER}" \
    "${DEPLOY_IMAGE}" >/dev/null
  docker pull "${DEPLOY_IMAGE}"
fi

image_revision="$(docker image inspect "${DEPLOY_IMAGE}" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
image_source="$(docker image inspect "${DEPLOY_IMAGE}" --format '{{ index .Config.Labels "org.opencontainers.image.source" }}')"
if [ "${image_revision}" != "${APP_COMMIT}" ]; then
  fail "Image revision ${image_revision:-unknown} does not match requested commit ${APP_COMMIT}."
fi
if [ "${image_source}" != "${CANONICAL_APP_REPO_URL}" ]; then
  fail "Image source ${image_source:-unknown} is not the canonical OCI source."
fi

if [ "${BOOTSTRAP_MODE}" = "1" ]; then
  log "Initializing the first database with the verified signed image in an isolated staging directory"
  BOOTSTRAP_STAGE="$(mktemp -d "${DATA_DIR}/.fultons-bootstrap-${APP_COMMIT}.XXXXXX")"
  chmod 700 "${BOOTSTRAP_STAGE}"
  docker run --rm \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --env-file "${ENV_FILE}" \
    --env FULTONS_EXPECT_DATA_DIR=/app/data \
    --volume "${BOOTSTRAP_STAGE}:/app/data" \
    --entrypoint python \
    "${DEPLOY_IMAGE}" -c \
    "import server; server.assert_runtime_storage_ready('signed bootstrap preflight'); server.initialize_database(); server.assert_runtime_storage_ready('signed bootstrap completion')"

  python3 - "${BOOTSTRAP_STAGE}" <<'PY'
import sqlite3
import sys
from pathlib import Path

stage = Path(sys.argv[1])
database = stage / "fultons.db"
entries = list(stage.iterdir())
if entries != [database] or database.is_symlink() or not database.is_file():
    raise SystemExit("signed bootstrap produced unexpected data-directory entries")
connection = sqlite3.connect(f"{database.resolve(strict=True).as_uri()}?mode=ro", uri=True, timeout=10)
try:
    check = connection.execute("PRAGMA quick_check").fetchone()[0]
    user_count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    admin_count = int(
        connection.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
    )
finally:
    connection.close()
if check != "ok" or user_count < 1 or admin_count < 1:
    raise SystemExit(
        f"signed bootstrap validation failed: quick_check={check!r}, "
        f"users={user_count}, admins={admin_count}"
    )
PY

  # Clear one-time credentials and enable normal production storage guards in
  # one atomic replacement before the staged database becomes live.
  finalize_bootstrap_environment
  python3 - "${BOOTSTRAP_STAGE}/fultons.db" "${DATA_DIR}/fultons.db" <<'PY'
import os
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
if source.is_symlink() or not source.is_file() or destination.exists():
    raise SystemExit("refusing unsafe bootstrap database promotion")
os.replace(source, destination)
os.chmod(destination, 0o600)
directory = os.open(destination.parent, os.O_RDONLY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
  rmdir "${BOOTSTRAP_STAGE}"
  BOOTSTRAP_STAGE=""
  log "Signed database bootstrap succeeded; one-time credentials were removed."
fi

log "Checking live SQLite before backup"
python3 - "${DATA_DIR}/fultons.db" <<'PY'
import sqlite3
import sys
from pathlib import Path

path = sys.argv[1]
database = Path(path)
if not database.is_file():
    raise SystemExit(f"Required runtime database is missing: {path}")
connection = sqlite3.connect(f"{database.resolve(strict=True).as_uri()}?mode=ro", uri=True, timeout=10)
try:
    check = connection.execute("PRAGMA quick_check").fetchone()[0]
    users_table = connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()[0]
    user_count = (
        int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        if users_table == 1
        else 0
    )
finally:
    connection.close()
if check != "ok":
    raise SystemExit(f"SQLite preflight failed: {check}")
if user_count < 1:
    raise SystemExit("SQLite preflight failed: users table is missing or empty")
PY

log "Creating transactionally consistent private backup"
BACKUP_DIR="$(python3 "${SRC_DIR}/deploy/backup_manager.py" create \
  --data-dir "${DATA_DIR}" --backup-root "${BACKUP_ROOT}")"
python3 "${SRC_DIR}/deploy/backup_manager.py" verify "${BACKUP_DIR}" >/dev/null

if [ "${OFFHOST_BACKUP_REQUIRED}" = "1" ] && [ -z "${OFFHOST_BACKUP_COMMAND}" ]; then
  fail "Off-host backup is required but FULTONS_OFFHOST_BACKUP_COMMAND is not configured."
fi
if [ -n "${OFFHOST_BACKUP_COMMAND}" ]; then
  log "Running configured off-host encrypted-copy gate"
  export FULTONS_BACKUP_DIR="${BACKUP_DIR}"
  export FULTONS_BACKUP_MANIFEST="${BACKUP_DIR}/manifest.json"
  # The administrator owns this executable and its encryption/remote verification policy.
  # It is deliberately not passed through a shell, so shell metacharacters are not interpreted.
  if [[ "${OFFHOST_BACKUP_COMMAND}" != /* ]] || [ ! -x "${OFFHOST_BACKUP_COMMAND}" ]; then
    fail "FULTONS_OFFHOST_BACKUP_COMMAND must be an absolute executable path."
  fi
  "${OFFHOST_BACKUP_COMMAND}" "${BACKUP_DIR}"
  offhost_marker="${BACKUP_DIR}/offhost-copy.verified"
  if [ "${OFFHOST_BACKUP_REQUIRED}" = "1" ] && \
     { [ -L "${offhost_marker}" ] || [ ! -f "${offhost_marker}" ]; }; then
    fail "Required off-host copy did not write offhost-copy.verified after encrypted remote verification."
  fi
  if [ -e "${offhost_marker}" ] || [ -L "${offhost_marker}" ]; then
    [ ! -L "${offhost_marker}" ] && [ -f "${offhost_marker}" ] || fail \
      "Off-host verification marker is not a regular file."
    chmod 600 "${offhost_marker}"
  fi
  python3 "${SRC_DIR}/deploy/backup_manager.py" verify "${BACKUP_DIR}" >/dev/null
  if [ "${OFFHOST_BACKUP_REQUIRED}" = "1" ]; then
    python3 "${SRC_DIR}/deploy/backup_manager.py" verify-offhost "${BACKUP_DIR}" >/dev/null
  fi
fi

compose_candidate="${COMPOSE_DIR}/.compose.yaml.${APP_COMMIT}.new"
install -m 600 "${SRC_DIR}/deploy/compose.yaml" "${compose_candidate}"
candidate_env="${COMPOSE_DIR}/.env.candidate-${APP_COMMIT}"
if [ -f "${COMPOSE_ENV_FILE}" ]; then
  install -m 600 "${COMPOSE_ENV_FILE}" "${candidate_env}"
else
  : > "${candidate_env}"
  chmod 600 "${candidate_env}"
fi
atomic_upsert_env_var "${candidate_env}" "FULTONS_SRC_DIR" "${SRC_DIR}"
atomic_upsert_env_var "${candidate_env}" "FULTONS_ENV_FILE" "${ENV_FILE}"
atomic_upsert_env_var "${candidate_env}" "FULTONS_HOST_DATA_DIR" "${DATA_DIR}"
atomic_upsert_env_var "${candidate_env}" "FULTONS_IMAGE" "${DEPLOY_IMAGE}"
export FULTONS_SRC_DIR="${SRC_DIR}"
export FULTONS_ENV_FILE="${ENV_FILE}"
export FULTONS_HOST_DATA_DIR="${DATA_DIR}"
export FULTONS_IMAGE="${DEPLOY_IMAGE}"
docker compose --env-file "${candidate_env}" -f "${compose_candidate}" config --quiet
ROLLOUT_STARTED=1
mv -f "${compose_candidate}" "${COMPOSE_FILE}"
chmod 600 "${COMPOSE_FILE}"
mv -f "${candidate_env}" "${COMPOSE_ENV_FILE}"
chmod 600 "${COMPOSE_ENV_FILE}"
log "All preflight checks passed; applying digest-selected image"
compose up -d --no-build --force-recreate quiz-app

running_image_id="$(docker inspect fultons-quiz --format '{{.Image}}')"
selected_image_id="$(docker image inspect "${DEPLOY_IMAGE}" --format '{{.Id}}')"
if [ "${running_image_id}" != "${selected_image_id}" ]; then
  fail "Running image ID ${running_image_id:-unknown} does not match selected ${selected_image_id}."
fi
running_revision="$(docker inspect fultons-quiz --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
if [ "${running_revision}" != "${APP_COMMIT}" ]; then
  fail "Running revision ${running_revision:-unknown} does not match requested commit ${APP_COMMIT}."
fi
wait_for_health "Deployment"

DEPLOY_SUCCEEDED=1
trap - ERR INT TERM
rm -f "${candidate_env}" "${PREVIOUS_COMPOSE_FILE}" "${PREVIOUS_COMPOSE_ENV_FILE}"
log "Deployment succeeded with ${DEPLOY_IMAGE}; verified backup: ${BACKUP_DIR}"
log "Run backup_manager.py retention without --apply to review 30 daily / 12 monthly / 3 annual retention."
docker ps --filter name=fultons-quiz --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
