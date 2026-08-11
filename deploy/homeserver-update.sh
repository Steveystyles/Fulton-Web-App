#!/usr/bin/env bash
set -Eeuo pipefail

APP_COMMIT="${1:?Usage: homeserver-update.sh <commit-sha>}"
APP_REPO_URL="${APP_REPO_URL:-https://github.com/Steveystyles/Fulton-Web-App.git}"
SRC_DIR="${SRC_DIR:-${HOME}/fulton-web-app}"
COMPOSE_DIR="${COMPOSE_DIR:-${HOME}/fulton-web-app-deploy}"
COMPOSE_ENV_FILE="${COMPOSE_ENV_FILE:-${COMPOSE_DIR}/.env}"
if [ -f "${COMPOSE_ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${COMPOSE_ENV_FILE}"
  set +a
fi
DATA_DIR="${DATA_DIR:-${FULTONS_HOST_DATA_DIR:-/srv/storage/appdata/fultons-quiz}}"
BACKUP_ROOT="${BACKUP_ROOT:-/srv/storage/backups}"
COMPOSE_FILE="${COMPOSE_DIR}/compose.yaml"
ENV_FILE="${ENV_FILE:-${FULTONS_ENV_FILE:-${DATA_DIR}/app.env}}"

log() {
  printf '[fultons-deploy] %s\n' "$*"
}

resolve_abs_path() {
  python3 - "${1:?path required}" <<'PY'
import os
import sys

print(os.path.realpath(sys.argv[1]))
PY
}

upsert_env_var() {
  local file="${1:?file required}"
  local key="${2:?key required}"
  local value="${3-}"
  python3 - "${file}" "${key}" "${value}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
prefix = f"{key}="
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
updated = False
result = []
for line in lines:
    if line.startswith(prefix):
        result.append(prefix + value)
        updated = True
    else:
        result.append(line)
if not updated:
    result.append(prefix + value)
path.write_text("\n".join(result).rstrip("\n") + "\n", encoding="utf-8")
PY
}

if [ -d "${SRC_DIR}/.git" ]; then
  log "Fetching latest git refs"
  git -C "${SRC_DIR}" fetch --tags --prune origin
  git -C "${SRC_DIR}" checkout --detach "${APP_COMMIT}"
  git -C "${SRC_DIR}" reset --hard "${APP_COMMIT}"
  git -C "${SRC_DIR}" clean -fdx
elif [ -f "${SRC_DIR}/deploy/compose.yaml" ]; then
  log "Using unpacked source at ${SRC_DIR}"
else
  log "Cloning ${APP_REPO_URL} into ${SRC_DIR}"
  rm -rf "${SRC_DIR}"
  git clone "${APP_REPO_URL}" "${SRC_DIR}"
  git -C "${SRC_DIR}" checkout --detach "${APP_COMMIT}"
fi

SRC_DIR="$(resolve_abs_path "${SRC_DIR}")"
DATA_DIR="$(resolve_abs_path "${DATA_DIR}")"
BACKUP_ROOT="$(resolve_abs_path "${BACKUP_ROOT}")"
COMPOSE_DIR="$(resolve_abs_path "${COMPOSE_DIR}")"
ENV_FILE="$(resolve_abs_path "${ENV_FILE}")"
COMPOSE_FILE="${COMPOSE_DIR}/compose.yaml"
COMPOSE_ENV_FILE="${COMPOSE_DIR}/.env"

mkdir -p "${DATA_DIR}" "${BACKUP_ROOT}" "${COMPOSE_DIR}" "$(dirname "${ENV_FILE}")"

if [ ! -f "${ENV_FILE}" ]; then
  if docker ps -a --format '{{.Names}}' | grep -qx 'fultons-quiz'; then
    log "Refusing to replace an existing deployment with a missing environment file: ${ENV_FILE}"
    log "Recover the private environment and correct ${COMPOSE_ENV_FILE} before retrying."
    exit 1
  fi
  log "Creating private app env file at ${ENV_FILE}"
  cat > "${ENV_FILE}" <<'EOF'
# Private container environment for Fulton Web App.
# Keep this file out of Git.
FULTONS_NEWS_MONITOR_KEY=
FULTONS_NEWS_MONITOR_INTERVAL_SEC=600
FULTONS_WORD_DEFINITION_TIMEOUT_SEC=5
FULTONS_COOKIE_SECURE=1
FULTONS_SEED_DEMO_USERS=0
FULTONS_ALLOWED_ORIGINS=https://fultons-quiz.co.uk,https://www.fultons-quiz.co.uk
FULTONS_MIN_PASSWORD_LENGTH=12
FULTONS_LOGIN_MAX_ATTEMPTS=5
FULTONS_LOGIN_WINDOW_SECONDS=300
FULTONS_LOGIN_BACKOFF_SECONDS=60
EOF
fi
chmod 600 "${ENV_FILE}"

ensure_env_var() {
  local key="${1:?key required}"
  local value="${2:-}"
  if ! grep -q "^${key}=" "${ENV_FILE}"; then
    printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"
  fi
}

migrate_env_var_value() {
  local key="${1:?key required}"
  local old_value="${2:-}"
  local new_value="${3:-}"
  if grep -q "^${key}=${old_value}$" "${ENV_FILE}"; then
    python3 - "${ENV_FILE}" "${key}" "${new_value}" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
key = sys.argv[2]
new_value = sys.argv[3]
prefix = f"{key}="

lines = env_path.read_text(encoding="utf-8").splitlines()
env_path.write_text(
    "\n".join((f"{prefix}{new_value}" if line.startswith(prefix) else line) for line in lines) + "\n",
    encoding="utf-8",
)
PY
  fi
}

default_env_var_when_blank() {
  local key="${1:?key required}"
  local value="${2:-}"
  python3 - "${ENV_FILE}" "${key}" "${value}" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
prefix = f"{key}="

lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
updated = False
for index, line in enumerate(lines):
    if line.startswith(prefix):
        if not line[len(prefix):].strip():
            lines[index] = prefix + value
        updated = True
        break
if not updated:
    lines.append(prefix + value)
env_path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
PY
}

ensure_env_var "FULTONS_COOKIE_SECURE" "1"
ensure_env_var "FULTONS_SEED_DEMO_USERS" "0"
ensure_env_var "FULTONS_ALLOWED_ORIGINS" "https://fultons-quiz.co.uk,https://www.fultons-quiz.co.uk"
ensure_env_var "FULTONS_MIN_PASSWORD_LENGTH" "12"
ensure_env_var "FULTONS_LOGIN_MAX_ATTEMPTS" "5"
ensure_env_var "FULTONS_LOGIN_WINDOW_SECONDS" "300"
ensure_env_var "FULTONS_LOGIN_BACKOFF_SECONDS" "60"
ensure_env_var "FULTONS_NEWS_MONITOR_INTERVAL_SEC" "600"
migrate_env_var_value "FULTONS_NEWS_MONITOR_INTERVAL_SEC" "3600" "600"
ensure_env_var "FULTONS_WORD_DEFINITION_TIMEOUT_SEC" "5"
ensure_env_var "FULTONS_EXPECT_DATA_DIR" "/app/data"
ensure_env_var "FULTONS_REQUIRE_EXISTING_DB" "1"
ensure_env_var "FULTONS_MIN_DB_USERS" "1"
ensure_env_var "FULTONS_DAILY_QUIZ_SCHEDULER_ENABLED" "1"
ensure_env_var "FULTONS_DAILY_QUIZ_SCHEDULER_HOUR" "0"
ensure_env_var "FULTONS_DAILY_QUIZ_SCHEDULER_MINUTE" "5"
ensure_env_var "FULTONS_DAILY_QUIZ_TRANSIENT_RETRY_INTERVAL_SEC" "3600"
ensure_env_var "FULTONS_DAILY_QUIZ_RECOVERY_HOUR" "20"
ensure_env_var "FULTONS_DAILY_MAP_GAME_SCHEDULER_ENABLED" "1"
migrate_env_var_value "FULTONS_DAILY_MAP_GAME_SCHEDULER_ENABLED" "0" "1"
ensure_env_var "FULTONS_DAILY_MAP_GAME_SCHEDULER_HOUR" "0"
ensure_env_var "FULTONS_DAILY_MAP_GAME_SCHEDULER_MINUTE" "0"
migrate_env_var_value "FULTONS_DAILY_MAP_GAME_SCHEDULER_MINUTE" "2" "0"
ensure_env_var "FULTONS_DAILY_MAP_PREPARE_DAYS_AHEAD" "2"
ensure_env_var "FULTONS_DAILY_MAP_GAME_RETRY_INTERVAL_SEC" "300"
ensure_env_var "FULTONS_DAILY_MAP_TRANSIENT_RETRY_INTERVAL_SEC" "3600"
ensure_env_var "FULTONS_DAILY_MAP_AI_GENERATION_ENABLED" "1"
ensure_env_var "FULTONS_DAILY_MAP_AI_SHORTLIST_LIMIT" "24"
ensure_env_var "FULTONS_DAILY_MAP_AI_MAX_CLUE_ATTEMPTS" "7"
ensure_env_var "FULTONS_DAILY_MAP_AI_DISCOVER_COUNT" "4"
ensure_env_var "FULTONS_DAILY_MAP_AI_DISCOVERY_ATTEMPTS" "2"
ensure_env_var "FULTONS_DAILY_MAP_AI_GENERATION_ROUNDS" "3"
ensure_env_var "FULTONS_DAILY_MAP_STADIUM_LAUNCH_DATE" "2026-08-05"
migrate_env_var_value "FULTONS_DAILY_MAP_STADIUM_LAUNCH_DATE" "2026-08-04" "2026-08-05"
ensure_env_var "FULTONS_DAILY_MAP_STADIUM_LAUNCH_ROUNDS" "3"
ensure_env_var "FULTONS_MAP_PROMO_CAMPAIGN_ID" "daily-map-launch-2026-08-04"
ensure_env_var "FULTONS_MAP_PROMO_AVAILABLE_DATE" "2026-08-04"
ensure_env_var "VITE_FULTONS_MAP_TILE_URL" ""
ensure_env_var "VITE_FULTONS_MAP_TILE_URL_CLEAR_BASE" ""
ensure_env_var "VITE_FULTONS_MAP_TILE_URL_NO_LABELS" ""
ensure_env_var "VITE_FULTONS_MAP_TILE_ATTRIBUTION" ""
ensure_env_var "AI_PROVIDER" "gemini"
ensure_env_var "AI_GENERATOR_MODEL" "gemini-3.5-flash"
ensure_env_var "AI_CRITIC_MODEL" "gemini-3.1-flash-lite"
ensure_env_var "GEMINI_API_KEY" ""
ensure_env_var "MAP_CLUE_GEMINI_API_KEY" ""
ensure_env_var "MAP_CLUE_GENERATOR_MODEL" "gemini-3.1-flash-lite"
ensure_env_var "MAP_CLUE_CRITIC_MODEL" "gemini-3.1-flash-lite"
ensure_env_var "MAP_CLUE_MAX_ATTEMPTS" "6"
ensure_env_var "MAP_CLUE_REQUIRE_AI_CRITIC" "1"
ensure_env_var "AI_BASE_URL" ""
ensure_env_var "AI_API_KEY" ""
ensure_env_var "AI_FALLBACK_PROVIDER" "gemini"
ensure_env_var "AI_FALLBACK_GENERATOR_MODEL" "gemini-3.1-flash-lite"
ensure_env_var "AI_FALLBACK_CRITIC_MODEL" "gemini-3.1-flash-lite"
ensure_env_var "AI_FALLBACK_API_KEY" ""
ensure_env_var "AI_FALLBACK_BASE_URL" ""
ensure_env_var "AI_FALLBACK2_PROVIDER" "openrouter"
ensure_env_var "AI_FALLBACK2_GENERATOR_MODEL" "openrouter/free"
ensure_env_var "AI_FALLBACK2_CRITIC_MODEL" "openrouter/free"
ensure_env_var "AI_FALLBACK_GEMINI_API_KEY" ""
ensure_env_var "AI_FALLBACK2_GEMINI_API_KEY" ""
ensure_env_var "AI_FALLBACK2_API_KEY" ""
ensure_env_var "AI_FALLBACK2_BASE_URL" "https://openrouter.ai/api/v1"
ensure_env_var "AI_TIMEOUT_SEC" "90"
ensure_env_var "AI_REQUEST_DELAY_SEC" "12"
ensure_env_var "AI_TRANSIENT_RETRIES" "3"
ensure_env_var "MAX_ATTEMPTS_PER_SLOT" "15"
ensure_env_var "QUESTION_HISTORY_DAYS" "90"
ensure_env_var "QUIZ_CANDIDATE_PIPELINE_ENABLED" "0"
ensure_env_var "QUIZ_ANSWER_EMBARGO_DAYS" "45"
ensure_env_var "QUIZ_RECOVERY_ANSWER_EMBARGO_DAYS" "30"
ensure_env_var "QUIZ_QUESTION_SIMILARITY_DAYS" "180"
ensure_env_var "QUIZ_CANDIDATE_BATCH_SIZE" "8"
ensure_env_var "QUIZ_CANDIDATE_BATCHES_PER_SLOT" "3"
ensure_env_var "QUIZ_EVIDENCE_REQUIRED" "1"
ensure_env_var "QUIZ_EVIDENCE_SEARCH_TIMEOUT_SEC" "90"
ensure_env_var "QUIZ_EVIDENCE_MAX_RESULTS" "8"
ensure_env_var "QUIZ_EVIDENCE_OPENROUTER_API_KEY" ""
ensure_env_var "QUIZ_EVIDENCE_OPENROUTER_BASE_URL" "https://openrouter.ai/api/v1"
ensure_env_var "QUIZ_EVIDENCE_OPENROUTER_MODEL" "openrouter/free"
ensure_env_var "QUIZ_LEARNING_PROFILE_PATH" ""
ensure_env_var "INTERNAL_QUIZ_TOKEN" ""
migrate_env_var_value "AI_FALLBACK_GENERATOR_MODEL" "gemini-2.5-flash" "gemini-3.1-flash-lite"
migrate_env_var_value "AI_FALLBACK_CRITIC_MODEL" "gemini-2.5-flash-lite" "gemini-3.1-flash-lite"
migrate_env_var_value "AI_FALLBACK_GENERATOR_MODEL" "openai/gpt-oss-120b:free" "google/gemma-4-26b-a4b-it:free"
migrate_env_var_value "AI_FALLBACK_CRITIC_MODEL" "openai/gpt-oss-120b:free" "openrouter/free"
migrate_env_var_value "AI_FALLBACK2_PROVIDER" "gemini" "openrouter"
migrate_env_var_value "AI_FALLBACK2_GENERATOR_MODEL" "gemini-3.1-flash-lite" "openrouter/free"
migrate_env_var_value "AI_FALLBACK2_CRITIC_MODEL" "gemini-3.1-flash-lite" "openrouter/free"
migrate_env_var_value "AI_FALLBACK2_GENERATOR_MODEL" "openai/gpt-oss-120b:free" "openrouter/free"
migrate_env_var_value "AI_FALLBACK2_CRITIC_MODEL" "openai/gpt-oss-120b:free" "openrouter/free"
migrate_env_var_value "AI_FALLBACK2_GENERATOR_MODEL" "gemini-2.0-flash" "openrouter/free"
migrate_env_var_value "AI_FALLBACK2_CRITIC_MODEL" "gemini-2.0-flash-lite" "openrouter/free"
default_env_var_when_blank "AI_FALLBACK_PROVIDER" "gemini"
default_env_var_when_blank "AI_FALLBACK_GENERATOR_MODEL" "gemini-3.1-flash-lite"
default_env_var_when_blank "AI_FALLBACK_CRITIC_MODEL" "gemini-3.1-flash-lite"
default_env_var_when_blank "AI_FALLBACK2_PROVIDER" "openrouter"
default_env_var_when_blank "AI_FALLBACK2_GENERATOR_MODEL" "openrouter/free"
default_env_var_when_blank "AI_FALLBACK2_CRITIC_MODEL" "openrouter/free"
default_env_var_when_blank "AI_FALLBACK2_BASE_URL" "https://openrouter.ai/api/v1"

if [ -d "${DATA_DIR}" ]; then
  backup_dir="${BACKUP_ROOT}/fultons-quiz-$(date -u +%Y%m%d%H%M%S)"
  log "Backing up ${DATA_DIR} to ${backup_dir}"
  mkdir -p "${backup_dir}"
  tar -C "${DATA_DIR}" --exclude='./localai' -cf - . | tar -C "${backup_dir}" -xf -
fi

log "Checking runtime database before restart"
python3 - "${DATA_DIR}/fultons.db" <<'PY'
import json
import os
import sqlite3
import sys

db_path = sys.argv[1]
if not os.path.exists(db_path):
    print(json.dumps({"dbPath": db_path, "exists": False}))
    raise SystemExit(0)

try:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
        user_table = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()[0]
        user_count = None
        if user_table:
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        payload = {
            "dbPath": db_path,
            "exists": True,
            "size": os.path.getsize(db_path),
            "quickCheck": quick_check,
            "userCount": user_count,
        }
        print(json.dumps(payload, sort_keys=True))
        if quick_check != "ok":
            raise SystemExit("SQLite quick_check failed")
    finally:
        conn.close()
except sqlite3.Error as exc:
    raise SystemExit(f"SQLite startup preflight failed: {exc}") from exc
PY

cp "${SRC_DIR}/deploy/compose.yaml" "${COMPOSE_FILE}"
upsert_env_var "${COMPOSE_ENV_FILE}" "FULTONS_SRC_DIR" "${SRC_DIR}"
upsert_env_var "${COMPOSE_ENV_FILE}" "FULTONS_ENV_FILE" "${ENV_FILE}"
upsert_env_var "${COMPOSE_ENV_FILE}" "FULTONS_HOST_DATA_DIR" "${DATA_DIR}"
upsert_env_var "${COMPOSE_ENV_FILE}" "FULTONS_IMAGE" "local/fulton-web-app:${APP_COMMIT}"
export FULTONS_IMAGE="local/fulton-web-app:${APP_COMMIT}"
chmod 600 "${COMPOSE_ENV_FILE}"

log "Normalizing data ownership"
docker run --rm -v "${DATA_DIR}:/data" alpine:3.22 sh -c \
  'find /data -mindepth 1 -maxdepth 1 ! -name localai -exec chown -R 1000:1000 {} +'

rollback_tag=""
if docker ps -a --format '{{.Names}}' | grep -qx 'fultons-quiz'; then
  previous_image_id="$(docker inspect fultons-quiz --format '{{.Image}}')"
  rollback_tag="local/fulton-web-app:rollback-$(date -u +%Y%m%d%H%M%S)"
  docker tag "${previous_image_id}" "${rollback_tag}"
  log "Preserved current image as ${rollback_tag}"
fi

log "Building local/fulton-web-app:${APP_COMMIT} while production remains online"
docker build \
  --pull \
  --build-arg "FULTONS_BUILD_COMMIT=${APP_COMMIT}" \
  --build-arg "FULTONS_BUILD_SOURCE=${SRC_DIR}" \
  -t "local/fulton-web-app:${APP_COMMIT}" \
  "${SRC_DIR}"
docker tag "local/fulton-web-app:${APP_COMMIT}" local/fulton-web-app:latest

if [ "${IMPORT_MAP_LAUNCH_ROUND:-0}" = "1" ]; then
  log "Validating the packaged launch round against the production database"
  docker run --rm \
    -v "${DATA_DIR}:/app/data" \
    --entrypoint python \
    "local/fulton-web-app:${APP_COMMIT}" \
    -m tools.map_launch_round import \
    --db /app/data/fultons.db \
    --input /app/map-launch-round/map-launch-round-2026-08-04.json \
    --dry-run

  log "Publishing the validated launch round before application startup"
  docker run --rm \
    -v "${DATA_DIR}:/app/data" \
    --entrypoint python \
    "local/fulton-web-app:${APP_COMMIT}" \
    -m tools.map_launch_round import \
    --db /app/data/fultons.db \
    --input /app/map-launch-round/map-launch-round-2026-08-04.json
fi

if docker ps -a --format '{{.Names}}' | grep -qx 'fultons-quiz'; then
  log "Replacing existing fultons-quiz container after successful build"
  docker rm -f fultons-quiz
fi

log "Starting fultons-quiz"
export FULTONS_SRC_DIR="${SRC_DIR}"
export FULTONS_ENV_FILE="${ENV_FILE}"
export FULTONS_HOST_DATA_DIR="${DATA_DIR}"
cd "${COMPOSE_DIR}"
docker compose -f "${COMPOSE_FILE}" up -d --no-build

log "Verifying running container revision"
running_revision="$(docker inspect fultons-quiz --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
if [ "${running_revision}" != "${APP_COMMIT}" ]; then
  log "Running revision ${running_revision:-unknown} does not match expected ${APP_COMMIT}"
  docker logs --tail 80 fultons-quiz || true
  exit 1
fi

log "Waiting for health endpoint"
for attempt in $(seq 1 30); do
  if docker exec fultons-quiz python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=3)); raise SystemExit(0 if data.get('ok') else 1)" >/dev/null 2>&1; then
    log "Health check passed"
    docker ps --filter name=fultons-quiz --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
    exit 0
  fi
  sleep 2
done

log "Health check failed"
docker logs --tail 80 fultons-quiz || true
if [ -n "${rollback_tag}" ]; then
  log "Rolling back to ${rollback_tag}"
  upsert_env_var "${COMPOSE_ENV_FILE}" "FULTONS_IMAGE" "${rollback_tag}"
  export FULTONS_IMAGE="${rollback_tag}"
  docker rm -f fultons-quiz >/dev/null 2>&1 || true
  docker compose -f "${COMPOSE_FILE}" up -d --no-build
fi
exit 1
