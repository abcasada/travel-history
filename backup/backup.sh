#!/usr/bin/env bash
# One backup run (PLAN.md §22.1). Everything written to the outbox is encrypted with age to the
# backup PUBLIC key; the private key never lives on this server. The NAS pulls the outbox.
#
#   outbox/db/<stamp>.dump.zst.age        pg_dump -Fc | zstd | age     (last $KEEP_DUMPS kept here)
#   outbox/raw/<path>.age                 each immutable raw import file, encrypted once
#   outbox/media/<path>.age               each photo derivative, encrypted once
#   outbox/manifests/<stamp>.json.age     every object with its SHA-256
set -euo pipefail

: "${AGE_RECIPIENT:?AGE_RECIPIENT (age public key) is not set; refusing to write unencrypted backups}"
BULK="${BULK_DIR:-/bulk}"
OUTBOX="${BACKUP_OUTBOX:-$BULK/backup-outbox}"
KEEP_DUMPS="${KEEP_DUMPS:-7}"
STAMP="$(date -u +%Y-%m-%dT%H%MZ)"
umask 077

log() { echo "$(date -u +%FT%TZ) backup: $*"; }
encrypt_to() {  # stdin -> encrypted file, written atomically
  local target="$1"
  mkdir -p "$(dirname "$target")"
  age -r "$AGE_RECIPIENT" -o "$target.tmp"
  mv "$target.tmp" "$target"
}

mkdir -p "$OUTBOX"/{db,raw,media,manifests}

log "dumping database"
# spatial_ref_sys belongs to the PostGIS extension (re-created by db/init); we add no custom SRIDs.
pg_dump -Fc --no-password --exclude-table-data=public.spatial_ref_sys | zstd -q -T2 -10 | encrypt_to "$OUTBOX/db/$STAMP.dump.zst.age"

copied_raw=0
if [ -d "$BULK/raw" ]; then
  while IFS= read -r -d '' file; do
    rel="${file#"$BULK/raw/"}"
    target="$OUTBOX/raw/$rel.age"
    [ -f "$target" ] && continue  # raw files are immutable: encrypt once
    encrypt_to "$target" < "$file"
    copied_raw=$((copied_raw + 1))
  done < <(find "$BULK/raw" -type f ! -name '*.tmp' -print0)
fi

copied_media=0
if [ -d "$BULK/media" ]; then
  while IFS= read -r -d '' file; do
    rel="${file#"$BULK/media/"}"
    target="$OUTBOX/media/$rel.age"
    [ -f "$target" ] && [ "$target" -nt "$file" ] && continue
    encrypt_to "$target" < "$file"
    copied_media=$((copied_media + 1))
  done < <(find "$BULK/media" -type f ! -name '*.tmp' -print0)
fi

log "writing manifest"
(
  cd "$OUTBOX"
  printf '{"created": "%s", "objects": [\n' "$STAMP"
  find db raw media -type f -name '*.age' -print0 | sort -z | {
    first=1
    while IFS= read -r -d '' obj; do
      sum="$(sha256sum "$obj" | cut -d' ' -f1)"
      size="$(stat -c %s "$obj")"
      [ $first -eq 1 ] || printf ',\n'
      printf '  {"path": "%s", "sha256": "%s", "bytes": %s}' "$obj" "$sum" "$size"
      first=0
    done
  }
  printf '\n]}\n'
) | encrypt_to "$OUTBOX/manifests/$STAMP.json.age"

# Local retention only: the NAS keeps its own versioned snapshots.
ls -1t "$OUTBOX"/db/*.dump.zst.age 2>/dev/null | tail -n +"$((KEEP_DUMPS + 1))" | xargs -r rm -f
ls -1t "$OUTBOX"/manifests/*.json.age 2>/dev/null | tail -n +"$((KEEP_DUMPS + 1))" | xargs -r rm -f

log "done: dump $STAMP, $copied_raw new raw file(s), $copied_media new/updated media file(s)"
