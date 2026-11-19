#!/usr/bin/env bash
# The production stack (work-order item 40a, D-96, docs/production.md): `./dev prod <command>`.
# A separate compose project with its own database, deployed only from a clean, pushed main.
set -euo pipefail
# shellcheck source=scripts/stack.sh
source "$(dirname "$0")/stack.sh"
cd "$REPO_ROOT"

usage() {
  cat <<'HELP'
./dev prod init              create the production directory, its bulk storage and .env.prod
                             (fresh secrets, mode 0600); never overwrites an existing file
./dev prod deploy            build pushed main into images tagged by its commit, back up (when
                             AGE_RECIPIENT is set), migrate, restart, smoke-test
./dev prod up                apply .env.prod changes: recreate what changed (deployed image)
./dev prod status            deployed commit, containers and health
./dev prod ps | logs [svc]   show the stack / follow its logs
./dev prod migrate           run migrations with the deployed image (owner role)
./dev prod manage <cmd>      Django management command (owner role, deployed image)
./dev prod shell | psql      Django shell / psql (owner role)
./dev prod backup-now        one encrypted backup (refuses without AGE_RECIPIENT)
./dev prod restore-test      backup with a throwaway key -> restore into a scratch DB -> compare
./dev prod import-from-dev   replace production's database with a pruned copy of dev's (item 40b;
                             refused once production has a real sign-in identity)
./dev prod smoke             local smoke test of 127.0.0.1:8784 (headers, private paths, redirect)
./dev prod down              stop the stack (the database volume stays)
./dev prod tracker start|stop|logs|ps|smoke [url]   the internet-facing tracker endpoint (8783)
HELP
}

init() {
  mkdir -p "$PROD_DIR"
  chmod 700 "$PROD_DIR"
  mkdir -p "$PROD_DIR"/bulk/{raw,media,backup-outbox,uploads,reference}
  if [ -f "$PROD_ENV_FILE" ]; then
    echo "$PROD_ENV_FILE exists; left unchanged"
  else
    local ors
    ors="$(grep -E '^ORS_API_KEY=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)"
    (
      umask 077
      while IFS= read -r line; do
        if [[ "$line" == DJANGO_SECRET_KEY=generate ]]; then
          echo "DJANGO_SECRET_KEY=$(random_secret 64)"  # Django's deploy check wants 50+
        elif [[ "$line" =~ ^([A-Z0-9_]+)=generate$ ]]; then
          echo "${BASH_REMATCH[1]}=$(random_secret)"
        elif [[ "$line" == APP_UID=* ]]; then
          echo "APP_UID=$(id -u)"
        elif [[ "$line" == APP_GID=* ]]; then
          echo "APP_GID=$(id -g)"
        elif [[ "$line" == ORS_API_KEY=* && -n "$ors" ]]; then
          echo "ORS_API_KEY=$ors"
        else
          echo "${line//__PROD_DIR__/$PROD_DIR}"
        fi
      done < .env.prod.example > "$PROD_ENV_FILE"
    )
    chmod 600 "$PROD_ENV_FILE"
    echo "created $PROD_ENV_FILE with fresh secrets$([ -n "$ors" ] && echo " (ORS_API_KEY copied from .env)")"
    echo "Adam adds OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET (item 40c) and AGE_RECIPIENT."
  fi
  docker network inspect valhalla >/dev/null 2>&1 || docker network create valhalla >/dev/null
  echo "production directory: $PROD_DIR"
}

# Only a clean, pushed main: the commit on origin is exactly what runs.
require_pushed_main() {
  local branch head remote
  branch="$(git rev-parse --abbrev-ref HEAD)"
  [ "$branch" = main ] || die "deploy only from main (this checkout is on $branch)"
  [ -z "$(git status --porcelain)" ] || die "the working tree isn't clean: commit and push first"
  git fetch --quiet origin main || die "can't fetch origin/main"
  head="$(git rev-parse HEAD)"
  remote="$(git rev-parse origin/main)"
  [ "$head" = "$remote" ] || die "HEAD $head isn't origin/main $remote: push (or pull) first"
}

# Keep the images of the last two deployed commits (the running one and one to go back to).
prune_images() {
  local keep repo tag
  keep="$(tac "$PROD_DIR/deploys.log" | awk '{print substr($2, 1, 12)}' | awk '!seen[$0]++' | head -2)"
  for repo in travel-history-backend travel-history-backup; do
    docker image ls "$repo" --format '{{.Tag}}' | while read -r tag; do
      [[ "$tag" =~ ^[0-9a-f]{12}$ ]] || continue  # only release images, never dev ones
      grep -qx "$tag" <<<"$keep" && continue
      docker image rm "$repo:$tag" >/dev/null 2>&1 && echo "removed old image $repo:$tag" || true
    done
  done
}

deploy() {
  prod_check_env_file
  require_pushed_main
  local head tag new old_commit ingest_running=false
  head="$(git rev-parse HEAD)"
  tag="${head:0:12}"
  old_commit="$(prod_commit)"
  new="$PROD_DIR/release.new"
  echo "deploying $head"
  rm -rf "$new"
  mkdir -p "$new"
  git archive "$head" | tar -x -C "$new"
  echo "$head" > "$new/.commit"

  echo "building images travel-history-backend:$tag and travel-history-backup:$tag"
  prod_compose_in "$new" "$tag" build migrate backup

  if [ -n "$old_commit" ] && [ -n "$(prod_compose ps -q db 2>/dev/null)" ]; then
    [ -n "$(prod_compose --profile tracker ps -q ingest 2>/dev/null)" ] && ingest_running=true
    if [ -n "$(prod_env_value AGE_RECIPIENT)" ]; then
      echo "backup before migrating (deployed: ${old_commit:0:12})"
      prod_compose run --rm backup /backup/backup.sh
    else
      echo "WARNING: no AGE_RECIPIENT in .env.prod, so no backup before migrating" >&2
    fi
  fi

  rm -rf "$PROD_DIR/release.old"
  [ -d "$PROD_RELEASE" ] && mv "$PROD_RELEASE" "$PROD_DIR/release.old"
  mv "$new" "$PROD_RELEASE"
  rm -rf "$PROD_DIR/release.old"
  echo "$(date -u +%FT%TZ) $head" >> "$PROD_DIR/deploys.log"

  # Migrations (owner role) before web and worker are recreated: if one fails, the previous
  # release keeps serving (each migration is its own transaction) and the deploy stops.
  prod_compose up -d --no-build db
  if ! prod_compose run --rm migrate; then
    echo "error: migrations failed; web and worker still run the previous image" >&2
    exit 1
  fi
  prod_compose up -d --no-build web worker backup
  $ingest_running && prod_compose --profile tracker up -d --no-build ingest
  wait_healthy prod_compose web 60 || {
    prod_compose logs --tail=40 migrate web
    exit 1
  }
  prune_images
  "$REPO_ROOT/scripts/prod-smoke.sh"
}

# Recreates the containers whose settings changed (e.g. after Adam pastes a secret into
# .env.prod), with the deployed image: no build, no new code.
up() {
  local ingest_running=false
  [ -n "$(prod_compose --profile tracker ps -q ingest 2>/dev/null)" ] && ingest_running=true
  prod_compose up -d --no-build db web worker backup
  $ingest_running && prod_compose --profile tracker up -d --no-build ingest
  wait_healthy prod_compose web 60 || {
    prod_compose logs --tail=40 web
    exit 1
  }
}

status() {
  local commit
  commit="$(prod_commit)"
  echo "production directory: $PROD_DIR"
  echo "deployed commit: ${commit:-none}"
  [ -n "$commit" ] || exit 0
  prod_compose --profile tracker ps
}

tracker() {
  local sub="${1:-help}"
  shift || true
  tc() { prod_compose --profile tracker "$@"; }
  case "$sub" in
    start | deploy)
      [ "$sub" = deploy ] && echo "note: the ingest service now runs the deployed production image (./dev prod deploy builds it)"
      tc up -d --no-build ingest
      wait_healthy tc ingest 45 || {
        tc logs --tail=30 ingest
        exit 1
      }
      TRACKER_SMOKE_TOKEN="${TRACKER_SMOKE_TOKEN:-}" "$REPO_ROOT/scripts/tracker-smoke.sh" </dev/null
      ;;
    stop) tc stop ingest && tc rm -f ingest ;;
    logs) tc logs -f --tail=100 ingest ;;
    ps) tc ps ingest ;;
    smoke) "$REPO_ROOT/scripts/tracker-smoke.sh" "$@" ;;
    *) echo "./dev prod tracker start | stop | logs | ps | smoke [https://<public host>] [--store]" ;;
  esac
}

# ---- import-from-dev (item 40b, docs/production.md "Copying the data from development") ----
# Dev's database is only read (pg_dump, SELECTs) and its raw files only copied, never changed.
STAGING_DB=travel_import
KEEP_ACCOUNT="${TRAVEL_KEEP_ACCOUNT:-dev-admin@example.test}"

# Per-table rows of the kept account (every foreign key to accounts_user), its batches' points,
# the policies and the `app` functions: equal in dev and in the pruned copy.
VERIFY_SQL=$(cat <<'SQL'
WITH k AS (SELECT id FROM accounts_user WHERE lower(email) = lower(:'keep'))
SELECT 'rows ' || cl.relname || '.' || a.attname || '=' || (xpath('/row/c/text()', query_to_xml(
  format('select count(*) as c from %I where %I = %s', cl.relname, a.attname, k.id),
  false, true, '')))[1]::text
FROM pg_constraint co JOIN pg_class cl ON cl.oid = co.conrelid
JOIN pg_attribute a ON a.attrelid = co.conrelid AND a.attnum = co.conkey[1], k
WHERE co.contype = 'f' AND co.confrelid = 'accounts_user'::regclass
UNION ALL SELECT 'batch ' || b.id || ' points=' || (SELECT count(*) FROM history_locationpoint p
  WHERE p.import_batch_id = b.id) FROM history_importbatch b, k WHERE b.owner_id = k.id
UNION ALL SELECT 'policies=' || count(*) FROM pg_policies
UNION ALL SELECT 'app_functions=' || count(*) FROM pg_proc p JOIN pg_namespace n
  ON n.oid = p.pronamespace WHERE n.nspname = 'app'
ORDER BY 1;
SQL
)

import_from_dev() {
  prod_check_env_file
  local commit work dev_bulk dev_raw prod_raw ingest_running=false
  commit="$(prod_commit)"
  [ -n "$commit" ] || die "nothing deployed yet: run ./dev prod deploy"
  [ -n "$(dev_compose ps -q db 2>/dev/null)" ] || die "the development database isn't running"
  dev_bulk="$(grep -E '^TRAVEL_BULK_DIR=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)"
  dev_bulk="${dev_bulk:-./var/bulk}"
  [[ "$dev_bulk" = /* ]] || dev_bulk="$REPO_ROOT/${dev_bulk#./}"
  dev_raw="$dev_bulk/raw"
  prod_raw="$PROD_DIR/bulk/raw"
  [ -d "$dev_raw" ] || die "dev's raw archive $dev_raw is missing"
  work="$(mktemp -d "$PROD_DIR/import.XXXXXX")"
  # shellcheck disable=SC2064
  trap "rm -rf '$work'; prod_compose exec -T db psql -q -U postgres -d postgres -c 'DROP DATABASE IF EXISTS $STAGING_DB WITH (FORCE)' >/dev/null 2>&1 || true" EXIT
  dev_sql() { dev_compose exec -T db psql -v ON_ERROR_STOP=1 -U travel_owner -d travel -At "$@"; }
  prod_sql() {  # database, psql args
    local db="$1"
    shift
    prod_compose exec -T db psql -v ON_ERROR_STOP=1 -U travel_owner -d "$db" -At "$@"
  }
  prod_super() { prod_compose exec -T db psql -q -v ON_ERROR_STOP=1 -U postgres -d postgres "$@"; }
  manage_copy() {  # extra compose-run args..., then the dev_copy arguments after --
    prod_compose --profile tools run --rm -v "$work:/work:ro" -v "$dev_raw:/devraw:ro" "$@"
  }

  prod_compose up -d --no-build db >/dev/null
  wait_healthy prod_compose db 30 >/dev/null || die "production's database isn't healthy"

  echo "1/7 refusals: the same migrations, no real sign-in identity in production"
  dev_sql -c "SELECT app || '.' || name FROM django_migrations ORDER BY 1" > "$work/dev-migrations.txt"
  manage_copy tools python manage.py dev_copy check --dev-migrations /work/dev-migrations.txt

  echo "2/7 copy dev's database into the staging database $STAGING_DB (piped, nothing on disk)"
  prod_super -c "DROP DATABASE IF EXISTS $STAGING_DB WITH (FORCE)" \
    -c "CREATE DATABASE $STAGING_DB OWNER travel_owner TEMPLATE template1" \
    -c "REVOKE ALL ON DATABASE $STAGING_DB FROM PUBLIC" \
    -c "GRANT CONNECT, TEMPORARY ON DATABASE $STAGING_DB TO travel_app, travel_public"
  dev_compose exec -T db pg_dump -U travel_owner -d travel -Fc \
    --exclude-table-data=public.spatial_ref_sys \
    | prod_compose exec -T db pg_restore -U travel_owner -d "$STAGING_DB" --no-comments --exit-on-error

  echo "3/7 inventory (dry run), then prune the copy down to $KEEP_ACCOUNT"
  manage_copy -e DB_NAME="$STAGING_DB" tools python manage.py dev_copy prune \
    --keep "$KEEP_ACCOUNT" --raw-dir /devraw
  manage_copy -e DB_NAME="$STAGING_DB" tools python manage.py dev_copy prune \
    --keep "$KEEP_ACCOUNT" --raw-dir /devraw --execute | tail -n 4

  echo "4/7 verify: the kept account's rows, batches, policies and functions equal dev's"
  dev_sql -v keep="$KEEP_ACCOUNT" <<<"$VERIFY_SQL" > "$work/dev.txt"
  prod_sql "$STAGING_DB" -v keep="$KEEP_ACCOUNT" <<<"$VERIFY_SQL" > "$work/copy.txt"
  [ -s "$work/dev.txt" ] || die "no verification output from dev"
  if ! diff -u "$work/dev.txt" "$work/copy.txt"; then
    die "the copy differs from dev (above); production is unchanged"
  fi
  [ "$(prod_sql "$STAGING_DB" -c 'SELECT count(*) FROM accounts_user')" = 1 ] \
    || die "the copy still has more than one account; production is unchanged"
  grep '^batch ' "$work/copy.txt" | sed 's/^/    /'
  echo "    $(wc -l < "$work/copy.txt") checks identical"

  echo "5/7 raw files the copy references -> $prod_raw (read-only, SHA-256 verified)"
  prod_sql "$STAGING_DB" -F '|' -c "SELECT storage_path, sha256 FROM history_rawfile ORDER BY 1" \
    > "$work/raw.txt"
  local path src dst
  while IFS='|' read -r path _; do
    [ -n "$path" ] || continue
    [[ "$path" != *..* && "$path" != /* ]] || die "unexpected raw path $path"
    src="$dev_raw/$path"
    dst="$prod_raw/$path"
    [ -f "$src" ] || die "raw file $path is missing in dev"
    if [ -e "$dst" ]; then
      cmp -s "$src" "$dst" || die "$dst exists with other content; raw files are never overwritten"
    else
      mkdir -p "$(dirname "$dst")"
      cp --preserve=timestamps "$src" "$dst.tmp"
      chmod 0444 "$dst.tmp"
      mv "$dst.tmp" "$dst"
    fi
  done < "$work/raw.txt"
  docker run --rm -i --network none --user "$(id -u):$(id -g)" -v "$prod_raw:/raw:ro" \
    "travel-history-backup:${commit:0:12}" sh -ec '
      n=0
      while IFS="|" read -r path sum; do
        [ -n "$path" ] || continue
        actual="$(zstd -q -d -c "/raw/$path" | sha256sum | cut -d" " -f1)"
        [ "$actual" = "$sum" ] || { echo "CHECKSUM MISMATCH $path" >&2; exit 1; }
        n=$((n + 1))
      done
      echo "    raw files verified: $n"' < "$work/raw.txt"

  echo "6/7 reference download cache (GeoNames, airports) -> production bulk storage"
  if [ -d "$dev_bulk/reference" ]; then
    mkdir -p "$PROD_DIR/bulk/reference"
    cp -a --update=none "$dev_bulk/reference/." "$PROD_DIR/bulk/reference/"
  fi

  echo "7/7 swap the copy in as production's database"
  [ -n "$(prod_compose --profile tracker ps -q ingest 2>/dev/null)" ] && ingest_running=true
  if [ -n "$(prod_env_value AGE_RECIPIENT)" ]; then
    echo "    backup of the database being replaced"
    prod_compose run --rm backup /backup/backup.sh
  fi
  prod_compose --profile tracker stop web worker backup ingest >/dev/null 2>&1 || true
  prod_super -c "DROP DATABASE travel WITH (FORCE)" -c "ALTER DATABASE $STAGING_DB RENAME TO travel"
  prod_compose up -d --no-build web worker backup
  $ingest_running && prod_compose --profile tracker up -d --no-build ingest
  wait_healthy prod_compose web 60 || {
    prod_compose logs --tail=40 web
    exit 1
  }
  echo "import-from-dev done: production holds $KEEP_ACCOUNT's data from dev"
}

cmd="${1:-help}"
shift || true
case "$cmd" in
  init) init ;;
  deploy) deploy ;;
  up) up ;;
  status) status ;;
  ps) prod_compose ps "$@" ;;
  logs) prod_compose logs -f --tail=100 "$@" ;;
  migrate) prod_compose run --rm migrate ;;
  manage) prod_compose --profile tools run --rm tools python manage.py "$@" ;;
  shell) prod_compose --profile tools run --rm tools python manage.py shell "$@" ;;
  psql) prod_compose exec db psql -U travel_owner -d travel "$@" ;;
  backup-now) prod_compose run --rm backup /backup/backup.sh ;;
  restore-test) "$REPO_ROOT/scripts/restore-test.sh" prod ;;
  import-from-dev) import_from_dev ;;
  smoke) "$REPO_ROOT/scripts/prod-smoke.sh" "$@" ;;
  down) prod_compose --profile tracker --profile tools down ;;
  tracker) tracker "$@" ;;
  help | *) usage ;;
esac
