#!/usr/bin/env bash
# Smoke test of the internet-facing tracker endpoint (work-order item 8, docs/tracking/exposure.md).
#
#   ./dev prod tracker smoke                    the local `ingest` service (127.0.0.1:8783), as
#                                               the tunnel would call it
#   ./dev prod tracker smoke https://<host>     through Cloudflare and the tunnel (after "go")
#
# The `ingest` service belongs to the production stack (D-96); its settings come from .env.prod.
#
# Checks: every other path answers 404; the tracker endpoints answer, with HSTS and the other
# security headers and no cookies; a bogus token is refused; locally, plain HTTP is redirected
# and unknown hosts are refused. With a test token (TRACKER_SMOKE_TOKEN, or typed at the hidden
# prompt) it also sends one OwnTracks message and one Overland batch that store nothing (an
# OwnTracks `lwt` and an empty Overland batch), unless --store is given, which stores one
# synthetic point (use it only with a synthetic account). Finally it searches the `ingest`
# service's log for both tokens. Tokens never appear on a command line: curl reads its
# options, URLs and headers included, from standard input.
set -euo pipefail
# shellcheck source=scripts/stack.sh
source "$(dirname "$0")/stack.sh"
cd "$REPO_ROOT"

store=false
base=""
for arg in "$@"; do
  case "$arg" in
    --store) store=true ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) base="$arg" ;;
  esac
done
base="${base:-http://127.0.0.1:8783}"
base="${base%/}"

public_host="$(prod_env_value TRAVEL_PUBLIC_HOSTS | cut -d, -f1)"
local_mode=false
extra_headers=()
if [[ "$base" == http://127.0.0.1:* || "$base" == http://localhost:* ]]; then
  local_mode=true
  if [ -z "$public_host" ]; then
    echo "TRAVEL_PUBLIC_HOSTS is not set in $PROD_ENV_FILE" >&2
    exit 2
  fi
  # What cloudflared adds: the public Host, the visitor's scheme and address (TEST-NET-1).
  extra_headers=("Host: $public_host" "X-Forwarded-Proto: https" "CF-Connecting-IP: 192.0.2.10")
fi

token="${TRACKER_SMOKE_TOKEN:-}"
if [ -z "$token" ] && [ -t 0 ]; then
  read -rsp "Test token (Enter to skip the token checks): " token
  echo
fi
bogus="trk_$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n' | head -c 43)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
chmod 700 "$work"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
failures=0

# request METHOD PATH [curl config line...]: status code on stdout; headers and body in $work.
request() {
  local method="$1" path="$2"
  shift 2
  {
    printf 'url = "%s%s"\n' "$base" "$path"
    printf 'request = "%s"\n' "$method"
    local header
    for header in "${extra_headers[@]}"; do printf 'header = "%s"\n' "$header"; done
    local line
    for line in "$@"; do printf '%s\n' "$line"; done
  } | curl --silent --show-error --max-time 20 --output "$work/body" --dump-header "$work/headers" \
    --write-out '%{http_code}' --config - || true  # curl prints 000 when it gets no answer
}

pass() { printf '  ok    %s\n' "$1"; }
fail() {
  printf '  FAIL  %s\n' "$1"
  failures=$((failures + 1))
}
expect() {  # description expected actual
  if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (got $3, expected $2)"; fi
}
header() { grep -i "^$1:" "$work/headers" | tail -1 | cut -d: -f2- | tr -d '\r' | sed 's/^ *//'; }

security_headers() {  # description
  local missing=()
  [[ "$(header strict-transport-security)" == max-age=* ]] || missing+=("HSTS")
  [ "$(header x-content-type-options)" = "nosniff" ] || missing+=("nosniff")
  [ "$(header x-frame-options)" = "DENY" ] || missing+=("X-Frame-Options")
  [ -n "$(header referrer-policy)" ] || missing+=("Referrer-Policy")
  [[ "$(header content-security-policy)" == *"frame-ancestors 'none'"* ]] || missing+=("CSP")
  [[ "$(header cache-control)" == *no-store* ]] || missing+=("Cache-Control: no-store")
  # Cloudflare may add its own __cf* cookies; the app must set none.
  if grep -i '^set-cookie:' "$work/headers" | grep -vqi 'set-cookie: *__cf'; then
    missing+=("no app cookies")
  fi
  if [ ${#missing[@]} -eq 0 ]; then pass "$1: security headers"; else fail "$1: missing ${missing[*]}"; fi
}

echo "Tracker endpoint smoke test: $base$($local_mode && echo " (Host: $public_host)")"

echo "Everything else is 404:"
for path in / /healthz /app/ /app/trackers /app/assets/index.js /app/manifest.webmanifest \
  /static/admin/x.css /robots.txt /favicon.ico /auth/login /api/v1/ /api/v1/me \
  /api/v1/openapi.json /api/v1/docs /api/v1/tracking/tokens /api/v1/ingest/ \
  /api/v1/ingest/owntracksx /admin/ /.env; do
  expect "GET $path" 404 "$(request GET "$path")"
done
expect "POST /api/v1/tracking/tokens" 404 "$(request POST /api/v1/tracking/tokens)"
security_headers "404"

echo "The tracker endpoints answer:"
expect "GET /api/v1/ingest/owntracks (POST only)" 405 "$(request GET /api/v1/ingest/owntracks)"
printf '{"_type":"lwt","tst":%s}' "$(date +%s)" > "$work/lwt.json"
status="$(request POST /api/v1/ingest/owntracks "header = \"Authorization: Bearer $bogus\"" \
  'header = "Content-Type: application/json"' "data-binary = \"@$work/lwt.json\"")"
expect "OwnTracks, bogus token in the header" 401 "$status"
security_headers "OwnTracks 401"
printf '{"locations":[]}' > "$work/empty.json"
status="$(request POST "/api/v1/ingest/overland?token=$bogus" \
  'header = "Content-Type: application/json"' "data-binary = \"@$work/empty.json\"")"
expect "Overland, bogus token in the query" 401 "$status"

if $local_mode; then
  echo "Local only (what the tunnel can't send):"
  saved=("${extra_headers[@]}")
  extra_headers=("Host: $public_host" "X-Forwarded-Proto: http")
  status="$(request POST /api/v1/ingest/owntracks)"
  expect "plain HTTP is redirected" 301 "$status"
  expect "  to HTTPS" "https://$public_host/api/v1/ingest/owntracks" "$(header location)"
  extra_headers=("Host: unknown.example" "X-Forwarded-Proto: https")
  expect "unknown Host refused" 400 "$(request POST /api/v1/ingest/owntracks)"
  extra_headers=("Host: localhost" "X-Forwarded-Proto: https")
  expect "other hosts: still only the tracker endpoints" 404 "$(request GET /healthz)"
  extra_headers=("${saved[@]}")
fi

if [ -n "$token" ]; then
  echo "With the test token:"
  auth="$(printf 'smoke:%s' "$token" | base64 -w0)"
  status="$(request POST /api/v1/ingest/owntracks "header = \"Authorization: Basic $auth\"" \
    'header = "Content-Type: application/json"' "data-binary = \"@$work/lwt.json\"")"
  expect "OwnTracks (Basic auth, as the app sends it)" 200 "$status"
  expect "  answers []" "[]" "$(cat "$work/body")"
  security_headers "OwnTracks 200"
  status="$(request POST "/api/v1/ingest/overland?token=$token" \
    'header = "Content-Type: application/json"' "data-binary = \"@$work/empty.json\"")"
  if [ "$status" = 401 ]; then
    echo "  note  Overland refused this token: its kind is OwnTracks or GPSLogger (fine)"
  else
    expect "Overland (token in the query, as some versions send it)" 200 "$status"
    expect "  answers {\"result\":\"ok\"}" '{"result":"ok"}' "$(cat "$work/body")"
  fi
  if $store; then
    # Synthetic point: Wichita city centre, one minute ago.
    printf '{"_type":"location","lat":37.6922,"lon":-97.3375,"tst":%s,"acc":10}' \
      "$(($(date +%s) - 60))" > "$work/point.json"
    status="$(request POST /api/v1/ingest/owntracks "header = \"Authorization: Bearer $token\"" \
      'header = "Content-Type: application/json"' "data-binary = \"@$work/point.json\"")"
    expect "one synthetic point stored" 200 "$status"
  fi
else
  echo "(no test token: skipped the accepted-token checks)"
fi

echo "Tokens stay out of the logs:"
sleep 1
if prod_compose --profile tracker logs --no-color --since "$started" ingest > "$work/log" \
  2>/dev/null && [ -s "$work/log" ]; then
  if grep -qF "$bogus" "$work/log"; then
    fail "the bogus token is in the ingest log"
  else
    pass "bogus token not in the ingest log ($(wc -l < "$work/log") lines read)"
  fi
  if [ -n "$token" ]; then
    if grep -qF -e "$token" -e "$auth" "$work/log"; then
      fail "THE TEST TOKEN IS IN THE INGEST LOG (revoke it)"
    else
      pass "test token (plain or Basic-encoded) not in the ingest log"
    fi
  fi
  if grep -qE 'trk_[A-Za-z0-9_-]{8}' "$work/log"; then
    fail "something token-shaped is in the ingest log"
  else
    pass "nothing token-shaped in the ingest log"
  fi
else
  fail "could not read the ingest service's log (is it running on this server?)"
fi

if [ "$failures" -eq 0 ]; then
  echo "PASS"
else
  echo "$failures check(s) FAILED"
  exit 1
fi
