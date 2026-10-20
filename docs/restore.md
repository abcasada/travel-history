# Restore runbook

Automated end-to-end check (throwaway key, scratch database): `./dev restore-test`.

## Full restore onto a new or rebuilt server

1. Install Docker; clone the repository; restore `.env` from your password manager
   (`chmod 600 .env`). Adjust `TRAVEL_BULK_DIR` and `TRAVEL_LAN_BIND` if paths/addresses changed.
2. Copy the latest backup outbox from the NAS to the server, e.g. into
   `/storage/hdd1/travel-history/restore/` (keep the NAS copy untouched).
3. Start only the database (it initializes the roles and extensions on an empty volume):
   `docker compose -f compose.yaml up -d db`
4. Restore the newest dump with your private key (bring the key file temporarily, then remove it):
   ```bash
   docker compose -f compose.yaml run --rm \
     -e AGE_IDENTITY_FILE=/restore/travel-backup.key \
     -v /storage/hdd1/travel-history/restore:/restore \
     backup /backup/restore.sh /restore/db/<newest>.dump.zst.age
   ```
5. Restore raw files and photos: decrypt every `raw/**.age` into `$TRAVEL_BULK_DIR/raw/` and
   every `media/**.age` into `$TRAVEL_BULK_DIR/media/` (same relative paths, without `.age`):
   ```bash
   cd /storage/hdd1/travel-history/restore
   find raw media -name '*.age' | while read -r f; do
     out="$TRAVEL_BULK_DIR/${f%.age}"; mkdir -p "$(dirname "$out")"
     age -d -i travel-backup.key -o "$out" "$f"
   done
   chmod -R a-w "$TRAVEL_BULK_DIR/raw"
   ```
6. Start everything: `./dev up` (development) or `docker compose -f compose.yaml up -d`.
7. Verify: sign in, check trips and history; `./dev restore-test` on the restored server.
8. Shred the private key copy on the server (`shred -u travel-backup.key`).
