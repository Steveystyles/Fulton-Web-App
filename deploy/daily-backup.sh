#!/bin/sh
# Run as the existing deployment user. No root privileges or plaintext env copies.
set -eu
umask 077
SOURCE_DIR=${FULTONS_BACKUP_SOURCE_DIR:-/home/ste/fulton-web-app}
DATA_DIR=${FULTONS_BACKUP_DATA_DIR:-/disk4/appdata/fultons-quiz}
BACKUP_ROOT=${FULTONS_BACKUP_ROOT:-/srv/storage/backups/fultons-quiz}
STATE_DIR=${FULTONS_BACKUP_STATE_DIR:-/home/ste/.local/state/fultons-backup}
mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/backup.lock"
flock -n 9 || exit 0
log=$(mktemp "$STATE_DIR/run.XXXXXX")
trap 'rm -f "$log"' EXIT HUP INT TERM
if python3 "$SOURCE_DIR/deploy/backup_manager.py" create --data-dir "$DATA_DIR" --backup-root "$BACKUP_ROOT" >"$log" 2>&1; then
    date -u +%FT%TZ >"$STATE_DIR/last-success"
    mv "$log" "$STATE_DIR/latest.log"
else
    mv "$log" "$STATE_DIR/latest-error.log"
    exit 1
fi
# Retention intentionally remains opt-in until restore points have been reviewed.
