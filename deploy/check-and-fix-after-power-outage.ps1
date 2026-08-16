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

  $healthUri = $null
  if (!( [Uri]::TryCreate($PublicHealthUrl, [UriKind]::Absolute, [ref]$healthUri) ) -or
      $healthUri.Scheme -notin @("http", "https") -or
      ![string]::IsNullOrEmpty($healthUri.UserInfo)) {
    throw "PublicHealthUrl must be an absolute HTTP(S) URL without user information"
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
  $healthUrlBase64 = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes($PublicHealthUrl)
  )

  $remoteScript = @'
set -Eeuo pipefail

FORCE_RESTART="${1:-0}"
PUBLIC_HEALTH_URL="$(python3 - "${2:-}" <<'PY'
import base64
import sys

try:
    value = base64.b64decode(sys.argv[1], validate=True).decode("utf-8")
except (ValueError, UnicodeError) as error:
    raise SystemExit(f"invalid encoded public health URL: {error}") from error
if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
    raise SystemExit("invalid public health URL")
print(value)
PY
)"
COMPOSE_FILE="/home/ste/fulton-web-app-deploy/compose.yaml"
COMPOSE_ENV_FILE="/home/ste/fulton-web-app-deploy/.env"
CANONICAL_SOURCE="https://github.com/Steveystyles/Fulton-Web-App.git"
HEALTH_OUTPUT=""
HEALTH_ERROR=""

cleanup() {
  if [ -n "${HEALTH_OUTPUT}" ]; then
    rm -f -- "${HEALTH_OUTPUT}"
  fi
  if [ -n "${HEALTH_ERROR}" ]; then
    rm -f -- "${HEALTH_ERROR}"
  fi
}

trap cleanup EXIT

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

read_compose_setting() {
  python3 - "${COMPOSE_ENV_FILE}" "${1:?key required}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
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
if len(found) != 1:
    raise SystemExit(f"compose dotenv must contain exactly one {key}")
print(found[0])
PY
}

run_db_check() {
  python3 - "$DB_PATH" <<'PY'
import json
import os
import sqlite3
import sys
from pathlib import Path

db_path = sys.argv[1]
database = Path(db_path)
if database.is_symlink() or not database.is_file():
    raise SystemExit(f"database is missing or unsafe: {db_path}")
conn = sqlite3.connect(
    f"{database.resolve(strict=True).as_uri()}?mode=ro",
    uri=True,
    timeout=10,
)
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

[ -f "$COMPOSE_FILE" ] || fail "compose file missing at $COMPOSE_FILE"
[ ! -L "$COMPOSE_ENV_FILE" ] && [ -f "$COMPOSE_ENV_FILE" ] || fail \
  "compose env file is missing or unsafe at $COMPOSE_ENV_FILE"

ENV_FILE="$(read_compose_setting FULTONS_ENV_FILE)"
APPDATA_DIR="$(read_compose_setting FULTONS_HOST_DATA_DIR)"
CONFIGURED_IMAGE="$(read_compose_setting FULTONS_IMAGE)"
[[ "$ENV_FILE" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "configured application env path is unsafe"
[[ "$APPDATA_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "configured appdata path is unsafe"
DB_PATH="$APPDATA_DIR/fultons.db"

[ ! -L "$ENV_FILE" ] && [ -f "$ENV_FILE" ] || fail "env file is missing or unsafe at $ENV_FILE"
[ -d "$APPDATA_DIR" ] || fail "data directory missing at $APPDATA_DIR"
[ ! -L "$DB_PATH" ] && [ -f "$DB_PATH" ] || fail "database is missing or unsafe at $DB_PATH"

log "storage mount"
findmnt -T "$APPDATA_DIR" -o TARGET,SOURCE,FSTYPE,OPTIONS || warn "findmnt could not inspect $APPDATA_DIR"

log "database preflight"
run_db_check

log "docker daemon"
docker info >/dev/null || fail "Docker daemon is not reachable"
if [[ ! "$CONFIGURED_IMAGE" =~ ^ghcr\.io/steveystyles/fulton-web-app@sha256:[0-9a-f]{64}$ ]] && \
   [[ ! "$CONFIGURED_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  fail "recovery requires an immutable canonical digest or local image ID in the compose dotenv"
fi
docker image inspect "$CONFIGURED_IMAGE" >/dev/null 2>&1 || fail \
  "configured immutable recovery image is not available locally; use the signed updater to fetch releases"
CONFIGURED_IMAGE_ID="$(docker image inspect "$CONFIGURED_IMAGE" --format '{{.Id}}')"
[[ "$CONFIGURED_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || fail \
  "configured recovery image did not resolve to an immutable local ID"

log "containers before fix"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' || true

NEEDS_RESTART=0
if [ "$FORCE_RESTART" = "1" ]; then
  warn "ForceRestart was requested"
  NEEDS_RESTART=1
fi

RECOVERY_IMAGE=""
EXPECTED_IMAGE_ID=""
if ! docker inspect fultons-quiz >/dev/null 2>&1; then
  warn "fultons-quiz container is missing"
  NEEDS_RESTART=1
  RECOVERY_IMAGE="$CONFIGURED_IMAGE"
else
  RECOVERY_IMAGE="$(docker inspect fultons-quiz --format '{{.Image}}')"
  [[ "$RECOVERY_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]] || fail \
    "existing container did not expose an immutable image ID"
  [ "$RECOVERY_IMAGE" = "$CONFIGURED_IMAGE_ID" ] || fail \
    "running container image does not match the immutable compose selection; use the signed updater"
  STATE="$(docker inspect fultons-quiz --format '{{.State.Status}}')"
  HEALTH="$(docker inspect fultons-quiz --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')"
  RESTART_POLICY="$(docker inspect fultons-quiz --format '{{.HostConfig.RestartPolicy.Name}}')"
  STARTED_AT="$(docker inspect fultons-quiz --format '{{.State.StartedAt}}')"
  log "fultons-quiz state=$STATE health=$HEALTH restart=$RESTART_POLICY started=$STARTED_AT"
  if [ "$STATE" != "running" ] || [ "$HEALTH" = "unhealthy" ] || [ "$HEALTH" = "starting" ]; then
    NEEDS_RESTART=1
  fi
fi
EXPECTED_IMAGE_ID="$(docker image inspect "$RECOVERY_IMAGE" --format '{{.Id}}')"
[[ "$EXPECTED_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || fail \
  "could not resolve the immutable recovery image ID"
IMAGE_SOURCE="$(docker image inspect "$RECOVERY_IMAGE" --format '{{ index .Config.Labels "org.opencontainers.image.source" }}')"
IMAGE_REVISION="$(docker image inspect "$RECOVERY_IMAGE" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
[ "$IMAGE_SOURCE" = "$CANONICAL_SOURCE" ] || fail "recovery image has a non-canonical OCI source label"
[[ "$IMAGE_REVISION" =~ ^[0-9a-f]{40}$ ]] || fail "recovery image has an invalid OCI revision label"

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
  export FULTONS_IMAGE="$RECOVERY_IMAGE"
  docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" config --quiet
  docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" \
    up -d --force-recreate --no-build quiz-app
  RESTARTED_IMAGE="$(docker inspect fultons-quiz --format '{{.Image}}')"
  [ "$RESTARTED_IMAGE" = "$EXPECTED_IMAGE_ID" ] || fail \
    "restarted image $RESTARTED_IMAGE does not match selected $EXPECTED_IMAGE_ID"
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
HEALTH_OUTPUT="$(mktemp /tmp/fultons-health.XXXXXX)"
HEALTH_ERROR="$(mktemp /tmp/fultons-health-error.XXXXXX)"
for attempt in $(seq 1 30); do
  if check_internal_health >"$HEALTH_OUTPUT" 2>"$HEALTH_ERROR"; then
    log "internal health passed on attempt $attempt"
    cat "$HEALTH_OUTPUT"
    break
  fi
  if [ "$attempt" = "30" ]; then
    warn "internal health did not recover"
    cat "$HEALTH_ERROR" 2>/dev/null || true
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
    "bash", "-s", "--", $forceFlag, $healthUrlBase64
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
