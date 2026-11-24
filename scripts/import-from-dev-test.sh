#!/usr/bin/env bash
# Scratch-container test of import-from-dev (item 40b, D-97): `./dev prod import-test`.
# Two scratch PostGIS databases (a "dev" and a "production") on their own internal network, both
# migrated with the working tree's code and SYNTHETIC data only; then the same steps as
# `./dev prod import-from-dev` (scripts/import-from-dev.sh) with hooks that point at them:
#   1. a copy succeeds: one account left, its real batch kept, its SYNTHETIC batch and the other
#      account pruned, the raw file copied and verified, the scratch "dev" untouched;
#   2. it is repeatable (the raw file already there is compared, not overwritten);
#   3. refused when the migrations differ, production unchanged;
#   4. refused once production has a real (https) identity, production unchanged.
# Never touches the development or production stacks. Everything is removed at the end.
set -euo pipefail
# shellcheck source=scripts/stack.sh
source "$(dirname "$0")/stack.sh"
# shellcheck source=scripts/import-from-dev.sh
source "$REPO_ROOT/scripts/import-from-dev.sh"
cd "$REPO_ROOT"

net=travel-import-test
devc=travel-import-test-dev
prodc=travel-import-test-prod
img="travel-history-backend-dev:${LANE_IMAGE_TAG:-latest}"
backup_img="travel-history-backup:${LANE_IMAGE_TAG:-latest}"
tmp="$REPO_ROOT/var/import-test"
pw="$(random_secret)"
secret="$(random_secret 64)"
cleanup() {
  docker rm -f "$devc" "$prodc" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  chmod -R u+w "$tmp" 2>/dev/null || true
  rm -rf "$tmp"
}
trap cleanup EXIT
cleanup
mkdir -p "$tmp"/dev/raw "$tmp"/prod/raw "$tmp"/work
docker image inspect "$backup_img" >/dev/null 2>&1 || dev_compose build backup >/dev/null

docker network create --internal "$net" >/dev/null
for c in "$devc" "$prodc"; do
  docker run -d --name "$c" --network "$net" --user 999:999 -e POSTGRES_PASSWORD="$pw" \
    -e TRAVEL_OWNER_PASSWORD="$pw" -e TRAVEL_APP_PASSWORD="$pw" -e TRAVEL_PUBLIC_PASSWORD="$pw" \
    -v "$REPO_ROOT/db/init:/docker-entrypoint-initdb.d:ro" "$POSTGIS_IMAGE" >/dev/null
done
for c in "$devc" "$prodc"; do
  for _ in $(seq 1 60); do
    docker exec "$c" psql -U postgres -d travel -c 'select 1' >/dev/null 2>&1 \
      && docker logs "$c" 2>&1 | grep -q 'PostgreSQL init process complete' && break
    sleep 2
  done
done
sleep 2

django() {  # db host, db name, bulk dir, extra docker args…, -- manage.py args…
  local host="$1" name="$2" bulk="$3" extra=()
  shift 3
  while [ "$1" != -- ]; do
    extra+=("$1")
    shift
  done
  shift
  docker run --rm -i --network "$net" --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -e PYTHONDONTWRITEBYTECODE=1 -e DB_HOST="$host" -e DB_NAME="$name" -e DB_USER=travel_owner \
    -e DB_PASSWORD="$pw" -e DB_PUBLIC_USER=travel_public -e DB_PUBLIC_PASSWORD="$pw" \
    -e DJANGO_SECRET_KEY="$secret" -e DJANGO_DEBUG=false -v "$REPO_ROOT/backend:/app:ro" \
    -v "$bulk:/bulk" "${extra[@]}" "$img" python manage.py "$@" 2> >(grep -v ' INFO ' >&2)
}
dev_db() { docker exec -i "$devc" "$@"; }
prod_db() { docker exec -i "$prodc" "$@"; }
prod_dev_copy() {
  local db="$1" work="$2" raw="$3"
  shift 3
  django "$prodc" "${db:-travel}" "$tmp/prod" -v "$work:/work:ro" -v "$raw:/devraw:ro" -- dev_copy "$@"
}
swap_stop() { :; }
swap_start() { :; }
q() { docker exec -i "$1" psql -U travel_owner -d travel -At -c "$2"; }
fail() {
  echo "IMPORT TEST FAILED: $*" >&2
  exit 1
}
run_import() { (import_from_dev "$tmp/dev" "$tmp/prod" "$tmp/work" "$backup_img") > "$tmp/out.txt" 2>&1; }

echo "setup: migrate both scratch databases, SYNTHETIC data in the scratch dev"
django "$devc" travel "$tmp/dev" -- migrate -v 0
django "$prodc" travel "$tmp/prod" -- migrate -v 0
django "$devc" travel "$tmp/dev" -- shell -c '
import datetime as dt, json, pathlib
from django.contrib.gis.geos import Point
from django.utils import timezone
from travel.accounts.models import User
from travel.history.models import ImportBatch, LocationPoint, PointSource
from travel.history.rawstore import store_file
from travel.trips.models import Trip
MOCK = "http://mock-oidc.example.test:8781/default"
WICHITA = Point(-97.3375, 37.6922, srid=4326)
keep = User.objects.create(email="dev-admin@example.test", oidc_issuer=MOCK, oidc_sub="dev-admin")
other = User.objects.create(email="dev-member@example.test", oidc_issuer=MOCK, oidc_sub="dev-member")
def batch(owner, doc, n, name):
    src = pathlib.Path("/tmp") / name
    src.write_text(json.dumps(doc))
    raw = store_file(owner.pk, src, original_name=name)
    b = ImportBatch.objects.create(owner=owner, kind="google_timeline", status="done", raw_file=raw)
    LocationPoint.objects.bulk_create([LocationPoint(owner=owner, import_batch=b, geom=WICHITA,
        ts=timezone.now() - dt.timedelta(minutes=i), source=PointSource.OWNTRACKS) for i in range(n)])
batch(keep, {"semanticSegments": [], "about": "generated, unmarked on purpose"}, 7, "kept.json")
batch(keep, {"SYNTHETIC": "generated test data"}, 3, "fixture.json")
batch(other, {"SYNTHETIC": "generated test data", "other": True}, 5, "other.json")
for owner in (keep, other):
    Trip.objects.create(owner=owner, title="Synthetic trip", start_date=dt.date(2024, 5, 1),
                        end_date=dt.date(2024, 5, 2))
'
dev_before="$(q "$devc" "SELECT (SELECT count(*) FROM accounts_user) || '/' || (SELECT count(*) FROM history_locationpoint) || '/' || (SELECT count(*) FROM trips_trip)")"
[ "$dev_before" = 2/15/2 ] || fail "unexpected scratch dev data $dev_before"

echo "1. a copy succeeds and prunes"
run_import || { cat "$tmp/out.txt"; fail "the first copy failed"; }
grep -q 'dev-member@example.test: ' "$tmp/out.txt" || fail "no dry-run inventory per account"
grep -q 'synthetic batches of the kept account: \[' "$tmp/out.txt" || fail "synthetic batch not found"
got="$(q "$prodc" "SELECT (SELECT string_agg(email, ',') FROM accounts_user) || '/' || (SELECT count(*) FROM history_importbatch) || '/' || (SELECT count(*) FROM history_locationpoint) || '/' || (SELECT count(*) FROM trips_trip) || '/' || (SELECT count(*) FROM history_rawfile)")"
[ "$got" = "dev-admin@example.test/1/7/1/1" ] || fail "production after the copy: $got"
[ "$(find "$tmp/prod/raw" -type f | wc -l)" = 1 ] || fail "expected exactly one raw file in production"
grep -q 'raw files verified: 1' "$tmp/out.txt" || fail "raw file not verified"
[ "$(q "$devc" "SELECT (SELECT count(*) FROM accounts_user) || '/' || (SELECT count(*) FROM history_locationpoint) || '/' || (SELECT count(*) FROM trips_trip)")" = "$dev_before" ] \
  || fail "the scratch dev changed"
[ -z "$(ls "$tmp/work")" ] || fail "work files left behind"
[ "$(q "$prodc" "SELECT count(*) FROM pg_database WHERE datname = '$STAGING_DB'")" = 0 ] \
  || fail "staging database left behind"

echo "2. repeatable"
run_import || { cat "$tmp/out.txt"; fail "the second copy failed"; }
[ "$(q "$prodc" "SELECT count(*) FROM history_locationpoint")" = 7 ] || fail "second copy counts"

echo "3. refused when the migrations differ"
q "$devc" "INSERT INTO django_migrations (app, name, applied) VALUES ('trips', '9999_scratch', now())" >/dev/null
q "$prodc" "INSERT INTO django_session VALUES ('scratch-marker', 'x', now() + interval '1 day')" >/dev/null
if run_import; then fail "a migration mismatch was not refused"; fi
grep -q 'migrations differ' "$tmp/out.txt" || { cat "$tmp/out.txt"; fail "wrong refusal"; }
[ "$(q "$prodc" "SELECT count(*) FROM django_session")" = 1 ] || fail "production changed"
q "$devc" "DELETE FROM django_migrations WHERE name = '9999_scratch'" >/dev/null

echo "4. refused for good once production has a real identity"
django "$prodc" travel "$tmp/prod" -- shell -c '
from travel.accounts.models import User
User.objects.create(email="someone@example.test", oidc_sub="real-sub",
                    oidc_issuer="https://auth.example.test/application/o/travel/")
'
if run_import; then fail "a real identity was not refused"; fi
grep -q 'real sign-in identity' "$tmp/out.txt" || { cat "$tmp/out.txt"; fail "wrong refusal"; }
[ "$(q "$prodc" "SELECT count(*) FROM accounts_user")" = 2 ] || fail "production changed"
echo "import test passed"
