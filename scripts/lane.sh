#!/usr/bin/env bash
# Parallel build lanes (D-98, work-order item P1): `./dev lane new|rm|list`.
#
# A lane is a git worktree at ../travel-history-lanes/<item> on branch item/<item>. Its .env is
# built from .env.example with fresh secrets (never copied from the real .env) and names its
# lane number, compose project, port block and image tag, so `./dev up|test|test-quick|lint|
# manage|e2e` there run a separate stack: its own DB volume, networks and var/bulk. The public
# reference downloads are copied in (GeoNames pins can't be downloaded again, D-94); raw imports
# and media never are, and the main bulk storage is never mounted.
set -euo pipefail
# shellcheck source=scripts/stack.sh
source "$(dirname "$0")/stack.sh"

MAX_LANES=9

usage() {
  cat <<'HELP'
./dev lane new <item>          create the lane (main checkout only)
./dev lane rm <item> [--force] stop its stack, delete its volumes, image tag and worktree, and
                               delete branch item/<item> (local and on origin) once merged
                               into main, also after a rebase. Refuses an unmerged branch or
                               uncommitted changes unless --force (which keeps the branch).
./dev lane list                lanes, their numbers and port blocks
HELP
}

valid_item() {
  [[ "$1" =~ ^[a-z0-9][a-z0-9-]{0,30}$ ]] ||
    die "item names are lowercase letters, digits and dashes (e.g. 40c-1), not '$1'"
}

# Lane worktrees (absolute paths) under LANES_DIR.
lane_paths() {
  git -C "$MAIN_ROOT" worktree list --porcelain | sed -n 's/^worktree //p' |
    while IFS= read -r p; do
      case "$p" in "$LANES_DIR"/*) echo "$p" ;; esac
    done
}

free_lane_number() {
  local used=" " p n
  while IFS= read -r p; do
    used+="$(env_file_value "$p/.env" TH_LANE) "
  done < <(lane_paths)
  for n in $(seq 1 "$MAX_LANES"); do
    [[ "$used" == *" $n "* ]] || { echo "$n"; return; }
  done
  die "all $MAX_LANES lane numbers are in use"
}

lane_compose() {  # path project args...
  local path="$1" project="$2"
  shift 2
  case "$project" in
    "$LANE_PROJECT_PREFIX"?*) ;;
    *) die "refusing to touch compose project '$project': not a lane" ;;
  esac
  local tag="lane-${project#"$LANE_PROJECT_PREFIX"}"
  TRAVEL_IMAGE_TAG="$tag" TRAVEL_DEV_IMAGE_TAG="$tag" docker compose -p "$project" \
    --project-directory "$path" -f "$path/compose.yaml" -f "$path/compose.dev.yaml" \
    --profile tools "$@"
}

cmd_new() {
  local item="${1:-}"
  [ -n "$item" ] || die "usage: ./dev lane new <item>"
  valid_item "$item"
  refuse_in_worktree "./dev lane new"
  local path="$LANES_DIR/$item" branch="item/$item"
  [ ! -e "$path" ] || die "$path already exists"

  local n web oidc mail vite cdp
  n="$(free_lane_number)"
  read -r web oidc mail vite cdp <<<"$(lane_ports "$n")"
  local p
  for p in "$web" "$oidc" "$mail" "$vite" "$cdp"; do
    ! ss -ltnH "sport = :$p" 2>/dev/null | grep -q . || die "port $p (lane $n's block) is in use"
  done

  mkdir -p "$LANES_DIR"
  if git -C "$MAIN_ROOT" show-ref --verify --quiet "refs/heads/$branch"; then
    echo "branch $branch exists: checking it out"
    git -C "$MAIN_ROOT" worktree add "$path" "$branch"
  else
    git -C "$MAIN_ROOT" worktree add -b "$branch" "$path" main
  fi

  env_from_example "$path/.env.example" "$path/.env" \
    TH_LANE="$n" TH_LANE_ITEM="$item" \
    TRAVEL_BULK_DIR=./var/bulk TRAVEL_LAN_BIND=127.0.0.1 TRAVEL_DEV_HOST=localhost \
    TRAVEL_WEB_PORT="$web" TRAVEL_OIDC_PORT="$oidc" TRAVEL_MAIL_PORT="$mail" \
    TRAVEL_VITE_PORT="$vite" TRAVEL_CDP_PORT="$cdp" \
    TRAVEL_DEV_IMAGE_TAG="lane-$item" TRAVEL_IMAGE_TAG="lane-$item" \
    TRAVEL_DB_SHARED_BUFFERS=256MB \
    OIDC_ISSUER="http://localhost:$oidc/default" \
    DJANGO_CSRF_TRUSTED_ORIGINS="http://localhost:$web,http://localhost:$vite" \
    TRAVEL_PUBLIC_BASE_URL="http://localhost:$web" \
    AGE_RECIPIENT= ORS_API_KEY= SMTP_PASSWORD=

  # Public reference downloads only: a copy, never raw/ or media/, never a mount.
  mkdir -p "$path/var/bulk"/{raw,media,backup-outbox,uploads,reference}
  # Empty: the tools container mounts it, and Docker would create a missing one as root.
  mkdir -p "$path/data/private"
  local main_bulk
  main_bulk="$(bulk_dir_of "$MAIN_ROOT")"
  if [ -n "$main_bulk" ] && [ -d "$main_bulk/reference" ]; then
    cp -a "$main_bulk/reference/." "$path/var/bulk/reference/"
    echo "copied $(du -sh "$path/var/bulk/reference" | cut -f1) of public reference data"
  else
    echo "warning: no reference data at $main_bulk/reference; ./dev load-reference will download"
  fi

  "$path/dev" setup

  cat <<EOF

lane $n ready: $path (branch $branch, compose project $LANE_PROJECT_PREFIX$item)
  web http://localhost:$web  vite http://localhost:$vite/app/  mock OIDC :$oidc  Mailpit :$mail
  cd $path && ./dev test-quick
  for the e2e: ./dev up && ./dev load-reference && ./dev e2e
  scratch files and logs: name them with the item ($item-test-quick.log); lanes share a scratchpad
  when merged: ./dev lane rm $item   (from the main checkout)
EOF
}

# Merged into main: either an ancestor of it, or (after a rebase onto main that wasn't written back
# to this branch) every commit has a patch-equivalent one in main (`git cherry` lists none with +).
branch_merged() {  # branch
  git -C "$MAIN_ROOT" show-ref --verify --quiet "refs/heads/$1" || return 1
  git -C "$MAIN_ROOT" merge-base --is-ancestor "$1" main 2>/dev/null && return 0
  local cherry
  cherry="$(git -C "$MAIN_ROOT" cherry main "$1" 2>/dev/null)" || return 1
  ! grep -q '^+' <<<"$cherry"
}

cmd_rm() {
  local item="" force=0 a
  for a in "$@"; do
    case "$a" in
      --force) force=1 ;;
      *) item="$a" ;;
    esac
  done
  [ -n "$item" ] || die "usage: ./dev lane rm <item> [--force]"
  valid_item "$item"
  refuse_in_worktree "./dev lane rm"
  local path="$LANES_DIR/$item" branch="item/$item" project="$LANE_PROJECT_PREFIX$item"
  lane_paths | grep -qxF "$path" || die "$path is not a lane worktree"
  [ "$(env_file_value "$path/.env" TH_LANE_ITEM)" = "$item" ] || die "$path/.env doesn't name lane $item"

  local merged=0
  if branch_merged "$branch"; then merged=1; fi
  if [ "$merged" = 0 ] && [ "$force" = 0 ]; then
    die "$branch isn't merged into main (use --force to remove the lane anyway; the branch is kept)"
  fi
  if [ -n "$(git -C "$path" status --porcelain)" ] && [ "$force" = 0 ]; then
    die "$path has uncommitted changes (use --force to discard them)"
  fi

  lane_compose "$path" "$project" down -v --remove-orphans
  docker rm -f "travel-e2e-chrome-$item" >/dev/null 2>&1 || true
  local img
  while IFS= read -r img; do
    docker image rm "$img" >/dev/null 2>&1 || true
  done < <(lane_image_tags "$item")
  # Files the containers wrote under var/ belong to this user (APP_UID), so git can remove them.
  if [ "$force" = 1 ]; then
    git -C "$MAIN_ROOT" worktree remove --force "$path"
  else
    git -C "$MAIN_ROOT" worktree remove "$path"
  fi
  if [ "$merged" = 1 ]; then
    # -D, not -d: branch_merged already checked main, and -d would compare with the branch's
    # upstream, which still holds the pre-rebase commits after the orchestrator's rebase.
    git -C "$MAIN_ROOT" branch -D "$branch"
    if git -C "$MAIN_ROOT" ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
      git -C "$MAIN_ROOT" push origin --delete "$branch" ||
        echo "warning: couldn't delete origin/$branch (git push origin --delete $branch)"
    fi
  else
    echo "kept unmerged branch $branch (git branch -D $branch deletes it)"
  fi
  rmdir "$LANES_DIR" 2>/dev/null || true
  echo "lane $item removed"
}

cmd_list() {
  local p n
  while IFS= read -r p; do
    n="$(env_file_value "$p/.env" TH_LANE)"
    printf '%-40s lane %s  ports %s  branch %s\n' "$p" "${n:-?}" \
      "$( [ -n "$n" ] && lane_ports "$n" | awk '{print "web " $1 " oidc " $2 " mail " $3 " vite " $4}')" \
      "$(git -C "$p" rev-parse --abbrev-ref HEAD)"
  done < <(lane_paths)
}

sub="${1:-help}"
shift || true
case "$sub" in
  new) cmd_new "$@" ;;
  rm) cmd_rm "$@" ;;
  list) cmd_list ;;
  *) usage ;;
esac
