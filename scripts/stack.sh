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
POSTGIS_IMAGE=postgis/postgis:18-3.6@sha256:b4466ea2ba7e3af54fcbba996d45325720f4b3ecb4f43f99b2f41367dc196f23

die() {
  echo "error: $*" >&2
  exit 1
}

random_secret() { head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c 48; }

# The project name is explicit, so a stray COMPOSE_PROJECT_NAME can't point dev commands
# at production.
dev_compose() {
  docker compose -p "$DEV_PROJECT" --project-directory "$REPO_ROOT" \
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
