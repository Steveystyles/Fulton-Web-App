#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-${HOME}/fulton-web-app-deploy}"
COMPOSE_ENV_FILE="${COMPOSE_ENV_FILE:-${COMPOSE_DIR}/.env}"
if [ -f "${COMPOSE_ENV_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${COMPOSE_ENV_FILE}"
  set +a
fi
ENV_FILE="${ENV_FILE:-${FULTONS_ENV_FILE:-/srv/storage/appdata/fultons-quiz/app.env}}"
QUIZ_DATE="${1:-$(TZ=Europe/London date -d tomorrow +%F)}"
QUIZ_FORCE="${QUIZ_FORCE:-false}"

if [[ ! "${QUIZ_DATE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "FAIL: quiz date must use YYYY-MM-DD format."
  exit 1
fi

if [ ! -f "${ENV_FILE}" ]; then
  echo "FAIL: private app env file is missing at ${ENV_FILE}."
  exit 1
fi

token="$(grep '^INTERNAL_QUIZ_TOKEN=' "${ENV_FILE}" | tail -1 | cut -d= -f2-)"
if [ -z "${token}" ]; then
  echo "FAIL: INTERNAL_QUIZ_TOKEN is not configured."
  exit 1
fi

echo "[daily-quiz] generating ${QUIZ_DATE}"
docker exec -i \
  -e QUIZ_DATE="${QUIZ_DATE}" \
  -e QUIZ_FORCE="${QUIZ_FORCE}" \
  -e INTERNAL_QUIZ_TOKEN="${token}" \
  fultons-quiz \
  python - <<'PY'
import http.client
import json
import os

payload = {
    "date": os.environ["QUIZ_DATE"],
    "force": os.environ.get("QUIZ_FORCE", "false").lower() == "true",
}
connection = http.client.HTTPConnection("127.0.0.1", 3000, timeout=1800)
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
