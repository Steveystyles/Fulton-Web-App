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
ENV_FILE="/srv/storage/appdata/fultons-quiz/app.env"
APPDATA_DIR="/srv/storage/appdata/fultons-quiz"

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

log "storage mount"
findmnt -T /srv/storage -o TARGET,SOURCE,FSTYPE,OPTIONS

log "containers before restart"
docker ps --filter name=fultons-quiz --filter name=jellyfin --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' || true

log "recreating fultons-quiz from existing image"
export FULTONS_ENV_FILE="$ENV_FILE"
docker compose -f "$COMPOSE_FILE" up -d --force-recreate --no-build

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

log "protected endpoint check"
docker exec fultons-quiz python -c "import http.client; conn=http.client.HTTPConnection('127.0.0.1',3000,timeout=3); conn.request('POST','/api/fact-image', body='{}', headers={'Content-Type':'application/json'}); print('fact_image_no_cookie_status=' + str(conn.getresponse().status)); conn.close()"

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
