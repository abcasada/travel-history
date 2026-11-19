# Restore runbook

Automated end-to-end check (throwaway key, scratch database): `./dev prod restore-test` for
production, `./dev restore-test` for development.

## Full restore onto a new or rebuilt server

1. Install Docker; clone the repository; run `./dev prod init`, then replace the generated
   `~/apps/travel-history-prod/.env.prod` with the copy from your password manager
   (`chmod 600`). Adjust `TRAVEL_BULK_DIR` if paths changed. Deploy once (`./dev prod deploy`
   from pushed `main`) so the release directory and images exist, then `./dev prod down`.
2. Copy the latest backup outbox from the NAS to the server, e.g. into
   `/storage/hdd1/travel-history/restore/` (keep the NAS copy untouched).
3. Start only the database. On an empty volume it initializes the roles and extensions; if the
   deploy in step 1 migrated a fresh database, remove it first
   (`docker volume rm travel-history-prod_db-data`, only on a server with no data of its own):
   `source scripts/stack.sh && prod_compose up -d db`
4. Restore the newest dump with your private key (bring the key file temporarily, then remove it):
   ```bash
   source scripts/stack.sh && prod_compose run --rm \
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
6. Start everything: `./dev prod up`.
7. Verify: sign in, check trips and history; `./dev prod restore-test` on the restored server.
8. Shred the private key copy on the server (`shred -u travel-backup.key`).
