#!/usr/bin/env bash
set -Eeuo pipefail

APP_COMMIT="${1:?Usage: homeserver-update.sh <commit-sha>}"
APP_REPO_URL="${APP_REPO_URL:-https://github.com/Steveystyles/Fulton-Web-App.git}"
SRC_DIR="${SRC_DIR:-${HOME}/fulton-web-app}"
COMPOSE_DIR="${COMPOSE_DIR:-${HOME}/fulton-web-app-deploy}"
DATA_DIR="${DATA_DIR:-/srv/storage/appdata/fultons-quiz}"
BACKUP_ROOT="${BACKUP_ROOT:-/srv/storage/backups}"
COMPOSE_FILE="${COMPOSE_DIR}/compose.yaml"

log() {
  printf '[fultons-deploy] %s\n' "$*"
}

if [ ! -d "${SRC_DIR}/.git" ]; then
  log "Cloning ${APP_REPO_URL} into ${SRC_DIR}"
  rm -rf "${SRC_DIR}"
  git clone "${APP_REPO_URL}" "${SRC_DIR}"
fi

log "Fetching latest git refs"
git -C "${SRC_DIR}" fetch --tags --prune origin
git -C "${SRC_DIR}" checkout --detach "${APP_COMMIT}"
git -C "${SRC_DIR}" reset --hard "${APP_COMMIT}"
git -C "${SRC_DIR}" clean -fdx

mkdir -p "${DATA_DIR}" "${BACKUP_ROOT}" "${COMPOSE_DIR}"

if [ -d "${DATA_DIR}" ]; then
  backup_dir="${BACKUP_ROOT}/fultons-quiz-$(date -u +%Y%m%d%H%M%S)"
  log "Backing up ${DATA_DIR} to ${backup_dir}"
  mkdir -p "${backup_dir}"
  cp -a "${DATA_DIR}/." "${backup_dir}/"
fi

cp "${SRC_DIR}/deploy/compose.yaml" "${COMPOSE_FILE}"

if docker ps -a --format '{{.Names}}' | grep -qx 'fultons-quiz'; then
  log "Removing existing fultons-quiz container"
  docker rm -f fultons-quiz
fi

log "Building and starting fultons-quiz"
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
