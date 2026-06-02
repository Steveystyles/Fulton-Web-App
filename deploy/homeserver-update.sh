#!/usr/bin/env bash
set -Eeuo pipefail

APP_COMMIT="${1:?Usage: homeserver-update.sh <commit-sha>}"
APP_REPO_URL="${APP_REPO_URL:-https://github.com/Steveystyles/Fulton-Web-App.git}"
SRC_DIR="${SRC_DIR:-${HOME}/fulton-web-app}"
COMPOSE_DIR="${COMPOSE_DIR:-${HOME}/fulton-web-app-deploy}"
DATA_DIR="${DATA_DIR:-/srv/storage/appdata/fultons-quiz}"
BACKUP_ROOT="${BACKUP_ROOT:-/srv/storage/backups}"
COMPOSE_FILE="${COMPOSE_DIR}/compose.yaml"
ENV_FILE="${ENV_FILE:-${DATA_DIR}/app.env}"

log() {
  printf '[fultons-deploy] %s\n' "$*"
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

mkdir -p "${DATA_DIR}" "${BACKUP_ROOT}" "${COMPOSE_DIR}"

if [ ! -f "${ENV_FILE}" ]; then
  log "Creating private app env file at ${ENV_FILE}"
  cat > "${ENV_FILE}" <<'EOF'
# Private container environment for Fulton Web App.
# Keep this file out of Git.
FULTONS_NEWS_MONITOR_KEY=
FULTONS_NEWS_MONITOR_INTERVAL_SEC=3600
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

ensure_env_var "FULTONS_COOKIE_SECURE" "1"
ensure_env_var "FULTONS_SEED_DEMO_USERS" "0"
ensure_env_var "FULTONS_ALLOWED_ORIGINS" "https://fultons-quiz.co.uk,https://www.fultons-quiz.co.uk"
ensure_env_var "FULTONS_MIN_PASSWORD_LENGTH" "12"
ensure_env_var "FULTONS_LOGIN_MAX_ATTEMPTS" "5"
ensure_env_var "FULTONS_LOGIN_WINDOW_SECONDS" "300"
ensure_env_var "FULTONS_LOGIN_BACKOFF_SECONDS" "60"
ensure_env_var "FULTONS_NEWS_MONITOR_INTERVAL_SEC" "3600"
ensure_env_var "FULTONS_WORD_DEFINITION_TIMEOUT_SEC" "5"
ensure_env_var "FULTONS_EXPECT_DATA_DIR" "/app/data"
ensure_env_var "FULTONS_REQUIRE_EXISTING_DB" "1"
ensure_env_var "FULTONS_MIN_DB_USERS" "1"
ensure_env_var "FULTONS_DAILY_QUIZ_SCHEDULER_ENABLED" "1"
ensure_env_var "FULTONS_DAILY_QUIZ_SCHEDULER_HOUR" "0"
ensure_env_var "FULTONS_DAILY_QUIZ_SCHEDULER_MINUTE" "5"
ensure_env_var "AI_PROVIDER" "gemini"
ensure_env_var "AI_GENERATOR_MODEL" "gemini-3.5-flash"
ensure_env_var "AI_CRITIC_MODEL" "gemini-3.1-flash-lite"
ensure_env_var "GEMINI_API_KEY" ""
ensure_env_var "AI_BASE_URL" ""
ensure_env_var "AI_API_KEY" ""
ensure_env_var "AI_TIMEOUT_SEC" "90"
ensure_env_var "AI_REQUEST_DELAY_SEC" "12"
ensure_env_var "AI_TRANSIENT_RETRIES" "3"
ensure_env_var "MAX_ATTEMPTS_PER_SLOT" "15"
ensure_env_var "QUESTION_HISTORY_DAYS" "90"
ensure_env_var "INTERNAL_QUIZ_TOKEN" ""

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

log "Normalizing data ownership"
docker run --rm -v "${DATA_DIR}:/data" alpine:3.22 sh -c \
  'find /data -mindepth 1 -maxdepth 1 ! -name localai -exec chown -R 1000:1000 {} +'

if docker ps -a --format '{{.Names}}' | grep -qx 'fultons-quiz'; then
  log "Removing existing fultons-quiz container"
  docker rm -f fultons-quiz
fi

log "Building and starting fultons-quiz"
export FULTONS_SRC_DIR="${SRC_DIR}"
export FULTONS_ENV_FILE="${ENV_FILE}"
docker compose -f "${COMPOSE_FILE}" up -d --build

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
exit 1
