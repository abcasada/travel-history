# Sourced by ./dev and scripts/*.sh: how to reach each stack (D-46, D-96).
#
# The two stacks are separate compose projects with their own database volumes, networks and
# env files, so no development command can reach the production database:
#   dev   project travel-history       compose.yaml + compose.dev.yaml   .env (repo root)
#   prod  project travel-history-prod  compose.yaml + compose.prod.yaml  <prod dir>/.env.prod,
#         run from <prod dir>/release (a `git archive` of the deployed commit), never from the
#         working tree, with images tagged by that commit.
# The production directory sits beside the repository, outside the git working tree, so
# `git clean` can't reach its env file or bulk storage. TRAVEL_PROD_DIR overrides it.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_PROJECT=travel-history
PROD_PROJECT=travel-history-prod
PROD_DIR="${TRAVEL_PROD_DIR:-$(dirname "$REPO_ROOT")/travel-history-prod}"
PROD_ENV_FILE="$PROD_DIR/.env.prod"
PROD_RELEASE="$PROD_DIR/release"
PROD_WEB_PORT=8784
POSTGIS_IMAGE=postgis/postgis:18-3.6@sha256:4a43e3c3e5d55b9208240fc71db543b79c638766280c625a425bd0a2390989c4

die() {
  echo "error: $*" >&2
  exit 1
}

random_secret() {  # [length], default 48
  local n="${1:-48}"
  head -c $((n * 2)) /dev/urandom | base64 | tr -d '/+=\n' | head -c "$n"
}

# ---- Parallel lanes (D-98, item P1) ----
# A lane is a git worktree at ../travel-history-lanes/<item> on branch item/<item>, made by
# `./dev lane new`. Its .env (from .env.example, never the real .env) names the lane (TH_LANE,
# TH_LANE_ITEM) and its port block, so its dev stack is its own compose project with its own
# DB volume, networks, image tag and var/bulk. Only the main checkout's stack holds real data.
LANE_PROJECT_PREFIX=travel-history-lane-

_git_dir_abs() { git -C "$REPO_ROOT" rev-parse --path-format=absolute "$1" 2>/dev/null || true; }
GIT_COMMON_DIR="$(_git_dir_abs --git-common-dir)"
# The main checkout's root (the repository root itself outside git, e.g. a production release).
MAIN_ROOT="$REPO_ROOT"
[ -n "$GIT_COMMON_DIR" ] && MAIN_ROOT="$(dirname "$GIT_COMMON_DIR")"
LANES_DIR="$(dirname "$MAIN_ROOT")/travel-history-lanes"

in_worktree() { [ -n "$GIT_COMMON_DIR" ] && [ "$(_git_dir_abs --git-dir)" != "$GIT_COMMON_DIR" ]; }

refuse_in_worktree() {  # what
  if in_worktree; then
    die "$1 runs only in the main checkout ($MAIN_ROOT), never in a worktree lane"
  fi
}

# A value from an env file (KEY=value lines).
env_file_value() { grep -E "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2- || true; }

LANE_ITEM=""
LANE_NUMBER=""
LANE_IMAGE_TAG=""
if in_worktree; then
  LANE_ITEM="$(env_file_value "$REPO_ROOT/.env" TH_LANE_ITEM)"
  LANE_NUMBER="$(env_file_value "$REPO_ROOT/.env" TH_LANE)"
  DEV_PROJECT="$LANE_PROJECT_PREFIX${LANE_ITEM:-unset}"
  LANE_IMAGE_TAG="lane-${LANE_ITEM:-unset}"
fi

# Images a lane builds carry its tag (D-121), so `./dev build` or `./dev up --build` in a lane
# never retags the main checkout's images (travel-history-backup:latest and the rest).
lane_image_tags() {  # item -> image references
  local repo
  for repo in travel-history-backend-dev travel-history-backend travel-history-backup; do
    echo "$repo:lane-$1"
  done
}

# Port block of lane n: web 8800+10(n-1), mock OIDC +1, Mailpit +2, Vite 5180+10(n-1), the
# e2e browser's debugging port 9222+n. (8790 belongs to another app on this host.)
lane_ports() {  # n -> "web oidc mail vite cdp"
  local n="$1" web=$((8800 + 10 * ($1 - 1)))
  echo "$web $((web + 1)) $((web + 2)) $((5180 + 10 * (n - 1))) $((9222 + n))"
}

# Absolute path of an env file's TRAVEL_BULK_DIR (relative paths are relative to its checkout).
bulk_dir_of() {  # checkout-root
  local d
  d="$(env_file_value "$1/.env" TRAVEL_BULK_DIR)"
  [ -n "$d" ] || return 0
  [[ "$d" = /* ]] || d="$1/${d#./}"
  echo "$d"
}

# A lane's stack must never reach the main project, its DB volume or its bulk storage.
lane_check() {
  [ -n "$LANE_ITEM" ] && [ -n "$LANE_NUMBER" ] ||
    die "this worktree's .env has no TH_LANE/TH_LANE_ITEM: create lanes with ./dev lane new <item>"
  [ "$DEV_PROJECT" != travel-history ] || die "a worktree may not use the main dev project"
  local bulk
  bulk="$(bulk_dir_of "$REPO_ROOT")"
  case "$(realpath -m "$bulk")/" in
    "$REPO_ROOT"/*) ;;
    *) die "TRAVEL_BULK_DIR ($bulk) must be inside this worktree, never the main bulk storage" ;;
  esac
}

# Write an env file from .env.example: every "generate" value gets a fresh secret, KEY=value
# overrides replace their line (or are appended). Mode 0600.
env_from_example() {  # example dest [KEY=value ...]
  local example="$1" dest="$2" line key kv
  shift 2
  local -A over=()
  local order=()
  for kv in "$@"; do over["${kv%%=*}"]="${kv#*=}"; order+=("${kv%%=*}"); done
  (
    umask 077
    while IFS= read -r line; do
      key=""
      [[ "$line" =~ ^([A-Z0-9_]+)= ]] && key="${BASH_REMATCH[1]}"
      if [ -n "$key" ] && [ -n "${over[$key]+x}" ]; then
        echo "$key=${over[$key]}"
        unset "over[$key]"
      elif [[ "$line" =~ ^([A-Z0-9_]+)=generate$ ]]; then
        echo "$key=$(random_secret)"
      else
        echo "$line"
      fi
    done < "$example"
    for key in "${order[@]}"; do
      [ -n "${over[$key]+x}" ] && echo "$key=${over[$key]}"
    done
    true
  ) > "$dest"
  chmod 600 "$dest"
}

# The project name is explicit, so a stray COMPOSE_PROJECT_NAME can't point dev commands
# at production (or a lane at the main dev stack).
# In a lane the image tags come from the lane's name, not its .env (older lanes' .env files have
# no TRAVEL_IMAGE_TAG), and the shell's values override the file's. The main checkout passes
# nothing, so its tags and rendered config are what its .env says.
dev_compose() {
  local tags=()
  if in_worktree; then
    lane_check
    tags=(TRAVEL_IMAGE_TAG="$LANE_IMAGE_TAG" TRAVEL_DEV_IMAGE_TAG="$LANE_IMAGE_TAG")
  fi
  env "${tags[@]}" docker compose -p "$DEV_PROJECT" --project-directory "$REPO_ROOT" \
    -f "$REPO_ROOT/compose.yaml" -f "$REPO_ROOT/compose.dev.yaml" "$@"
}

prod_env_value() { grep -E "^$1=" "$PROD_ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true; }

prod_check_env_file() {
  [ -f "$PROD_ENV_FILE" ] || die "$PROD_ENV_FILE is missing: run ./dev prod init"
  [ "$(stat -c %a "$PROD_ENV_FILE")" = 600 ] || die "$PROD_ENV_FILE must be mode 0600"
  [ "$(stat -c %u "$PROD_ENV_FILE")" = "$(id -u)" ] || die "$PROD_ENV_FILE must belong to you"
}

prod_commit() { cat "$PROD_RELEASE/.commit" 2>/dev/null || true; }

# Compose for the production project from a given release directory and image tag. The shell's
# environment is dropped (only what Docker itself needs is kept), so nothing exported in this
# shell can override .env.prod.
prod_compose_in() {
  local release="$1" tag="$2"
  shift 2
  local keep=(PATH="$PATH" HOME="$HOME")
  [ -n "${DOCKER_HOST:-}" ] && keep+=(DOCKER_HOST="$DOCKER_HOST")
  [ -n "${DOCKER_CONTEXT:-}" ] && keep+=(DOCKER_CONTEXT="$DOCKER_CONTEXT")
  [ -n "${DOCKER_CONFIG:-}" ] && keep+=(DOCKER_CONFIG="$DOCKER_CONFIG")
  env -i "${keep[@]}" TRAVEL_IMAGE_TAG="$tag" docker compose -p "$PROD_PROJECT" \
    --project-directory "$release" -f "$release/compose.yaml" -f "$release/compose.prod.yaml" \
    --env-file "$PROD_ENV_FILE" "$@"
}

# Compose for the deployed release.
prod_compose() {
  prod_check_env_file
  local commit
  commit="$(prod_commit)"
  [ -n "$commit" ] || die "nothing deployed yet: run ./dev prod deploy"
  prod_compose_in "$PROD_RELEASE" "${commit:0:12}" "$@"
}

# Wait for a service's health check; prints the final state.
wait_healthy() {  # compose-function service [tries]
  local fn="$1" service="$2" tries="${3:-60}" state="" id
  printf 'waiting for %s to be healthy' "$service"
  for _ in $(seq 1 "$tries"); do
    id="$("$fn" ps -q "$service" 2>/dev/null || true)"
    state="$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || true)"
    [ "$state" = healthy ] && break
    printf '.'
    sleep 2
  done
  echo " ${state:-not running}"
  [ "$state" = healthy ]
}
