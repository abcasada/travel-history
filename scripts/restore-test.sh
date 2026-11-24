#!/usr/bin/env bash
# Backup -> restore -> verify, end to end, with a throwaway key (never the real one), for either
# stack: `./dev restore-test` (dev) or `./dev prod restore-test` (production, D-96).
#
# 1. a backup of the stack's database and raw files, encrypted to a throwaway key;
# 2. a restore into a scratch PostGIS container on its own network;
# 3. every table's row count, the security policies and the `app` functions compared;
# 4. every raw import file checked against its recorded SHA-256.
# The scratch container, network and files are removed at the end, whatever happens.
set -euo pipefail
# shellcheck source=scripts/stack.sh
source "$(dirname "$0")/stack.sh"
refuse_in_worktree "restore-test"
cd "$REPO_ROOT"

stack="${1:-dev}"
case "$stack" in
  dev)
    stack_compose() { dev_compose "$@"; }
    rt="$REPO_ROOT/var/restore-test"
    init_dir="$REPO_ROOT/db/init"
    dev_compose build backup >/dev/null
    img="travel-history-backup:${LANE_IMAGE_TAG:-latest}"
    ;;
  prod)
    stack_compose() { prod_compose "$@"; }
    rt="$PROD_DIR/restore-test"
    init_dir="$PROD_RELEASE/db/init"
    commit="$(prod_commit)"
    [ -n "$commit" ] || die "nothing deployed yet: run ./dev prod deploy"
    img="travel-history-backup:${commit:0:12}"
    ;;
  *) die "usage: restore-test.sh dev|prod" ;;
esac

net="travel-restore-test-$stack"
db="travel-restore-db-$stack"
rm -rf "$rt"
mkdir -p "$rt/outbox"
chmod 700 "$rt"
trap 'docker rm -f "$db" >/dev/null 2>&1; docker network rm "$net" >/dev/null 2>&1; rm -rf "$rt"' EXIT

docker run --rm "$img" age-keygen 2>/dev/null > "$rt/test.key"
pub="$(grep -m1 'public key:' "$rt/test.key" | awk '{print $4}')"
stack_compose up -d db >/dev/null 2>&1

echo "1/4 backup with a test key ($stack)"
stack_compose run --rm -e AGE_RECIPIENT="$pub" -e BACKUP_OUTBOX=/rt/outbox -v "$rt:/rt" \
  backup /backup/backup.sh
dump="$(ls -1 "$rt"/outbox/db/*.age | head -1)"

echo "2/4 restore into a scratch database"
pw="$(random_secret)"
docker network create "$net" >/dev/null
docker run -d --name "$db" --network "$net" --user 999:999 -e POSTGRES_PASSWORD="$pw" \
  -e TRAVEL_OWNER_PASSWORD="$pw" -e TRAVEL_APP_PASSWORD="$pw" -e TRAVEL_PUBLIC_PASSWORD="$pw" \
  -v "$init_dir:/docker-entrypoint-initdb.d:ro" "$POSTGIS_IMAGE" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$db" psql -U postgres -d travel -c 'select 1' >/dev/null 2>&1 \
    && docker logs "$db" 2>&1 | grep -q 'PostgreSQL init process complete' && break
  sleep 2
done
sleep 2
scratch=(docker run --rm --network "$net" --user "$(id -u):$(id -g)" -e HOME=/tmp
  -e PGHOST="$db" -e PGUSER=travel_owner -e PGPASSWORD="$pw" -e PGDATABASE=travel
  -e AGE_IDENTITY_FILE=/rt/test.key -v "$rt:/rt" "$img")
"${scratch[@]}" /backup/restore.sh "/rt/outbox/db/$(basename "$dump")"

echo "3/4 compare every table's row count and the security policies"
counts_sql="SELECT table_name || '=' || (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I', table_name), false, true, '')))[1]::text FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' UNION ALL SELECT 'policies=' || count(*) FROM pg_policies UNION ALL SELECT 'app_functions=' || count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'app' ORDER BY 1"
stack_compose exec -T db psql -U travel_owner -d travel -At -c "$counts_sql" > "$rt/source.txt"
"${scratch[@]}" psql -At -c "$counts_sql" > "$rt/restored.txt"
if diff -u "$rt/source.txt" "$rt/restored.txt"; then
  echo "    $(wc -l < "$rt/source.txt") tables/checks identical"
else
  echo "RESTORE TEST FAILED: differences above" >&2
  exit 1
fi

echo "4/4 verify raw import files against their checksums"
"${scratch[@]}" python3 /backup/verify_raw.py /rt/outbox /rt/test.key
echo "restore test passed ($stack)"
