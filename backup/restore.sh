#!/usr/bin/env bash
# Restore a database dump from the outbox into the database named by the PG* environment.
#   AGE_IDENTITY_FILE=/path/to/private.key restore.sh <outbox>/db/<stamp>.dump.zst.age
# The target database must have been initialized by db/init (roles + extensions).
set -euo pipefail
dump="${1:?usage: restore.sh <dump.zst.age>}"
: "${AGE_IDENTITY_FILE:?AGE_IDENTITY_FILE (age private key file) is required}"
age -d -i "$AGE_IDENTITY_FILE" "$dump" | zstd -q -d | \
  pg_restore --no-password --no-comments --exit-on-error -d "${PGDATABASE:-travel}"
echo "restored $(basename "$dump")"
