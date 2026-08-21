param(
  [string]$Target = "ste@192.168.0.15",
  [string]$KeyPath = "$env:USERPROFILE\.ssh\codex_fultons_ed25519",
  [int]$Port = 22,
  [ValidateSet("GEMINI_API_KEY", "MAP_CLUE_GEMINI_API_KEY")]
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
CANONICAL_SOURCE="https://github.com/Steveystyles/Fulton-Web-App.git"

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

[ ! -L "$COMPOSE_ENV_FILE" ] && [ -f "$COMPOSE_ENV_FILE" ] || {
  echo "FAIL: compose env file is missing or unsafe at $COMPOSE_ENV_FILE" >&2
  exit 1
}
ENV_FILE="$(read_compose_setting FULTONS_ENV_FILE)"
[[ "$ENV_FILE" =~ ^/[A-Za-z0-9._/-]+$ ]] || {
  echo "FAIL: configured application env path is unsafe" >&2
  exit 1
}

CURRENT_IMAGE=""
EXPECTED_IMAGE_ID=""
APPDATA_DIR=""
if [ "${RESTART_APP}" = "1" ]; then
  [ -f "$COMPOSE_FILE" ] || {
    echo "FAIL: compose file is missing at $COMPOSE_FILE" >&2
    exit 1
  }
  APPDATA_DIR="$(read_compose_setting FULTONS_HOST_DATA_DIR)"
  CONFIGURED_IMAGE="$(read_compose_setting FULTONS_IMAGE)"
  [[ "$APPDATA_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] || {
    echo "FAIL: configured appdata path is unsafe" >&2
    exit 1
  }
  docker info >/dev/null
  if [[ ! "$CONFIGURED_IMAGE" =~ ^ghcr\.io/steveystyles/fulton-web-app@sha256:[0-9a-f]{64}$ ]] && \
     [[ ! "$CONFIGURED_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "FAIL: compose image selection is not immutable." >&2
    exit 1
  fi
  docker image inspect "$CONFIGURED_IMAGE" >/dev/null 2>&1 || {
    echo "FAIL: configured immutable image is not available locally." >&2
    exit 1
  }
  CONFIGURED_IMAGE_ID="$(docker image inspect "$CONFIGURED_IMAGE" --format '{{.Id}}')"
  [[ "$CONFIGURED_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "FAIL: configured immutable image is not available locally." >&2
    exit 1
  }
  docker inspect fultons-quiz >/dev/null 2>&1 || {
    echo "FAIL: fultons-quiz must already exist; use the signed updater for deployment." >&2
    exit 1
  }
  CURRENT_IMAGE="$(docker inspect fultons-quiz --format '{{.Image}}')"
  [[ "$CURRENT_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "FAIL: current container did not expose an immutable image ID." >&2
    exit 1
  }
  [ "$CURRENT_IMAGE" = "$CONFIGURED_IMAGE_ID" ] || {
    echo "FAIL: running image does not match the immutable compose selection; use the signed updater." >&2
    exit 1
  }
  EXPECTED_IMAGE_ID="$(docker image inspect "$CURRENT_IMAGE" --format '{{.Id}}')"
  [ "$EXPECTED_IMAGE_ID" = "$CURRENT_IMAGE" ] || {
    echo "FAIL: current immutable image is not available locally." >&2
    exit 1
  }
  IMAGE_SOURCE="$(docker image inspect "$CURRENT_IMAGE" --format '{{ index .Config.Labels "org.opencontainers.image.source" }}')"
  IMAGE_REVISION="$(docker image inspect "$CURRENT_IMAGE" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
  [ "$IMAGE_SOURCE" = "$CANONICAL_SOURCE" ] || {
    echo "FAIL: current image has a non-canonical OCI source label." >&2
    exit 1
  }
  [[ "$IMAGE_REVISION" =~ ^[0-9a-f]{40}$ ]] || {
    echo "FAIL: current image has an invalid OCI revision label." >&2
    exit 1
  }
  export FULTONS_ENV_FILE="$ENV_FILE"
  export FULTONS_HOST_DATA_DIR="$APPDATA_DIR"
  export FULTONS_IMAGE="$CURRENT_IMAGE"
  docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" config --quiet
fi

python3 - "$ENV_FILE" <<'PY'
import base64
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

env_path = Path(sys.argv[1])
try:
    api_key = base64.b64decode(os.environ["GEMINI_B64"], validate=True).decode("utf-8")
except (ValueError, UnicodeError) as error:
    raise SystemExit(f"Gemini API key encoding is invalid: {error}") from error
key_name = os.environ["KEY_NAME"]
allowed = {"GEMINI_API_KEY", "MAP_CLUE_GEMINI_API_KEY"}
if key_name not in allowed:
    raise SystemExit("Unsupported Gemini environment variable")
if (
    not re.fullmatch(r"[A-Za-z0-9._-]{16,512}", api_key)
    or any(ord(character) < 32 or ord(character) == 127 for character in api_key)
):
    raise SystemExit("Gemini API key contains unsupported dotenv characters or has an invalid length")
if env_path.is_symlink() or not env_path.is_file():
    raise SystemExit("application environment must be a regular, non-symlink file")

lines = env_path.read_text(encoding="utf-8-sig").splitlines()

updated = False
result = []
for line in lines:
    candidate = line.split("=", 1)[0].strip() if "=" in line else ""
    if candidate == key_name:
        if not updated:
            result.append(key_name + "=" + api_key)
            updated = True
        continue
    result.append(line)
if not updated:
    result.append(key_name + "=" + api_key)

descriptor, temporary = tempfile.mkstemp(prefix=f".{env_path.name}.", dir=env_path.parent)
try:
    os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        descriptor = -1
        handle.write("\n".join(result).rstrip("\n") + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, env_path)
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    directory = os.open(env_path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
finally:
    if descriptor >= 0:
        os.close(descriptor)
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY

unset GEMINI_B64 KEY_NAME
chmod 600 "$ENV_FILE"
if [ "${RESTART_APP}" != "1" ]; then
  echo "PASS: Gemini key stored. Restart deferred."
  exit 0
fi
cd "$(dirname "$COMPOSE_FILE")"
docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" \
  up -d --force-recreate --no-build quiz-app
RESTARTED_IMAGE="$(docker inspect fultons-quiz --format '{{.Image}}')"
[ "$RESTARTED_IMAGE" = "$EXPECTED_IMAGE_ID" ] || {
  echo "FAIL: restarted image $RESTARTED_IMAGE does not match selected $EXPECTED_IMAGE_ID" >&2
  exit 1
}

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
