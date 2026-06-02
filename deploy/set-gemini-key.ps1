param(
  [string]$Target = "ste@192.168.0.15",
  [string]$KeyPath = "$env:USERPROFILE\.ssh\codex_fultons_ed25519",
  [int]$Port = 22
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $KeyPath)) {
  throw "SSH key not found: $KeyPath"
}

$secureKey = Read-Host "Gemini API key" -AsSecureString
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

ENV_FILE="/srv/storage/appdata/fultons-quiz/app.env"
COMPOSE_FILE="/home/ste/fulton-web-app-deploy/compose.yaml"

python3 - "$ENV_FILE" <<'PY'
import base64
import os
import sys

env_path = sys.argv[1]
api_key = base64.b64decode(os.environ["GEMINI_B64"]).decode("utf-8").strip()
if not api_key:
    raise SystemExit("Gemini API key cannot be empty")

with open(env_path, encoding="utf-8") as handle:
    lines = handle.read().splitlines()

updated = False
for index, line in enumerate(lines):
    if line.startswith("GEMINI_API_KEY="):
        lines[index] = "GEMINI_API_KEY=" + api_key
        updated = True
        break
if not updated:
    lines.append("GEMINI_API_KEY=" + api_key)

with open(env_path, "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")
PY

unset GEMINI_B64
chmod 600 "$ENV_FILE"
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

$payload = "$encodedKey`n$remoteScript" -replace "`r", ""
$payload | & ssh -i $KeyPath -p $Port -o BatchMode=yes $Target "read -r GEMINI_B64; export GEMINI_B64; sed 's/\r$//' | bash -s"
$encodedKey = $null
exit $LASTEXITCODE
