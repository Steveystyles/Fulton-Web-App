param(
  [string]$Target = "ste@192.168.0.15",
  [string]$KeyPath = "$env:USERPROFILE\.ssh\codex_fultons_ed25519",
  [int]$Port = 22,
  [string]$PublicHealthUrl = "https://fultons-quiz.co.uk/api/health",
  [switch]$ForceRestart
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host "[power-check] $Message"
}

function Write-WarnLine {
  param([string]$Message)
  Write-Host "[power-check] WARNING: $Message" -ForegroundColor Yellow
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $ScriptRoot "logs"
if (!(Test-Path -LiteralPath $LogDir)) {
  New-Item -ItemType Directory -Path $LogDir | Out-Null
}
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDir "power-outage-check-$Timestamp.log"

try {
  Start-Transcript -Path $LogPath -Append | Out-Null
} catch {
  Write-WarnLine "could not start transcript: $($_.Exception.Message)"
}

try {
  Write-Step "log=$LogPath"
  Write-Step "target=$Target port=$Port"

  try {
    if (!(Test-Path -LiteralPath $KeyPath)) {
      throw "SSH key not found: $KeyPath"
    }
  } catch [System.UnauthorizedAccessException] {
    Write-WarnLine "could not inspect SSH key path because access was denied; trying SSH anyway"
  }

  Write-Step "checking public health from this PC"
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $PublicHealthUrl -TimeoutSec 10
    $payload = $response.Content | ConvertFrom-Json
    if ($response.StatusCode -eq 200 -and $payload.ok -eq $true) {
      Write-Step "public health OK: $PublicHealthUrl"
    } else {
      Write-WarnLine "public health responded but did not report ok=true"
      Write-Host $response.Content
    }
  } catch {
    Write-WarnLine "public health check failed from this PC: $($_.Exception.Message)"
    Write-WarnLine "continuing with server-side checks over SSH"
  }

  $forceFlag = if ($ForceRestart.IsPresent) { "1" } else { "0" }

  $remoteScript = @'
set -Eeuo pipefail

FORCE_RESTART="${1:-0}"
PUBLIC_HEALTH_URL="${2:-https://fultons-quiz.co.uk/api/health}"
COMPOSE_FILE="/home/ste/fulton-web-app-deploy/compose.yaml"
COMPOSE_ENV_FILE="/home/ste/fulton-web-app-deploy/.env"

log() {
  printf '[power-check] %s\n' "$*"
}

warn() {
  printf '[power-check] WARNING: %s\n' "$*"
}

fail() {
  printf '[power-check] ERROR: %s\n' "$*" >&2
  exit 1
}

run_db_check() {
  python3 - "$DB_PATH" <<'PY'
import json
import os
import sqlite3
import sys

db_path = sys.argv[1]
conn = sqlite3.connect(db_path, timeout=10)
try:
    quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    counts = {}
    for table in (
        "users",
        "sessions",
        "daily_quiz_sets",
        "daily_quiz_questions",
        "daily_map_puzzles",
        "daily_map_levels",
    ):
        if table in tables:
            counts[table] = conn.execute(
                'SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"'
            ).fetchone()[0]
    result = {
        "dbPath": db_path,
        "size": os.path.getsize(db_path),
        "quickCheck": quick_check,
        "counts": counts,
    }
    print(json.dumps(result, sort_keys=True))
    if quick_check != "ok":
        raise SystemExit("SQLite quick_check failed")
    if counts.get("users", 0) < 1:
        raise SystemExit("users table is empty")
finally:
    conn.close()
PY
}

check_internal_health() {
  docker exec fultons-quiz python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=3)); print(json.dumps(data, sort_keys=True)); raise SystemExit(0 if data.get('ok') and data.get('storage', {}).get('ok') else 1)"
}

log "server=$(hostname) utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
log "uptime=$(uptime -p 2>/dev/null || true)"

log "recent boots"
last -x -n 8 || true

if [ -f "$COMPOSE_ENV_FILE" ]; then
  set -a
  . "$COMPOSE_ENV_FILE"
  set +a
else
  warn "compose env file missing at $COMPOSE_ENV_FILE; using deployment defaults"
fi

ENV_FILE="${FULTONS_ENV_FILE:-/srv/storage/appdata/fultons-quiz/app.env}"
APPDATA_DIR="${FULTONS_HOST_DATA_DIR:-/srv/storage/appdata/fultons-quiz}"
DB_PATH="$APPDATA_DIR/fultons.db"

[ -f "$COMPOSE_FILE" ] || fail "compose file missing at $COMPOSE_FILE"
[ -f "$ENV_FILE" ] || fail "env file missing at $ENV_FILE"
[ -d "$APPDATA_DIR" ] || fail "data directory missing at $APPDATA_DIR"
[ -f "$DB_PATH" ] || fail "database missing at $DB_PATH"

log "storage mount"
findmnt -T "$APPDATA_DIR" -o TARGET,SOURCE,FSTYPE,OPTIONS || warn "findmnt could not inspect $APPDATA_DIR"

log "database preflight"
run_db_check

log "docker daemon"
docker info >/dev/null || fail "Docker daemon is not reachable"

log "containers before fix"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' || true

NEEDS_RESTART=0
if [ "$FORCE_RESTART" = "1" ]; then
  warn "ForceRestart was requested"
  NEEDS_RESTART=1
fi

if ! docker inspect fultons-quiz >/dev/null 2>&1; then
  warn "fultons-quiz container is missing"
  NEEDS_RESTART=1
else
  STATE="$(docker inspect fultons-quiz --format '{{.State.Status}}')"
  HEALTH="$(docker inspect fultons-quiz --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')"
  RESTART_POLICY="$(docker inspect fultons-quiz --format '{{.HostConfig.RestartPolicy.Name}}')"
  STARTED_AT="$(docker inspect fultons-quiz --format '{{.State.StartedAt}}')"
  log "fultons-quiz state=$STATE health=$HEALTH restart=$RESTART_POLICY started=$STARTED_AT"
  if [ "$STATE" != "running" ] || [ "$HEALTH" = "unhealthy" ] || [ "$HEALTH" = "starting" ]; then
    NEEDS_RESTART=1
  fi
fi

if [ "$NEEDS_RESTART" = "0" ]; then
  log "internal health precheck"
  if ! check_internal_health; then
    warn "internal health failed before fix"
    NEEDS_RESTART=1
  fi
fi

if [ "$NEEDS_RESTART" = "1" ]; then
  log "recreating fultons-quiz with existing image"
  cd "$(dirname "$COMPOSE_FILE")"
  export FULTONS_ENV_FILE="$ENV_FILE"
  export FULTONS_HOST_DATA_DIR="$APPDATA_DIR"
  docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-build
else
  log "no Fulton restart needed"
fi

if docker inspect traefik >/dev/null 2>&1; then
  TRAEFIK_STATE="$(docker inspect traefik --format '{{.State.Status}}')"
  log "traefik state=$TRAEFIK_STATE"
  if [ "$TRAEFIK_STATE" != "running" ]; then
    warn "starting traefik"
    docker start traefik >/dev/null
  fi
else
  warn "traefik container was not found"
fi

log "waiting for internal health"
for attempt in $(seq 1 30); do
  if check_internal_health >/tmp/fultons-health.json 2>/tmp/fultons-health.err; then
    log "internal health passed on attempt $attempt"
    cat /tmp/fultons-health.json
    break
  fi
  if [ "$attempt" = "30" ]; then
    warn "internal health did not recover"
    cat /tmp/fultons-health.err 2>/dev/null || true
    docker logs --tail 120 fultons-quiz || true
    exit 1
  fi
  sleep 2
done

log "database postcheck"
run_db_check

log "public health from server"
if python3 - "$PUBLIC_HEALTH_URL" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
response = urllib.request.urlopen(url, timeout=10)
body = response.read().decode("utf-8", "replace")
print(response.status)
print(body)
data = json.loads(body)
raise SystemExit(0 if response.status == 200 and data.get("ok") else 1)
PY
then
  log "public health OK from server"
else
  warn "public health failed from server; check Traefik, DNS, router/NAT, or certificate renewal"
fi

log "homepage from server"
if python3 - "$PUBLIC_HEALTH_URL" <<'PY'
import sys
import urllib.request
from urllib.parse import urlparse

health_url = sys.argv[1]
parsed = urlparse(health_url)
base = f"{parsed.scheme}://{parsed.netloc}/"
response = urllib.request.urlopen(base, timeout=10)
head = response.read(120).decode("utf-8", "replace")
print(response.status)
print(head)
raise SystemExit(0 if response.status == 200 and "<!doctype html>" in head.lower() else 1)
PY
then
  log "homepage OK from server"
else
  warn "homepage check failed from server"
fi

log "recent kernel power/storage messages"
journalctl -k -b --no-pager -g 'thermal|overheat|critical|power|battery|acpi|mce|hardware error|oom|killed process|ext4|i/o error' -n 80 || true

log "recent Fulton logs"
docker logs --tail 60 fultons-quiz || true

log "containers after fix"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' || true

log "done"
'@

  $sshArgs = @(
    "-i", $KeyPath,
    "-p", "$Port",
    "-o", "BatchMode=yes",
    $Target,
    "bash", "-s", "--", $forceFlag, $PublicHealthUrl
  )

  Write-Step "running server-side recovery checks"
  $remoteScript | & ssh @sshArgs
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "server-side recovery checks failed with exit code $exitCode"
  }

  Write-Step "complete"
  Write-Step "saved log: $LogPath"
  exit 0
} catch {
  Write-Host "[power-check] ERROR: $($_.Exception.Message)" -ForegroundColor Red
  Write-Step "saved log: $LogPath"
  exit 1
} finally {
  try {
    Stop-Transcript | Out-Null
  } catch {
  }
}
