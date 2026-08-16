param(
  [string]$Target = "ste@192.168.0.15",
  [string]$KeyPath = "$env:USERPROFILE\.ssh\codex_fultons_ed25519",
  [int]$Port = 22
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $KeyPath)) {
  throw "SSH key not found: $KeyPath"
}

$remoteScript = @'
set -Eeuo pipefail

COMPOSE_FILE="/home/ste/fulton-web-app-deploy/compose.yaml"
COMPOSE_ENV_FILE="/home/ste/fulton-web-app-deploy/.env"

read_compose_path_setting() {
  python3 - "${1:?dotenv path required}" "${2:?key required}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
if not path.exists():
    raise SystemExit(0)
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

configured_env_file="$(read_compose_path_setting "$COMPOSE_ENV_FILE" "FULTONS_ENV_FILE")"
configured_data_dir="$(read_compose_path_setting "$COMPOSE_ENV_FILE" "FULTONS_HOST_DATA_DIR")"
ENV_FILE="${configured_env_file:-/srv/storage/appdata/fultons-quiz/app.env}"
APPDATA_DIR="${configured_data_dir:-/srv/storage/appdata/fultons-quiz}"

log() {
  printf '[fultons-restart] %s\n' "$*"
}

log "server=$(hostname) utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if [ ! -f "$COMPOSE_FILE" ]; then
  log "ERROR: compose file missing at $COMPOSE_FILE"
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  log "ERROR: env file missing at $ENV_FILE"
  exit 1
fi

if [ ! -f "$APPDATA_DIR/fultons.db" ]; then
  log "ERROR: database missing at $APPDATA_DIR/fultons.db"
  find "$APPDATA_DIR" -maxdepth 2 -type f -printf '%TY-%Tm-%Td %TH:%TM %s %p\n' 2>/dev/null | sort || true
  exit 1
fi

log "database preflight"
python3 - "$APPDATA_DIR/fultons.db" <<'PY'
import json
import os
import sqlite3
import sys

db_path = sys.argv[1]
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
        print(json.dumps({
            "dbPath": db_path,
            "size": os.path.getsize(db_path),
            "quickCheck": quick_check,
            "userCount": user_count,
        }, sort_keys=True))
        if quick_check != "ok":
            raise SystemExit("SQLite quick_check failed")
    finally:
        conn.close()
except sqlite3.Error as exc:
    raise SystemExit(f"SQLite startup preflight failed: {exc}") from exc
PY

log "storage mount"
findmnt -T "$APPDATA_DIR" -o TARGET,SOURCE,FSTYPE,OPTIONS

log "containers before restart"
docker ps --filter name=fultons-quiz --filter name=jellyfin --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' || true

CURRENT_IMAGE="$(docker inspect fultons-quiz --format '{{.Image}}')"
if [[ ! "$CURRENT_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  log "ERROR: current container does not expose an immutable image ID"
  exit 1
fi

log "recreating fultons-quiz from immutable existing image $CURRENT_IMAGE"
cd "$(dirname "$COMPOSE_FILE")"
export FULTONS_ENV_FILE="$ENV_FILE"
export FULTONS_HOST_DATA_DIR="$APPDATA_DIR"
export FULTONS_IMAGE="$CURRENT_IMAGE"
docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" up -d --force-recreate --no-build

RESTARTED_IMAGE="$(docker inspect fultons-quiz --format '{{.Image}}')"
if [ "$RESTARTED_IMAGE" != "$CURRENT_IMAGE" ]; then
  log "ERROR: restarted image $RESTARTED_IMAGE does not match $CURRENT_IMAGE"
  exit 1
fi

log "waiting for /api/health"
for attempt in $(seq 1 30); do
  if docker exec fultons-quiz python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=3)); raise SystemExit(0 if data.get('ok') else 1)" >/dev/null 2>&1; then
    log "health passed on attempt $attempt"
    break
  fi
  if [ "$attempt" = "30" ]; then
    log "ERROR: health check failed"
    docker logs --tail 120 fultons-quiz || true
    exit 1
  fi
  sleep 2
done

log "health payload"
docker exec fultons-quiz python -c "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=3)), sort_keys=True))"

log "database summary"
docker exec fultons-quiz python -c "import json,os,sqlite3; p='/app/data/fultons.db'; c=sqlite3.connect(p); tables=[r[0] for r in c.execute('select name from sqlite_master where type=\"table\" order by name')]; counts={t:c.execute('select count(*) from '+t).fetchone()[0] for t in tables}; print(json.dumps({'path':p,'size':os.path.getsize(p),'counts':counts}, sort_keys=True))"

log "retired endpoint compatibility check"
docker exec fultons-quiz python -c "import http.client; paths=('/api/history','/api/facts','/api/fact-image'); statuses={}; [(lambda c,p: (c.request('GET',p), statuses.__setitem__(p,c.getresponse().status), c.close()))(http.client.HTTPConnection('127.0.0.1',3000,timeout=3),p) for p in paths]; print('retired_api_statuses=' + str(statuses)); raise SystemExit(0 if all(v == 410 for v in statuses.values()) else 1)"

log "containers after restart"
docker ps --filter name=fultons-quiz --filter name=jellyfin --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

log "recent fultons logs"
docker logs --tail 40 fultons-quiz || true

log "done"
'@

$sshArgs = @(
  "-i", $KeyPath,
  "-p", "$Port",
  "-o", "BatchMode=yes",
  $Target,
  "bash", "-s"
)

Write-Host "[fultons-restart] target=$Target port=$Port"
$remoteScript | & ssh @sshArgs
exit $LASTEXITCODE
