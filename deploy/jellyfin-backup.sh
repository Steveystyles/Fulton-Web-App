#!/usr/bin/env bash
# Verified Jellyfin configuration/database backup. Run as the deployment user.
set -Eeuo pipefail
umask 077

readonly CONTAINER_NAME="${JELLYFIN_CONTAINER_NAME:-jellyfin}"
readonly CONFIG_DIR="${JELLYFIN_CONFIG_DIR:-/home/ste/docker/jellyfin/config}"
readonly BACKUP_ROOT="${JELLYFIN_BACKUP_ROOT:-/disk2/backups/jellyfin}"
readonly STATE_DIR="${JELLYFIN_BACKUP_STATE_DIR:-$HOME/.local/state/jellyfin-backup}"

mkdir -p -- "$BACKUP_ROOT" "$STATE_DIR"
chmod 700 "$BACKUP_ROOT" "$STATE_DIR"
exec 9>"$STATE_DIR/backup.lock"
flock -n 9 || exit 0

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
work="$BACKUP_ROOT/.jellyfin-$stamp.incomplete"
final="$BACKUP_ROOT/jellyfin-$stamp"

cleanup() {
  if [[ -d "$work" ]]; then
    case "$work" in
      "$BACKUP_ROOT"/.jellyfin-*.incomplete) rm -rf -- "$work" ;;
      *) printf 'Refusing to remove unsafe backup path: %s\n' "$work" >&2 ;;
    esac
  fi
}
trap cleanup EXIT HUP INT TERM

test -d "$CONFIG_DIR"
test -r "$CONFIG_DIR/data/jellyfin.db"
docker inspect "$CONTAINER_NAME" >/dev/null
mkdir -m 700 "$work"

docker exec "$CONTAINER_NAME" tar \
  --exclude='./data/jellyfin.db' \
  --exclude='./data/jellyfin.db-wal' \
  --exclude='./data/jellyfin.db-shm' \
  --exclude='./data/SQLiteBackups/*' \
  --exclude='./log/*' \
  --exclude='./temp/*' \
  -C /config -czf - . >"$work/config-files.tar.gz"

python3 - "$CONFIG_DIR/data/jellyfin.db" "$work/jellyfin.db" <<'PY'
import sqlite3
import sys

source_path, target_path = sys.argv[1:]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
target = sqlite3.connect(target_path)
try:
    with target:
        source.backup(target)
    result = target.execute("PRAGMA quick_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"backup quick_check failed: {result}")
finally:
    target.close()
    source.close()
PY

python3 - "$work/manifest.json" "$stamp" "$CONTAINER_NAME" "$CONFIG_DIR" <<'PY'
import json
import subprocess
import sys

path, stamp, container, source = sys.argv[1:]
image = subprocess.check_output(
    ["docker", "inspect", "--format", "{{.Config.Image}}", container],
    text=True,
).strip()
payload = {
    "archive_excludes": [
        "data/jellyfin.db*",
        "data/SQLiteBackups/*",
        "log/*",
        "temp/*",
    ],
    "container": container,
    "created_at_utc": stamp,
    "database_method": "sqlite_online_backup",
    "image": image,
    "source": source,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

gzip -t "$work/config-files.tar.gz"
(
  cd "$work"
  sha256sum config-files.tar.gz jellyfin.db manifest.json >SHA256SUMS
  sha256sum --check SHA256SUMS
)
chmod -R go-rwx "$work"
mv -- "$work" "$final"
trap - EXIT HUP INT TERM
printf '%s\n' "$final" >"$STATE_DIR/last-success"
printf 'Verified Jellyfin backup: %s\n' "$final"

