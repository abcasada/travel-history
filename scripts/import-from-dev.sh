# Sourced: the steps of `./dev prod import-from-dev` (item 40b, D-97, docs/production.md "Copying
# the data from development"). The caller defines how to reach each side, so the same steps run
# against production (scripts/prod.sh) and against scratch containers (scripts/import-from-dev-test.sh):
#   dev_db <cmd…>          a command in dev's database container (stdin passed through)
#   prod_db <cmd…>         a command in production's database container
#   prod_dev_copy <staging db or ""> <work dir> <dev raw dir> <dev_copy args…>
#                          `manage.py dev_copy` with production's code, as the owner role
#   swap_stop, swap_start  stop production's services before the swap, start them after
# Dev's database is only read (pg_dump, SELECTs) and its raw files only copied, never changed.
# Every step that can refuse or fail says `|| die` itself: callers may run this where `set -e`
# doesn't apply (the test runs it as an `if` condition).

STAGING_DB=travel_import
KEEP_ACCOUNT="${TRAVEL_KEEP_ACCOUNT:-dev-admin@example.test}"

# Per-table rows of the kept account (every foreign key to accounts_user), its batches' points,
# the policies and the `app` functions: equal in dev and in the pruned copy. Rows the pruning
# removes from the kept account on purpose (:'synth', its SYNTHETIC batches as "1,2", and the
# e2e leftovers named "E2E ...") are left out on both sides.
IMPORT_VERIFY_SQL=$(cat <<'SQL'
WITH k AS (SELECT id FROM accounts_user WHERE lower(email) = lower(:'keep')),
s AS (SELECT string_to_array(:'synth', ',')::bigint[] AS ids)
SELECT 'rows ' || cl.relname || '.' || a.attname || '=' || (xpath('/row/c/text()', query_to_xml(
  format('select count(*) as c from %I t where %I = %s', cl.relname, a.attname, k.id)
  || CASE WHEN EXISTS (SELECT 1 FROM pg_attribute b WHERE b.attrelid = cl.oid
       AND b.attname = 'import_batch_id' AND NOT b.attisdropped)
     THEN format(' and (t.import_batch_id is null or t.import_batch_id <> all(%L::bigint[]))', s.ids)
     ELSE '' END
  || CASE cl.relname
     WHEN 'history_importbatch' THEN format(' and t.id <> all(%L::bigint[])', s.ids)
     WHEN 'history_rawfile' THEN format(' and t.id not in (select raw_file_id from '
       'history_importbatch where id = any(%L::bigint[]) and raw_file_id is not null)', s.ids)
     WHEN 'trips_trip' THEN ' and t.title not like ''E2E %'''
     WHEN 'trips_place' THEN ' and t.name not like ''E2E %'''
     WHEN 'accounts_devicetoken' THEN ' and t.name not like ''E2E %'''
     ELSE '' END,
  false, true, '')))[1]::text
FROM pg_constraint co JOIN pg_class cl ON cl.oid = co.conrelid
JOIN pg_attribute a ON a.attrelid = co.conrelid AND a.attnum = co.conkey[1], k, s
WHERE co.contype = 'f' AND co.confrelid = 'accounts_user'::regclass
UNION ALL SELECT 'batch ' || b.id || ' points=' || (SELECT count(*) FROM history_locationpoint p
  WHERE p.import_batch_id = b.id) FROM history_importbatch b, k, s
  WHERE b.owner_id = k.id AND b.id <> ALL(s.ids)
UNION ALL SELECT 'policies=' || count(*) FROM pg_policies
UNION ALL SELECT 'app_functions=' || count(*) FROM pg_proc p JOIN pg_namespace n
  ON n.oid = p.pronamespace WHERE n.nspname = 'app'
ORDER BY 1;
SQL
)

# import_from_dev <dev bulk dir> <production bulk dir> <work parent dir> <backup image>
import_from_dev() {
  local dev_bulk="$1" prod_bulk="$2" work_parent="$3" backup_image="$4"
  local dev_raw="$dev_bulk/raw" prod_raw="$prod_bulk/raw" work path src dst synth
  [ -d "$dev_raw" ] || die "dev's raw archive $dev_raw is missing"
  work="$(mktemp -d "$work_parent/import.XXXXXX")"
  # shellcheck disable=SC2064
  trap "rm -rf '$work'; prod_db psql -q -U postgres -d postgres -c 'DROP DATABASE IF EXISTS $STAGING_DB WITH (FORCE)' >/dev/null 2>&1 || true" EXIT
  dev_sql() { dev_db psql -v ON_ERROR_STOP=1 -U travel_owner -d travel -At "$@"; }
  copy_sql() { prod_db psql -v ON_ERROR_STOP=1 -U travel_owner -d "$STAGING_DB" -At "$@"; }
  prod_super() { prod_db psql -q -v ON_ERROR_STOP=1 -U postgres -d postgres "$@"; }

  echo "1/7 refusals: the same migrations, no real sign-in identity in production"
  dev_sql -c "SELECT app || '.' || name FROM django_migrations ORDER BY 1" > "$work/dev-migrations.txt" \
    || die "can't read dev's migrations"
  prod_dev_copy "" "$work" "$dev_raw" check --dev-migrations /work/dev-migrations.txt \
    || die "refused (above); production is unchanged"

  echo "2/7 copy dev's database into the staging database $STAGING_DB (piped, nothing on disk)"
  prod_super -c "DROP DATABASE IF EXISTS $STAGING_DB WITH (FORCE)" \
    -c "CREATE DATABASE $STAGING_DB OWNER travel_owner TEMPLATE template1" \
    -c "REVOKE ALL ON DATABASE $STAGING_DB FROM PUBLIC" \
    -c "GRANT CONNECT, TEMPORARY ON DATABASE $STAGING_DB TO travel_app, travel_public" \
    || die "can't create the staging database"
  dev_db pg_dump -U travel_owner -d travel -Fc --exclude-table-data=public.spatial_ref_sys \
    | prod_db pg_restore -U travel_owner -d "$STAGING_DB" --no-comments --exit-on-error \
    || die "the copy failed; production is unchanged"

  echo "3/7 inventory (dry run), then prune the copy down to $KEEP_ACCOUNT"
  prod_dev_copy "$STAGING_DB" "$work" "$dev_raw" prune --keep "$KEEP_ACCOUNT" --raw-dir /devraw \
    || die "the dry run failed; production is unchanged"
  prod_dev_copy "$STAGING_DB" "$work" "$dev_raw" prune --keep "$KEEP_ACCOUNT" --raw-dir /devraw \
    --execute > "$work/prune.txt" || die "the pruning failed; production is unchanged"
  tail -n 4 "$work/prune.txt"
  grep -q '^EXECUTED$' "$work/prune.txt" || die "the pruning didn't complete"
  synth="$(sed -n 's/^synthetic batches of the kept account: \[\(.*\)\]$/\1/p' "$work/prune.txt" | tr -d ' ')"

  echo "4/7 verify: the kept account's rows, batches, policies and functions equal dev's"
  dev_sql -v keep="$KEEP_ACCOUNT" -v synth="$synth" <<<"$IMPORT_VERIFY_SQL" > "$work/dev.txt"
  copy_sql -v keep="$KEEP_ACCOUNT" -v synth="$synth" <<<"$IMPORT_VERIFY_SQL" > "$work/copy.txt"
  [ -s "$work/dev.txt" ] || die "no verification output from dev"
  if ! diff -u "$work/dev.txt" "$work/copy.txt"; then
    die "the copy differs from dev (above); production is unchanged"
  fi
  [ "$(copy_sql -c 'SELECT count(*) FROM accounts_user')" = 1 ] \
    || die "the copy still has more than one account; production is unchanged"
  grep '^batch ' "$work/copy.txt" | sed 's/^/    /'
  echo "    $(wc -l < "$work/copy.txt") checks identical"

  echo "5/7 raw files the copy references -> $prod_raw (read-only, SHA-256 verified)"
  copy_sql -F '|' -c "SELECT storage_path, sha256 FROM history_rawfile ORDER BY 1" > "$work/raw.txt"
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
  mkdir -p "$prod_raw"
  docker run --rm -i --network none --user "$(id -u):$(id -g)" -v "$prod_raw:/raw:ro" \
    "$backup_image" sh -ec '
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
    mkdir -p "$prod_bulk/reference"
    cp -a --update=none "$dev_bulk/reference/." "$prod_bulk/reference/"
  fi

  echo "7/7 swap the copy in as production's database"
  swap_stop
  prod_super -c "DROP DATABASE travel WITH (FORCE)" -c "ALTER DATABASE $STAGING_DB RENAME TO travel" \
    || die "the swap failed"
  swap_start
  echo "import-from-dev done: production holds $KEEP_ACCOUNT's data from dev"
}
