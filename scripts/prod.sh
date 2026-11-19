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

  # web waits for migrate (owner role) to finish successfully, so a failed migration stops here.
  prod_compose up -d --no-build db web worker backup
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
  smoke) "$REPO_ROOT/scripts/prod-smoke.sh" "$@" ;;
  down) prod_compose --profile tracker --profile tools down ;;
  tracker) tracker "$@" ;;
  help | *) usage ;;
esac
