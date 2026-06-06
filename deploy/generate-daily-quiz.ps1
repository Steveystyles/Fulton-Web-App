param(
  [string]$Date = (Get-Date).AddDays(1).ToString("yyyy-MM-dd"),
  [switch]$Force,
  [string]$Target = "ste@192.168.0.15",
  [string]$KeyPath = "$env:USERPROFILE\.ssh\codex_fultons_ed25519",
  [int]$Port = 22
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $KeyPath)) {
  throw "SSH key not found: $KeyPath"
}

if ($Date -notmatch "^\d{4}-\d{2}-\d{2}$") {
  throw "Date must use YYYY-MM-DD format."
}
[void][DateTime]::ParseExact($Date, "yyyy-MM-dd", $null)

$remoteScript = @'
set -Eeuo pipefail

COMPOSE_ENV_FILE="/home/ste/fulton-web-app-deploy/.env"
if [ -f "$COMPOSE_ENV_FILE" ]; then
  set -a
  . "$COMPOSE_ENV_FILE"
  set +a
fi
ENV_FILE="${FULTONS_ENV_FILE:-/srv/storage/appdata/fultons-quiz/app.env}"
quiz_date="${QUIZ_DATE:?QUIZ_DATE is required}"
force="${QUIZ_FORCE:-false}"
token="$(grep '^INTERNAL_QUIZ_TOKEN=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"

if [ -z "$token" ]; then
  echo "FAIL: INTERNAL_QUIZ_TOKEN is not configured."
  exit 1
fi

docker exec -i \
  -e QUIZ_DATE="$quiz_date" \
  -e QUIZ_FORCE="$force" \
  -e INTERNAL_QUIZ_TOKEN="$token" \
  fultons-quiz \
  python - <<'PY'
import http.client
import json
import os

payload = {
    "date": os.environ["QUIZ_DATE"],
    "force": os.environ.get("QUIZ_FORCE", "false").lower() == "true",
}
connection = http.client.HTTPConnection("127.0.0.1", 3000, timeout=900)
connection.request(
    "POST",
    "/internal/generate-daily-quiz",
    body=json.dumps(payload),
    headers={
        "Authorization": "Bearer " + os.environ["INTERNAL_QUIZ_TOKEN"],
        "Content-Type": "application/json",
    },
)
response = connection.getresponse()
body = response.read().decode("utf-8")
print("status=" + str(response.status))
try:
    print(json.dumps(json.loads(body), indent=2))
except json.JSONDecodeError:
    print(body)
raise SystemExit(0 if response.status == 200 else 1)
PY

'@

$forceValue = if ($Force) { "true" } else { "false" }
$remoteCommand = "export QUIZ_DATE='$Date' QUIZ_FORCE='$forceValue'; sed 's/\r$//' | bash -s"
($remoteScript -replace "`r", "") | & ssh -i $KeyPath -p $Port -o BatchMode=yes $Target $remoteCommand
exit $LASTEXITCODE
