param(
  [string]$Target = "ste@192.168.0.15",
  [string]$KeyPath = "$env:USERPROFILE\.ssh\codex_fultons_ed25519",
  [int]$Port = 22,
  [ValidateSet("GEMINI_API_KEY", "MAP_CLUE_GEMINI_API_KEY", "FULTONS_FACTS_GEMINI_API_KEY")]
  [string]$VariableName = "GEMINI_API_KEY",
  [switch]$NoRestart
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $KeyPath)) {
  throw "SSH key not found: $KeyPath"
}

$secureKey = Read-Host "$VariableName value" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
  $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
  if ([string]::IsNullOrWhiteSpace($plainKey)) {
    throw "Gemini API key cannot be empty."
  }
  $encodedKey = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($plainKey))
}
finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
  $plainKey = $null
}

$remoteScript = @'
set -Eeuo pipefail

COMPOSE_FILE="/home/ste/fulton-web-app-deploy/compose.yaml"
COMPOSE_ENV_FILE="/home/ste/fulton-web-app-deploy/.env"
if [ -f "$COMPOSE_ENV_FILE" ]; then
  set -a
  . "$COMPOSE_ENV_FILE"
  set +a
fi
ENV_FILE="${FULTONS_ENV_FILE:-/srv/storage/appdata/fultons-quiz/app.env}"

python3 - "$ENV_FILE" <<'PY'
import base64
import os
import sys

env_path = sys.argv[1]
api_key = base64.b64decode(os.environ["GEMINI_B64"]).decode("utf-8").strip()
key_name = os.environ["KEY_NAME"]
allowed = {"GEMINI_API_KEY", "MAP_CLUE_GEMINI_API_KEY", "FULTONS_FACTS_GEMINI_API_KEY"}
if key_name not in allowed:
    raise SystemExit("Unsupported Gemini environment variable")
if not api_key:
    raise SystemExit("Gemini API key cannot be empty")

with open(env_path, encoding="utf-8") as handle:
    lines = handle.read().splitlines()

updated = False
for index, line in enumerate(lines):
    if line.startswith(key_name + "="):
        lines[index] = key_name + "=" + api_key
        updated = True
        break
if not updated:
    lines.append(key_name + "=" + api_key)

with open(env_path, "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")
PY

unset GEMINI_B64 KEY_NAME
chmod 600 "$ENV_FILE"
if [ "${RESTART_APP}" != "1" ]; then
  echo "PASS: Gemini key stored. Restart deferred."
  exit 0
fi
cd "$(dirname "$COMPOSE_FILE")"
FULTONS_ENV_FILE="$ENV_FILE" docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --force-recreate --no-build quiz-app

for attempt in $(seq 1 30); do
  if docker exec fultons-quiz python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=3)); raise SystemExit(0 if data.get('ok') else 1)" >/dev/null 2>&1; then
    echo "PASS: Gemini key stored and Fulton Web App is healthy."
    exit 0
  fi
  sleep 2
done

echo "FAIL: Fulton Web App did not become healthy after storing the Gemini key."
docker logs --tail 80 fultons-quiz || true
exit 1
'@

$restartApp = if ($NoRestart) { "0" } else { "1" }
$payload = "$VariableName`n$encodedKey`n$restartApp`n$remoteScript" -replace "`r", ""
$payload | & ssh -i $KeyPath -p $Port -o BatchMode=yes $Target "read -r KEY_NAME; read -r GEMINI_B64; read -r RESTART_APP; export KEY_NAME GEMINI_B64 RESTART_APP; sed 's/\r$//' | bash -s"
$encodedKey = $null
exit $LASTEXITCODE
