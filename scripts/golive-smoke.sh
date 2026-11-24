#!/usr/bin/env bash
# Go-live smoke test (work-order item 40d, docs/go-live.md): the whole app as it is exposed once
# TRAVEL_PUBLIC_SCOPE=all, generalizing scripts/tracker-smoke.sh from the two tracker paths.
#
#   ./dev golive-smoke local [--keep] [--port N] [--issuer URL]
#       Builds the production image from this checkout's HEAD (`git archive`, as a deploy does),
#       runs it with production's compose files and settings and scope `all` against a throwaway
#       database on 127.0.0.1 only, runs every check through simulated tunnel headers, and
#       removes the stack, its volume, its image and its directory again (--keep leaves it
#       running for manual testing). Never production's project, database, volumes, .env.prod or
#       commit-tagged images. Works in a lane worktree. --issuer: an https OIDC issuer to point
#       /auth/login at (default: an unreachable placeholder, so sign-in answers 503).
#   ./dev golive-smoke local-check     the checks again, against a stack left by --keep
#   ./dev golive-smoke local-down      remove a stack left by --keep
#   ./dev golive-smoke https://travel.adamcasada.com [--scope all|tracker] [--other HOST|--no-other]
#       Through Cloudflare and the tunnel, from anywhere (item 40e, after the "go"). --scope
#       tracker checks the state before go-live (Cloudflare's own 404s allowed). The other
#       public name defaults to trips.<domain> for a travel.<domain> canonical name.
#
# Checks: health and the landing page with production headers and HSTS; the installed PWA's
# index.html and sw.js with the CSP (F-1); plain HTTP redirected; a loopback Host through the
# tunnel refused (F-8); no docs or schema and junk Bearer tokens refused cleanly (F-7); large
# anonymous bodies refused (F-2); locally, scope all refusing to start without the provider
# (F-9) and a signed-in Member: public visibility refused (F-10), the hourly provider check and
# deactivate_account (F-3);
# sign-in (redirect to the provider with state, nonce, PKCE S256 and the canonical callback;
# cookie flags); every API operation in the OpenAPI schema and the private pages refuse anonymous
# requests; unknown and public-renderer paths 404 without DEBUG pages; robots.txt (Cloudflare
# serves its managed file when the app has none); the redirect from the other public name (not
# an open redirect; tracker paths exempt); the tracker endpoints unchanged (bogus tokens refused;
# with a token, accepted; locally, a synthetic token is made in the throwaway database); tokens
# absent from the logs. Tokens never appear on a command line: curl reads its config from stdin.
set -euo pipefail
# shellcheck source=scripts/stack.sh
source "$(dirname "$0")/stack.sh"
cd "$REPO_ROOT"

usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

# ---- the throwaway local stack ----
# A distinct project and image tag: never travel-history-prod and never a 12-hex release tag, so
# production's images, volumes and `prune_images` are untouched; per lane, so lanes can't collide.
LOCAL_PROJECT="travel-history-golive${LANE_ITEM:+-$LANE_ITEM}"
LOCAL_TAG="golive-local${LANE_ITEM:+-$LANE_ITEM}"
LOCAL_DIR="$REPO_ROOT/var/golive-local"  # var/ is git-ignored
LOCAL_ENV="$LOCAL_DIR/env"
LOCAL_RELEASE="$LOCAL_DIR/release"
LOCAL_OVERRIDE="$LOCAL_DIR/compose.local.yaml"
PLACEHOLDER_ISSUER="https://auth.invalid/application/o/travel-history/"
MIN_AVAILABLE_MIB=2500

[ "$LOCAL_PROJECT" != "$PROD_PROJECT" ] && [ "$LOCAL_PROJECT" != travel-history ] ||
  die "refusing project name $LOCAL_PROJECT"
[[ ! "$LOCAL_TAG" =~ ^[0-9a-f]{12}$ ]] || die "refusing a release-shaped image tag"

default_port() {  # lane n: web + 5 (8805, 8815, …); main checkout 8786
  if [ -n "$LANE_NUMBER" ]; then echo $((8800 + 10 * (LANE_NUMBER - 1) + 5)); else echo 8786; fi
}

local_compose() {
  [ -f "$LOCAL_ENV" ] || die "no local go-live stack: run ./dev golive-smoke local"
  local keep=(PATH="$PATH" HOME="$HOME")
  [ -n "${DOCKER_HOST:-}" ] && keep+=(DOCKER_HOST="$DOCKER_HOST")
  [ -n "${DOCKER_CONTEXT:-}" ] && keep+=(DOCKER_CONTEXT="$DOCKER_CONTEXT")
  [ -n "${DOCKER_CONFIG:-}" ] && keep+=(DOCKER_CONFIG="$DOCKER_CONFIG")
  env -i "${keep[@]}" TRAVEL_IMAGE_TAG="$LOCAL_TAG" docker compose -p "$LOCAL_PROJECT" \
    --project-directory "$LOCAL_RELEASE" -f "$LOCAL_RELEASE/compose.yaml" \
    -f "$LOCAL_RELEASE/compose.prod.yaml" -f "$LOCAL_OVERRIDE" --env-file "$LOCAL_ENV" "$@"
}

wait_for_memory() {
  local available
  for _ in $(seq 1 40); do
    available="$(free -m | awk '/^Mem:/ {print $7}')"
    [ "$available" -ge "$MIN_AVAILABLE_MIB" ] && return 0
    echo "only $available MiB available (need $MIN_AVAILABLE_MIB); waiting 30 s"
    sleep 30
  done
  die "not enough memory for the production image build"
}

local_down() {
  if [ -f "$LOCAL_ENV" ]; then
    local_compose --profile tools down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  docker image rm "travel-history-backend:$LOCAL_TAG" >/dev/null 2>&1 || true
  rm -rf "$LOCAL_DIR"
  echo "local go-live stack removed ($LOCAL_PROJECT, image tag $LOCAL_TAG)"
}

local_up() {  # port issuer
  local port="$1" issuer="$2" head
  [ ! -e "$LOCAL_DIR" ] || die "$LOCAL_DIR exists: ./dev golive-smoke local-check or local-down"
  if ss -ltn | awk '{print $4}' | grep -q ":$port\$"; then die "port $port is in use (--port N)"; fi
  head="$(git rev-parse HEAD)"
  [ -z "$(git status --porcelain)" ] || echo "note: uncommitted changes are not in the image (HEAD only)"
  mkdir -p "$LOCAL_DIR"/bulk/{raw,media,backup-outbox,uploads,reference} "$LOCAL_RELEASE"
  chmod 700 "$LOCAL_DIR"
  git archive "$head" | tar -x -C "$LOCAL_RELEASE"
  echo "$head" > "$LOCAL_RELEASE/.commit"
  # Production's own settings file, with fresh secrets and the go-live values: scope `all`, a
  # confidential client (placeholder secret) for an https issuer, a smaller database cache.
  env_from_example "$REPO_ROOT/.env.prod.example" "$LOCAL_ENV" \
    "APP_UID=$(id -u)" "APP_GID=$(id -g)" "TRAVEL_BULK_DIR=$LOCAL_DIR/bulk" \
    "DJANGO_SECRET_KEY=$(random_secret 64)" TRAVEL_PUBLIC_SCOPE=all \
    "OIDC_ISSUER=$issuer" OIDC_CLIENT_ID=golive-local "OIDC_CLIENT_SECRET=$(random_secret)" \
    ORS_API_KEY= TRAVEL_DB_SHARED_BUFFERS=128MB
  cat > "$LOCAL_OVERRIDE" <<YAML
# Generated by scripts/golive-smoke.sh: the throwaway go-live stack's own port (127.0.0.1 only).
services:
  web:
    ports: !override ["127.0.0.1:$port:8000"]
YAML
  echo "$port" > "$LOCAL_DIR/port"
  wait_for_memory
  echo "building travel-history-backend:$LOCAL_TAG from ${head:0:12}"
  local_compose build migrate
  local_compose up -d --no-build web
  wait_healthy local_compose web 90 || {
    local_compose logs --tail=40 migrate web
    return 1
  }
}

# A synthetic account with a Colota token (accepted on both endpoints) in the throwaway database.
local_token() {
  local secret
  secret="trk_$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n' | head -c 43)"
  printf '%s' "$secret" | sha256sum | cut -d' ' -f1 > "$LOCAL_DIR/token.sha256"
  if ! local_compose --profile tools run --rm --no-deps -T -v "$LOCAL_DIR/token.sha256:/work/h:ro" \
    tools python manage.py shell >"$work/token.log" 2>&1 <<'PY'
from travel.accounts.models import DeviceToken, User
user, _ = User.objects.get_or_create(email="golive-smoke@example.invalid", defaults={"display_name": "SYNTHETIC smoke"})
digest = open("/work/h").read().strip()
DeviceToken.objects.get_or_create(token_hash=digest, defaults={"user": user, "name": "golive smoke", "kind": "colota", "token_prefix": "trk_smok"})
PY
  then
    cat "$work/token.log" >&2
    die "could not create the synthetic token"
  fi
  rm -f "$LOCAL_DIR/token.sha256"
  echo "$secret"
}

# ---- the checks ----
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
chmod 700 "$work"
failures=0
pass() { printf '  ok    %s\n' "$1"; }
note() { printf '  note  %s\n' "$1"; }
fail() {
  printf '  FAIL  %s\n' "$1"
  failures=$((failures + 1))
}
expect() {  # description expected actual
  if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (got $3, expected $2)"; fi
}
header() { { grep -i "^$1:" "$work/headers" || true; } | tail -1 | cut -d: -f2- | tr -d '\r' | sed 's/^ *//'; }

mode=""        # local | remote
base=""        # local: http://127.0.0.1:<port>
canonical=""
other=""
scope=all
proto=https    # what the visitor used; locally sent as X-Forwarded-Proto

# request METHOD HOST PATH [curl config line...]: status on stdout; headers and body in $work.
request() {
  local method="$1" host="$2" path="$3"
  shift 3
  {
    if [ "$mode" = local ]; then
      printf 'url = "%s%s"\n' "$base" "$path"
      printf 'header = "Host: %s"\n' "$host"
      # What cloudflared adds: the visitor's scheme and address (TEST-NET-1).
      printf 'header = "X-Forwarded-Proto: %s"\n' "$proto"
      printf 'header = "CF-Connecting-IP: 192.0.2.10"\n'
    else
      printf 'url = "%s://%s%s"\n' "$proto" "$host" "$path"
    fi
    printf 'request = "%s"\n' "$method"
    local line
    for line in "$@"; do printf '%s\n' "$line"; done
  } | curl --silent --show-error --path-as-is --max-time 20 --output "$work/body" \
    --dump-header "$work/headers" --write-out '%{http_code}' --config - 2>/dev/null || true
}

app_cookies() { grep -i '^set-cookie:' "$work/headers" | grep -vi 'set-cookie: *__cf' || true; }

# Production headers on an app response (HSTS only over HTTPS; Cloudflare's __cf cookies allowed).
production_headers() {  # description
  local missing=() csp
  [[ "$(header strict-transport-security)" == max-age=* ]] || missing+=("HSTS")
  [ "$(header x-content-type-options)" = nosniff ] || missing+=("nosniff")
  [ "$(header x-frame-options)" = DENY ] || missing+=("X-Frame-Options")
  [ "$(header referrer-policy)" = same-origin ] || missing+=("Referrer-Policy")
  [ "$(header cross-origin-opener-policy)" = same-origin ] || missing+=("COOP")
  csp="$(header content-security-policy)"
  [[ "$csp" == *"default-src"* && "$csp" == *"frame-ancestors 'none'"* ]] || missing+=("CSP")
  [ -n "$(app_cookies)" ] && missing+=("no cookies")
  if [ ${#missing[@]} -eq 0 ]; then pass "$1: production headers"; else fail "$1: missing ${missing[*]}"; fi
}
from_app() { [ -n "$(header content-security-policy)" ]; }  # Cloudflare's own pages carry no CSP
no_debug_page() {  # description
  if grep -qiE 'traceback|DisallowedHost|django\.|settings\.py|INSTALLED_APPS' "$work/body"; then
    fail "$1: looks like DEBUG's error page"
  else
    pass "$1: no DEBUG page"
  fi
}

check_landing() {
  echo "Health and the landing page ($canonical):"
  expect "GET /healthz" 200 "$(request GET "$canonical" /healthz)"
  expect "GET /" 200 "$(request GET "$canonical" /)"
  production_headers "landing page"
  expect "  offers only Sign in" 'href="/auth/login"' \
    "$(grep -o 'href="[^"]*"' "$work/body" | sort -u | tr '\n' ' ' | sed 's/ $//')"
  grep -q '<form' "$work/body" && fail "  the landing page has a form" || pass "  no forms"
  grep -q 'name="robots" content="noindex, nofollow"' "$work/body" && pass "  noindex" || fail "  noindex missing"
  local status location
  proto=http
  status="$(request GET "$canonical" '/app/trips?year=2024')"
  location="$(header location)"
  proto=https
  if [[ "$status" =~ ^30[178]$ ]] && [ "$location" = "https://$canonical/app/trips?year=2024" ]; then
    pass "plain HTTP redirected to HTTPS ($status)"
  else
    fail "plain HTTP: $status $location"
  fi
  expect "the SPA build is served (manifest)" 200 "$(request GET "$canonical" /app/manifest.webmanifest)"
  # F-1: the service worker answers every in-app navigation with its precached /app/index.html,
  # so that copy, and sw.js itself, must carry the CSP and X-Frame-Options too.
  local file
  for file in /app/index.html /app/sw.js; do
    status="$(request GET "$canonical" "$file")"
    if [ "$status" = 200 ]; then
      production_headers "GET $file (the installed PWA's copy)"
      [[ "$(header content-security-policy)" == *"script-src 'self'"* ]] &&
        pass "  CSP script-src 'self'" || fail "  CSP without script-src 'self'"
    elif [ "$status" = 302 ] && [[ "$(header location)" == /auth/login* ]]; then
      pass "GET $file -> sign in"
    else
      fail "GET $file answered $status"
    fi
  done
  if [ "$(request GET "$canonical" /app/index.html)" = 200 ]; then
    # Inline scripts would be blocked by script-src 'self' (vite-plugin-pwa registers the
    # worker from a file).
    local inline
    inline="$(grep -o '<script[^>]*>' "$work/body" | grep -cv 'src=' || true)"
    expect "  the shell has no inline scripts" 0 "$inline"
  fi
  if [ "$mode" = local ]; then
    expect "unknown Host refused" 400 "$(request GET evil.example /)"
    no_debug_page "  unknown Host"
    proto=http
    expect "loopback Host through the tunnel still redirected" 301 "$(request GET localhost /)"
    proto=https
    # F-8: through the tunnel (CF-Connecting-IP) only the public names are served; a route with
    # an "HTTP Host Header" override would otherwise skip the scope rule.
    expect "loopback Host through the tunnel over HTTPS: 404" 404 "$(request GET localhost /)"
    expect "  127.0.0.1 too (health check path)" 404 "$(request GET 127.0.0.1 /healthz)"
    expect "  the tracker path too" 404 "$(request POST localhost:8784 /api/v1/ingest/owntracks)"
  fi
}

check_sign_in() {
  echo "Sign-in:"
  local status location cookie
  status="$(request GET "$canonical" '/auth/login?next=/app/trips')"
  location="$(header location)"
  cookie="$(app_cookies | { grep -i 'sessionid=' || true; } | tail -1)"
  if [ "$status" = 302 ]; then
    [[ "$location" == https://* && "$location" != "https://$canonical/"* ]] &&
      pass "GET /auth/login -> the provider (${location%%\?*})" || fail "GET /auth/login -> $location"
    local enc="redirect_uri=https%3A%2F%2F$canonical%2Fauth%2Fcallback"
    local missing=()
    [[ "$location" == *"$enc"* ]] || missing+=("canonical redirect_uri")
    for part in response_type=code state= nonce= code_challenge= code_challenge_method=S256 scope=openid; do
      [[ "$location" == *"$part"* ]] || missing+=("$part")
    done
    if [ ${#missing[@]} -eq 0 ]; then pass "  state, nonce, PKCE S256, canonical callback"; else fail "  missing ${missing[*]}"; fi
  elif [ "$status" = 503 ] && [ "$mode" = local ]; then
    pass "GET /auth/login: 503 (the placeholder issuer is unreachable; --issuer for a real one)"
    no_debug_page "  503"
  else
    fail "GET /auth/login answered $status"
  fi
  if [ "$status" != 302 ]; then
    note "  no session cookie to check (Django saves no session on a 5xx answer)"
  elif [ -n "$cookie" ]; then
    local missing=()
    grep -qi '; *secure' <<<"$cookie" || missing+=("Secure")
    grep -qi '; *httponly' <<<"$cookie" || missing+=("HttpOnly")
    grep -qi '; *samesite=lax' <<<"$cookie" || missing+=("SameSite=Lax")
    if [ ${#missing[@]} -eq 0 ]; then pass "  session cookie Secure, HttpOnly, SameSite=Lax"; else fail "  session cookie lacks ${missing[*]}"; fi
  else
    fail "  no session cookie for the sign-in state"
  fi
  status="$(request GET "$canonical" '/auth/callback?code=x&state=forged')"
  [[ "$status" =~ ^(400|503)$ ]] && pass "GET /auth/callback with a forged state refused ($status)" ||
    fail "GET /auth/callback with a forged state answered $status"
  no_debug_page "  callback"
}

check_private() {
  echo "Private paths refuse anonymous requests ($canonical):"
  local path status location
  for path in /app/ /app/trips /app/history /auth/reauth /auth/logout /admin/ /.env /.git/config; do
    status="$(request GET "$canonical" "$path")"
    location="$(header location)"
    if [ "$status" = 302 ] && [[ "$location" == /auth/login* ]]; then
      pass "GET $path -> sign in"
    elif [ "$status" = 404 ]; then
      pass "GET $path -> 404"
    else
      fail "GET $path ($status $location)"
    fi
  done
  local operations refused=0 total=0 method
  operations="$(python3 - "$REPO_ROOT/frontend/src/api/openapi.json" <<'PY'
import json, re, sys
paths = json.load(open(sys.argv[1]))["paths"]
for path, ops in sorted(paths.items()):
    concrete = re.sub(r"\{[^}]+\}", "1", path)
    for method in sorted(ops):
        if method in ("get", "post", "put", "patch", "delete"):
            print(method.upper(), concrete)
PY
)"
  while read -r method path; do
    total=$((total + 1))
    status="$(request "$method" "$canonical" "$path" 'header = "Content-Type: application/json"' 'data = "{}"')"
    if [ "$status" = 401 ]; then refused=$((refused + 1)); else fail "$method $path answered $status"; fi
  done <<<"$operations"
  expect "every API operation in the schema answers 401 ($total)" "$total" "$refused"
  [ "$total" -gt 40 ] || fail "too few API operations found ($total)"
  expect "GET /api/v1/openapi.json (schema not public)" 401 "$(request GET "$canonical" /api/v1/openapi.json)"
  # F-7: a Bearer header passes the login wall for the API's own auth classes; the docs and the
  # schema don't exist in production, and a token the provider can't vouch for is no user.
  local bearer='header = "Authorization: Bearer smoke.junk.token"'
  expect "GET /api/v1/openapi.json with a Bearer header: not served" 404 \
    "$(request GET "$canonical" /api/v1/openapi.json "$bearer")"
  no_debug_page "  openapi.json"
  expect "GET /api/v1/docs with a Bearer header: not served" 404 \
    "$(request GET "$canonical" /api/v1/docs "$bearer")"
  expect "GET /api/v1/me with a junk Bearer token: 401, not 500" 401 \
    "$(request GET "$canonical" /api/v1/me "$bearer")"
  # F-2: a form POST with a well-formed csrftoken cookie used to be parsed (up to 40 MB) before
  # any view or rate limit; above the 2.5 MiB default it is refused before anything reads it.
  head -c $((3 * 1024 * 1024)) /dev/zero | tr '\0' 'x' | sed 's/^/a=/' > "$work/big-form"
  local csrf
  csrf="$(head -c 96 /dev/urandom | base64 -w0 | tr -dc 'A-Za-z0-9' | head -c 32)"
  expect "an anonymous 3 MiB form POST to / is refused (413)" 413 "$(request POST "$canonical" / \
    'header = "Content-Type: application/x-www-form-urlencoded"' \
    "header = \"Cookie: csrftoken=$csrf\"" "header = \"Referer: https://$canonical/\"" \
    "data-binary = \"@$work/big-form\"")"
}

# 404s: in scope `all` every path reaches the app, so its 404s carry its headers. Before go-live
# the tunnel's path rule sends only the tracker paths to the app, and Cloudflare answers the rest
# with its own bare 404 (2026-11-19).
check_not_found() {
  echo "404s and robots.txt ($canonical):"
  local path status
  for path in /static/nope.css /t/nope /u/nope/ /pm/1/large /invite/nope; do
    status="$(request GET "$canonical" "$path")"
    if [ "$status" != 404 ]; then
      fail "GET $path answered $status (no public renderer or invitations yet)"
    elif from_app; then
      production_headers "GET $path 404"
      no_debug_page "  $path"
    elif [ "$mode" = remote ] && [ "$scope" = tracker ]; then
      pass "GET $path 404 (Cloudflare's own: the path rule doesn't forward it)"
    else
      fail "GET $path 404 without the app's headers (route not pointing at the app?)"
    fi
  done
  # The login wall lets /app/assets/ through and spa_index answers any /app/ path, so an unknown
  # asset gets the SPA shell (code references only, no data), not a 404. Reported for item 41a.
  status="$(request GET "$canonical" /app/assets/nope.js)"
  if [ "$status" = 404 ]; then
    pass "GET /app/assets/nope.js 404"
  elif [ "$status" = 200 ] && grep -q '<div id="root"></div>' "$work/body" && from_app; then
    note "GET /app/assets/nope.js: 200 with the SPA shell (no data)"
  else
    fail "GET /app/assets/nope.js answered $status"
  fi
  status="$(request GET "$canonical" /robots.txt)"
  if [ "$status" = 200 ] && [ "$mode" = remote ]; then
    # Cloudflare's managed robots.txt answers when the origin has none (the app has none).
    grep -qi '^user-agent:' "$work/body" && ! from_app &&
      pass "GET /robots.txt 200 (Cloudflare's managed file)" ||
      fail "GET /robots.txt 200 but not Cloudflare's managed file"
  elif [ "$status" = 404 ]; then
    pass "GET /robots.txt 404 (the app serves none)"
  else
    fail "GET /robots.txt answered $status"
  fi
}

check_redirect() {
  [ -n "$other" ] || return 0
  echo "The other public name ($other -> $canonical):"
  local status
  status="$(request GET "$other" '/app/trips?year=2024')"
  if [ "$status" = 404 ] && ! from_app && [ "$scope" = tracker ]; then
    note "Cloudflare 404 for $other/app/trips (no route for it yet, or a tracker-only path rule)"
  else
    expect "GET https://$other/app/trips?year=2024" 301 "$status"
    expect "  to the same path on $canonical" "https://$canonical/app/trips?year=2024" "$(header location)"
    request GET "$other" / >/dev/null
    expect "GET https://$other/" "https://$canonical/" "$(header location)"
    request GET "$other" //evil.example >/dev/null
    expect "GET https://$other//evil.example (not an open redirect)" "https://$canonical//evil.example" "$(header location)"
    request GET "$other" '/auth/login?next=https://evil.example' >/dev/null
    expect "GET https://$other/auth/login?next=… stays on $canonical" \
      "https://$canonical/auth/login?next=https://evil.example" "$(header location)"
  fi
}

check_ingest() {  # token (may be empty)
  local token="$1" host status auth
  bogus="trk_$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n' | head -c 43)"
  printf '{"_type":"lwt","tst":%s}' "$(date +%s)" > "$work/lwt.json"
  printf '{"locations":[]}' > "$work/empty.json"
  for host in "$canonical" ${other:+"$other"}; do
    echo "The tracker endpoints, unchanged ($host):"
    expect "GET /api/v1/ingest/owntracks (POST only)" 405 "$(request GET "$host" /api/v1/ingest/owntracks)"
    status="$(request POST "$host" /api/v1/ingest/owntracks "header = \"Authorization: Bearer $bogus\"" \
      'header = "Content-Type: application/json"' "data-binary = \"@$work/lwt.json\"")"
    expect "OwnTracks, bogus token in the header" 401 "$status"
    production_headers "OwnTracks 401"
    [[ "$(header cache-control)" == *no-store* ]] && pass "  Cache-Control: no-store" || fail "  Cache-Control: no-store missing"
    status="$(request POST "$host" "/api/v1/ingest/overland/?token=$bogus" \
      'header = "Content-Type: application/json"' "data-binary = \"@$work/empty.json\"")"
    expect "Overland (trailing slash), bogus token in the query" 401 "$status"
    if [ -n "$token" ]; then
      auth="$(printf 'smoke:%s' "$token" | base64 -w0)"
      status="$(request POST "$host" /api/v1/ingest/owntracks "header = \"Authorization: Basic $auth\"" \
        'header = "Content-Type: application/json"' "data-binary = \"@$work/lwt.json\"")"
      expect "OwnTracks with the token (Basic auth, as the app sends it)" 200 "$status"
      expect "  answers []" "[]" "$(cat "$work/body")"
      status="$(request POST "$host" "/api/v1/ingest/overland?token=$token" \
        'header = "Content-Type: application/json"' "data-binary = \"@$work/empty.json\"")"
      if [ "$status" = 401 ] && [ "$mode" = remote ]; then
        note "Overland refused this token: its kind is OwnTracks or GPSLogger (fine)"
      else
        expect "Overland with the token in the query" 200 "$status"
        expect "  answers {\"result\":\"ok\"}" '{"result":"ok"}' "$(cat "$work/body")"
      fi
    fi
  done
  [ -n "$token" ] || echo "  (no test token: skipped the accepted-token checks)"
  if [ "$mode" = local ]; then
    # Through the tunnel this needs "Disable Chunked Encoding" on the route (docs/go-live.md).
    status="$(request POST "$canonical" /api/v1/ingest/owntracks "header = \"Authorization: Bearer $bogus\"" \
      'header = "Content-Type: application/json"' 'header = "Transfer-Encoding: chunked"' \
      "data-binary = \"@$work/lwt.json\"")"
    expect "a chunked body is refused (411)" 411 "$status"
  fi
}

check_logs() {  # log-file token
  local log="$1" token="$2"
  echo "Tokens stay out of the logs:"
  if [ ! -s "$log" ]; then
    note "no log to read here (run from the server's main checkout to scan production's)"
    return 0
  fi
  grep -qF "$bogus" "$log" && fail "the bogus token is in the log" ||
    pass "bogus token not in the log ($(wc -l < "$log") lines read)"
  if [ -n "$token" ]; then
    grep -qF "$token" "$log" && fail "THE TEST TOKEN IS IN THE LOG (revoke it)" || pass "test token not in the log"
  fi
  grep -qE 'trk_[A-Za-z0-9_-]{8}' "$log" && fail "something token-shaped is in the log" ||
    pass "nothing token-shaped in the log"
}

check_local_stack() {
  echo "The throwaway stack ($LOCAL_PROJECT):"
  local web db port
  web="$(local_compose ps -q web)"
  db="$(local_compose ps -q db)"
  port="$(cat "$LOCAL_DIR/port")"
  expect "web runs the local image" "travel-history-backend:$LOCAL_TAG" "$(docker inspect -f '{{.Config.Image}}' "$web")"
  [[ "$(docker inspect -f '{{json .Config.Cmd}}' "$web")" == *gunicorn* ]] && pass "web runs gunicorn" || fail "web does not run gunicorn"
  expect "web is published on 127.0.0.1:$port only" "127.0.0.1:$port" \
    "$(docker port "$web" 8000/tcp | tr '\n' ' ' | sed 's/ $//')"
  expect "db publishes no ports" "" "$(docker port "$db")"
  local users
  users="$(docker inspect -f '{{.Config.User}}' "$web" "$db" | tr '\n' ' ' | sed 's/ $//')"
  if grep -qE '(^| )(0|root)?(:| |$)' <<<"$users"; then fail "a container runs as root ($users)"; else pass "web and db run non-root ($users)"; fi
  expect "the scope is all" all "$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$web" | sed -n 's/^TRAVEL_PUBLIC_SCOPE=//p')"
  [ "$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$web" | sed -n 's/^TRAVEL_PRODUCTION=//p')" = true ] &&
    pass "TRAVEL_PRODUCTION (settings refuse to start without auth.md §7.7)" || fail "TRAVEL_PRODUCTION not set"
  if local_compose --profile tools run --rm --no-deps -T tools \
    python manage.py check --deploy --fail-level WARNING > "$work/check" 2>&1; then
    pass "Django's deploy checks pass"
  else
    fail "Django's deploy checks: $(grep -E '^\?: \(' "$work/check" | cut -c1-90 | tr '\n' ' ')"
  fi
  expect "sessions go back through the provider hourly (F-3)" 3600 \
    "$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$web" | sed -n 's/^OIDC_SESSION_RECHECK_SECONDS=//p')"
  # F-9: scope `all` without the provider must not start.
  if local_compose --profile tools run --rm --no-deps -T -e OIDC_ISSUER= tools \
    python manage.py check > "$work/no-issuer" 2>&1; then
    fail "scope all started without OIDC_ISSUER"
  elif grep -q "must be set once TRAVEL_PUBLIC_SCOPE=all" "$work/no-issuer"; then
    pass "scope all refuses to start without OIDC_ISSUER (F-9)"
  else
    fail "scope all without OIDC_ISSUER: $(tail -1 "$work/no-issuer" | cut -c1-90)"
  fi
}

# A synthetic Member with a trip and two sessions in the throwaway database: one the provider
# vouched for just now, one two hours ago. Prints: account trip fresh-session stale-session.
local_sessions() {
  if ! local_compose --profile tools run --rm --no-deps -T tools python manage.py shell \
    >"$work/sessions.log" 2>&1 <<'PY'
import datetime as dt, time
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from travel.accounts.models import User
from travel.trips.models import Trip
user, _ = User.objects.get_or_create(email="golive-smoke-member@example.invalid", defaults={"display_name": "SYNTHETIC smoke member"})
user.set_unusable_password(); user.save()
trip = Trip.objects.create(owner=user, title="SYNTHETIC smoke trip", start_date=dt.date(2024, 1, 1), end_date=dt.date(2024, 1, 2))
def session(checked):
    s = SessionStore()
    s[SESSION_KEY], s[BACKEND_SESSION_KEY] = str(user.pk), "django.contrib.auth.backends.ModelBackend"
    s[HASH_SESSION_KEY], s["oidc_checked_at"] = user.get_session_auth_hash(), checked
    s.create()
    return s.session_key
print("SMOKE", user.pk, trip.pk, session(int(time.time())), session(int(time.time()) - 7200))
PY
  then
    cat "$work/sessions.log" >&2
    die "could not create the synthetic sessions"
  fi
  grep '^SMOKE ' "$work/sessions.log" | cut -d' ' -f2-
}

check_signed_in() {  # local only: a signed-in Member, as the session cookie makes one
  echo "Signed in (a synthetic Member's sessions in the throwaway database):"
  local account trip fresh stale csrf
  read -r account trip fresh stale < <(local_sessions)
  csrf="$(head -c 96 /dev/urandom | base64 -w0 | tr -dc 'A-Za-z0-9' | head -c 32)"
  signed() {  # session method path [json]
    local key="$1" method="$2" path="$3"
    local extra=("header = \"Cookie: sessionid=$key; csrftoken=$csrf\"" "header = \"X-CSRFToken: $csrf\""
      "header = \"Origin: https://$canonical\"" 'header = "Content-Type: application/json"')
    [ -n "${4:-}" ] && extra+=("data = \"${4//\"/\\\"}\"")
    request "$method" "$canonical" "$path" "${extra[@]}"
  }
  expect "GET /api/v1/me with the session" 200 "$(signed "$fresh" GET /api/v1/me)"
  # F-10: nothing becomes public before T37.
  expect "POST /api/v1/trips with visibility public: 422 (F-10)" 422 \
    "$(signed "$fresh" POST /api/v1/trips '{"title":"SYNTHETIC","start_date":"2024-01-01","end_date":"2024-01-02","visibility":"public"}')"
  expect "PATCH /api/v1/trips/$trip to public: 422" 422 \
    "$(signed "$fresh" PATCH "/api/v1/trips/$trip" '{"visibility":"public"}')"
  expect "POST /api/v1/trips/bulk to public: 422" 422 \
    "$(signed "$fresh" POST /api/v1/trips/bulk "{\"trip_ids\":[$trip],\"visibility\":\"public\"}")"
  expect "PATCH /api/v1/trips/$trip to family still works" 200 \
    "$(signed "$fresh" PATCH "/api/v1/trips/$trip" '{"visibility":"family"}')"
  # F-3: a session the provider last vouched for two hours ago is signed out.
  expect "a session past the hourly provider check: 401 (F-3)" 401 "$(signed "$stale" GET /api/v1/me)"
  grep -q "fresh check with the sign-in provider" "$work/body" && pass "  says why" || fail "  no reason given"
  expect "  and it is gone" 401 "$(signed "$stale" GET /api/v1/me)"
  # F-3: deactivate_account ends the account's access at once.
  if local_compose --profile tools run --rm --no-deps -T tools \
    python manage.py deactivate_account "$account" --execute >"$work/deactivate" 2>&1; then
    pass "deactivate_account $account --execute (owner role)"
  else
    fail "deactivate_account: $(tail -1 "$work/deactivate" | cut -c1-90)"
  fi
  expect "  its session answers 401" 401 "$(signed "$fresh" GET /api/v1/me)"
}

run_checks() {  # token log-command...
  local token="$1"
  shift
  local started
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ "$scope" = all ]; then
    check_landing
    check_sign_in
    check_private
  else
    echo "Before go-live: everything but the tracker paths is 404 ($canonical):"
    local path
    for path in / /healthz /app/ /auth/login /api/v1/me; do
      expect "GET $path" 404 "$(request GET "$canonical" "$path")"
    done
  fi
  check_not_found
  check_redirect
  check_ingest "$token"
  sleep 1
  "$@" "$started" > "$work/log" 2>&1 || true
  check_logs "$work/log" "$token"
}

local_logs() { local_compose logs --no-color --since "$1" web; }
prod_logs() {  # since: production's web and ingest, read-only, only from the main checkout
  in_worktree && return 0
  local c
  for c in "$PROD_PROJECT-web-1" "$PROD_PROJECT-ingest-1"; do
    docker logs --since "$1" "$c" 2>&1 || true
  done
}

local_checks() {
  mode=local
  base="http://127.0.0.1:$(cat "$LOCAL_DIR/port")"
  canonical="$(env_file_value "$LOCAL_ENV" TRAVEL_CANONICAL_HOST)"
  other="$(env_file_value "$LOCAL_ENV" TRAVEL_PUBLIC_HOSTS | tr ',' '\n' | grep -vx "$canonical" | head -1 || true)"
  echo "Go-live smoke test, local: $base as https://$canonical (scope all, commit $(head -c 12 "$LOCAL_RELEASE/.commit"))"
  check_local_stack
  local token
  token="$(local_token)"
  run_checks "$token" local_logs
  check_signed_in
}

finish() {
  if [ "$failures" -eq 0 ]; then echo "PASS"; else echo "$failures check(s) FAILED"; return 1; fi
}

cmd="${1:-help}"
shift || true
case "$cmd" in
  local)
    keep=false
    port="$(default_port)"
    issuer="$PLACEHOLDER_ISSUER"
    while [ $# -gt 0 ]; do
      case "$1" in
        --keep) keep=true ;;
        --port) port="$2"; shift ;;
        --issuer) issuer="$2"; shift ;;
        *) die "unknown option $1" ;;
      esac
      shift
    done
    [[ "$issuer" == https://* ]] || die "--issuer must be https:// (production refuses anything else)"
    $keep || trap 'local_down; rm -rf "$work"' EXIT
    local_up "$port" "$issuer" || exit 1
    status=0
    local_checks || status=$?
    finish || status=1
    if $keep; then
      echo "left running: http://127.0.0.1:$port (send Host: $canonical and X-Forwarded-Proto: https);"
      echo "  again: ./dev golive-smoke local-check   remove: ./dev golive-smoke local-down"
    fi
    exit "$status"
    ;;
  local-check)
    [ -f "$LOCAL_ENV" ] || die "no local go-live stack: run ./dev golive-smoke local --keep"
    local_checks
    finish
    ;;
  local-down) local_down ;;
  https://*)
    mode=remote
    canonical="${cmd#https://}"
    canonical="${canonical%%/*}"
    [[ "$canonical" == travel.* ]] && other="trips.${canonical#travel.}"
    while [ $# -gt 0 ]; do
      case "$1" in
        --scope) scope="$2"; shift ;;
        --other) other="$2"; shift ;;
        --no-other) other="" ;;
        *) die "unknown option $1" ;;
      esac
      shift
    done
    [[ "$scope" =~ ^(all|tracker)$ ]] || die "--scope is all or tracker"
    token="${TRACKER_SMOKE_TOKEN:-}"
    if [ -z "$token" ] && [ -t 0 ]; then
      read -rsp "Tracker test token (Enter to skip the token checks): " token
      echo
    fi
    echo "Go-live smoke test through Cloudflare: https://$canonical${other:+ and $other} (scope $scope)"
    run_checks "$token" prod_logs
    finish
    ;;
  -h | --help | help) usage ;;
  *) usage; exit 2 ;;
esac
