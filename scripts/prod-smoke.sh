#!/usr/bin/env bash
# Local smoke test of the production stack (work-order item 40a, D-96, docs/production.md):
#
#   ./dev prod smoke
#
# Calls the production web service on 127.0.0.1:8784 the way the tunnel and an SSH port-forward
# would, and inspects the containers:
# - the stack: deployed from a release, not the working tree; gunicorn, no dev services, no
#   source mounts; non-root; DB unpublished on an internal network only production joins;
#   web published on 127.0.0.1:8784 only; .env.prod 0600; bulk storage outside the repository;
# - the landing page and /healthz answer with production headers; the landing page offers only
#   "Sign in"; plain HTTP through the tunnel is redirected, plain HTTP on localhost (the SSH
#   port-forward, G-4) is served; unknown hosts are refused without DEBUG's error page;
# - every API operation in the release's OpenAPI schema and the private pages refuse anonymous
#   requests;
# - the public names: before go-live only the tracker paths answer on the canonical one; the
#   other names redirect to the same path on it, tracker paths excepted;
# - the development stack never answers a public name.
# Nothing is stored. Exits non-zero if any check fails.
set -euo pipefail
# shellcheck source=scripts/stack.sh
source "$(dirname "$0")/stack.sh"
cd "$REPO_ROOT"

base="http://127.0.0.1:$PROD_WEB_PORT"
prod_check_env_file
commit="$(prod_commit)"
[ -n "$commit" ] || die "nothing deployed yet: run ./dev prod deploy"
canonical="$(prod_env_value TRAVEL_CANONICAL_HOST)"
hosts="$(prod_env_value TRAVEL_PUBLIC_HOSTS)"
canonical="${canonical:-${hosts%%,*}}"
others="$(tr ',' '\n' <<<"$hosts" | grep -vx "$canonical" | head -1 || true)"
scope="$(prod_env_value TRAVEL_PUBLIC_SCOPE)"
bulk="$(prod_env_value TRAVEL_BULK_DIR)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
chmod 700 "$work"
failures=0
pass() { printf '  ok    %s\n' "$1"; }
fail() {
  printf '  FAIL  %s\n' "$1"
  failures=$((failures + 1))
}
expect() {  # description expected actual
  if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (got $3, expected $2)"; fi
}

# request METHOD URL-PATH HOST [extra curl config lines...]: status code on stdout.
request() {
  local method="$1" path="$2" host="$3"
  shift 3
  {
    printf 'url = "%s%s"\n' "$base" "$path"
    printf 'request = "%s"\n' "$method"
    printf 'header = "Host: %s"\n' "$host"
    local line
    for line in "$@"; do printf '%s\n' "$line"; done
  } | curl --silent --show-error --max-time 20 --output "$work/body" --dump-header "$work/headers" \
    --write-out '%{http_code}' --config - || true
}
https='header = "X-Forwarded-Proto: https"'
tunnel_http=('header = "X-Forwarded-Proto: http"' 'header = "CF-Connecting-IP: 203.0.113.1"')
header() { grep -i "^$1:" "$work/headers" | tail -1 | cut -d: -f2- | tr -d '\r' | sed 's/^ *//'; }

production_headers() {  # description
  local missing=()
  [[ "$(header strict-transport-security)" == max-age=* ]] || missing+=("HSTS")
  [ "$(header x-content-type-options)" = nosniff ] || missing+=("nosniff")
  [ "$(header x-frame-options)" = DENY ] || missing+=("X-Frame-Options")
  [ "$(header referrer-policy)" = same-origin ] || missing+=("Referrer-Policy")
  [ "$(header cross-origin-opener-policy)" = same-origin ] || missing+=("COOP")
  local csp
  csp="$(header content-security-policy)"
  [[ "$csp" == *"default-src"* && "$csp" == *"frame-ancestors 'none'"* ]] || missing+=("CSP")
  grep -qi '^set-cookie:' "$work/headers" && missing+=("no cookies")
  if [ ${#missing[@]} -eq 0 ]; then pass "$1: production headers"; else fail "$1: missing ${missing[*]}"; fi
}

echo "Production smoke test: $base (deployed ${commit:0:12}, scope ${scope:-tracker})"

echo "The stack:"
container() { prod_compose --profile tracker ps -q "$1" 2>/dev/null || true; }
web="$(container web)"
db="$(container db)"
[ -n "$web" ] && pass "web is running" || fail "web is not running"
[ -n "$db" ] && pass "db is running" || fail "db is not running"
expect "web runs the release image" "travel-history-backend:${commit:0:12}" \
  "$(docker inspect -f '{{.Config.Image}}' "$web" 2>/dev/null)"
[[ "$(docker inspect -f '{{json .Config.Cmd}}' "$web" 2>/dev/null)" == *gunicorn* ]] \
  && pass "web runs gunicorn" || fail "web does not run gunicorn"
expect "web is published on 127.0.0.1:$PROD_WEB_PORT only" "127.0.0.1:$PROD_WEB_PORT" \
  "$(docker port "$web" 8000/tcp 2>/dev/null | tr '\n' ' ' | sed 's/ $//')"
expect "db publishes no ports" "" "$(docker port "$db" 2>/dev/null)"
services="$(prod_compose --profile tracker --profile tools ps --services 2>/dev/null | sort | tr '\n' ' ')"
for dev_only in oidc mail frontend; do
  [[ " $services " == *" $dev_only "* ]] && fail "dev-only service $dev_only runs in production"
done
pass "no mock OIDC, Mailpit or Vite (running: ${services% })"
root_or_source=()
for id in $(prod_compose --profile tracker --profile tools ps -q 2>/dev/null); do
  name="$(docker inspect -f '{{.Name}}' "$id")"
  user="$(docker inspect -f '{{.Config.User}}' "$id")"
  [[ -z "$user" || "$user" == 0* || "$user" == root* ]] && root_or_source+=("$name runs as root")
  docker inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$id" \
    | grep -q "^$REPO_ROOT\(/\|$\)" && root_or_source+=("$name mounts the working tree")
done
if [ ${#root_or_source[@]} -eq 0 ]; then
  pass "containers run non-root and mount nothing from the working tree"
else
  fail "${root_or_source[*]}"
fi
internal="${PROD_PROJECT}_internal"
expect "the database network is internal" true "$(docker network inspect -f '{{.Internal}}' "$internal" 2>/dev/null)"
expect "db joins only $internal" "$internal" \
  "$(docker inspect -f '{{range $n, $_ := .NetworkSettings.Networks}}{{$n}} {{end}}' "$db" 2>/dev/null | sed 's/ $//')"
strangers="$(docker network inspect -f '{{range .Containers}}{{.Name}} {{end}}' "$internal" 2>/dev/null \
  | tr ' ' '\n' | grep -v "^${PROD_PROJECT}-" | grep -v '^$' || true)"
expect "only production containers share the database network" "" "$strangers"
expect ".env.prod is mode 0600" 600 "$(stat -c %a "$PROD_ENV_FILE")"
if prod_compose --profile tools run --rm --no-deps -T tools \
  python manage.py check --deploy --fail-level WARNING > "$work/check" 2>&1; then
  pass "Django's deploy checks pass"
else
  fail "Django's deploy checks: $(grep -E '^\?: \(' "$work/check" | cut -c1-90 | tr '\n' ' ')"
fi
if [ -d "$bulk" ] && ! git -C "$bulk" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  pass "bulk storage outside any git working tree ($bulk)"
else
  fail "bulk storage $bulk is missing or inside a git working tree"
fi

echo "Health and the landing page:"
expect "GET /healthz (plain HTTP, as the health check)" 200 "$(request GET /healthz "127.0.0.1:$PROD_WEB_PORT")"
expect "  answers ok" '{"status": "ok"}' "$(cat "$work/body")"
expect "GET / over HTTPS" 200 "$(request GET / "localhost:$PROD_WEB_PORT" "$https")"
production_headers "landing page"
links="$(grep -o 'href="[^"]*"' "$work/body" | sort -u | tr '\n' ' ' | sed 's/ $//')"
expect "  offers only Sign in" 'href="/auth/login"' "$links"
grep -q '<form' "$work/body" && fail "  the landing page has a form" || pass "  no forms"
grep -q 'name="robots" content="noindex, nofollow"' "$work/body" && pass "  noindex" || fail "  noindex missing"
expect "GET / over plain HTTP through the tunnel is redirected" 301 \
  "$(request GET / "$canonical" "${tunnel_http[@]}")"
expect "  to HTTPS" "https://$canonical/" "$(header location)"
expect "  also with a loopback Host header" 301 \
  "$(request GET / "localhost:$PROD_WEB_PORT" "${tunnel_http[@]}")"
expect "GET / over plain HTTP on localhost (the SSH port-forward, G-4) is served" 200 \
  "$(request GET / "localhost:$PROD_WEB_PORT")"
[ -z "$(header strict-transport-security)" ] && pass "  without HSTS" || fail "  sent HSTS over plain HTTP"
expect "unknown Host refused" 400 "$(request GET / evil.example "$https")"
grep -qiE 'traceback|DisallowedHost|settings' "$work/body" && fail "  DEBUG's error page" || pass "  without DEBUG's error page"
expect "the SPA build is served (manifest)" 200 \
  "$(request GET /app/manifest.webmanifest "localhost:$PROD_WEB_PORT" "$https")"

echo "Private paths refuse anonymous requests:"
for path in /app/ /app/trips /auth/reauth /auth/logout; do
  status="$(request GET "$path" "localhost:$PROD_WEB_PORT" "$https")"
  location="$(header location)"
  if [ "$status" = 302 ] && [[ "$location" == /auth/login* ]]; then pass "GET $path -> sign in"; else fail "GET $path ($status $location)"; fi
done
operations="$(python3 - "$PROD_RELEASE/frontend/src/api/openapi.json" <<'PY'
import json, re, sys
paths = json.load(open(sys.argv[1]))["paths"]
for path, ops in sorted(paths.items()):
    concrete = re.sub(r"\{[^}]+\}", "1", path)
    for method in sorted(ops):
        if method in ("get", "post", "put", "patch", "delete"):
            print(method.upper(), concrete)
PY
)"
refused=0
total=0
while read -r method path; do
  total=$((total + 1))
  status="$(request "$method" "$path" "localhost:$PROD_WEB_PORT" "$https" 'header = "Content-Type: application/json"' 'data = "{}"')"
  if [ "$status" = 401 ]; then refused=$((refused + 1)); else fail "$method $path answered $status"; fi
done <<<"$operations"
expect "every API operation in the schema answers 401 ($total)" "$total" "$refused"
[ "$total" -gt 40 ] || fail "too few API operations found ($total)"

echo "Public names ($canonical${others:+, $others}):"
if [ "${scope:-tracker}" = tracker ]; then
  for path in / /healthz /app/ /auth/login /api/v1/me; do
    expect "GET https://$canonical$path (before go-live)" 404 "$(request GET "$path" "$canonical" "$https")"
  done
  production_headers "404 on $canonical"
fi
expect "POST $canonical/api/v1/ingest/owntracks without a token" 401 \
  "$(request POST /api/v1/ingest/owntracks "$canonical" "$https" 'header = "Content-Type: application/json"' 'data = "{}"')"
if [ -n "$others" ]; then
  expect "GET https://$others/app/trips?year=2024" 301 "$(request GET '/app/trips?year=2024' "$others" "$https")"
  expect "  to the same path on $canonical" "https://$canonical/app/trips?year=2024" "$(header location)"
  expect "GET https://$others//evil.example (not an open redirect)" "https://$canonical//evil.example" \
    "$( request GET //evil.example "$others" "$https" >/dev/null; header location)"
  expect "POST $others/api/v1/ingest/overland is served, not redirected" 401 \
    "$(request POST /api/v1/ingest/overland "$others" "$https" 'header = "Content-Type: application/json"' 'data = "{}"')"
fi

echo "The development stack never answers a public name:"
if curl --silent --max-time 5 -o /dev/null http://127.0.0.1:8780/healthz; then
  for host in "$canonical" ${others:+"$others"}; do
    status="$(curl --silent --max-time 10 -o /dev/null -w '%{http_code}' -H "Host: $host" http://127.0.0.1:8780/healthz || true)"
    expect "dev 127.0.0.1:8780 with Host $host" 404 "$status"
  done
else
  echo "  skip  the dev stack isn't running"
fi

if [ "$failures" -eq 0 ]; then
  echo "PASS"
else
  echo "$failures check(s) FAILED"
  exit 1
fi
