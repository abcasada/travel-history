#!/usr/bin/env bash
# Runs backup.sh every day at $BACKUP_TIME (local time, TZ env). Without an age recipient it
# only warns: an unencrypted backup is never written.
set -uo pipefail
BACKUP_TIME="${BACKUP_TIME:-03:30}"
while true; do
  now=$(date +%s)
  next=$(date -d "today $BACKUP_TIME" +%s)
  [ "$next" -le "$now" ] && next=$(date -d "tomorrow $BACKUP_TIME" +%s)
  echo "$(date -u +%FT%TZ) schedule: next backup at $(date -d "@$next")"
  sleep $((next - now))
  if [ -z "${AGE_RECIPIENT:-}" ]; then
    echo "$(date -u +%FT%TZ) schedule: WARNING no AGE_RECIPIENT configured; backup skipped" >&2
    continue
  fi
  /backup/backup.sh || echo "$(date -u +%FT%TZ) schedule: backup FAILED" >&2
done
