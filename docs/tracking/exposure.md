# Tracker exposure: making the tracker endpoints reachable from the internet

Work-order item 8, decisions D-73 and D-85. Until go-live (Authentik with 2FA, phase 8), only the
two tracker endpoints are reachable from the internet, at `https://travel.adamcasada.com`:

- `POST /api/v1/ingest/owntracks`
- `POST /api/v1/ingest/overland`

A trailing slash is accepted on both. Every other path on that hostname answers 404. The rest of
the app stays LAN/VPN-only.

## How it fits together

```
phone ── HTTPS ── Cloudflare edge ── main tunnel ── cloudflared (host network)
      ── http://localhost:8783 ── `ingest` container ── db
```

- **The same public path as the other sites.** Traffic goes through the shared,
  dashboard-managed tunnel that already serves the bible, pinpoint, adsb, ntfy and auth
  sites (`~/infra/cloudflared`; routes are listed in `~/infra/TUNNELS.md`). There's no new
  tunnel and no `cloudflared` container of this app's own. No router port forwards are involved.
- **Cloudflare terminates TLS.** HTTPS ends at Cloudflare's edge. From there the request travels
  through the tunnel to `cloudflared` on this server, then over plain HTTP on localhost to the
  app. **So Cloudflare can see, in clear text and in transit, every device token and every
  location payload.** Tokens travel in the `Authorization` header, or in the URL for Overland
  setups that use `?token=`. Payloads hold the position, time, accuracy, speed and battery.
  This is the same trust you already place in Cloudflare for the other sites. Nothing is stored
  at Cloudflare on purpose, but it is in the path.
- **The `ingest` service** (in `compose.yaml`, profile `tracker`) runs the production image with
  production settings and answers only the two tracker paths, whatever the Host header says.
  It is published on `127.0.0.1:8783` only. It has no bulk storage, a read-only root
  filesystem, no OIDC or SMTP secrets, and dropped capabilities.
- **The dev stack is untouched.** It keeps `127.0.0.1:8780` and the LAN address. `./dev up` and
  `./dev down` don't touch `ingest`, so work in progress never reaches the internet. Only
  `./dev tracker deploy` rebuilds and restarts it.

## The change for Adam (after you reply "go")

Nothing on the server needs to change: the `ingest` service is already running on
`127.0.0.1:8783` (`./dev tracker ps`). Everything below is in the Cloudflare dashboard.

### 1. Tunnel route

Open **Zero Trust → Networks → Tunnels**. Pick the main tunnel, the one every `*.adamcasada.com`
site uses (see `~/infra/TUNNELS.md`). Under **Published application routes**, choose **Add**:

| Field | Value |
|---|---|
| Subdomain | `travel` |
| Domain | `adamcasada.com` |
| Path | `^/api/v1/ingest/(owntracks\|overland)/?$` |
| Service type | `HTTP` |
| URL | `localhost:8783` |

Type the Path without the backslash, which is only Markdown escaping: `^/api/v1/ingest/(owntracks|overland)/?$`.

In **Additional application settings → HTTP Settings**:

- **Disable Chunked Encoding: ON.** This one is required. By default `cloudflared` forwards
  request bodies chunked. Cloudflare's docs recommend turning that off for WSGI servers, and the
  endpoints refuse chunked bodies with 411, because a body without a length would be read as
  empty and lose points.
- **HTTP Host Header:** leave it empty. The app recognizes the public hostname by the
  original Host header.

Leave everything else at its default. Don't add Cloudflare Access to this route either: the
phone apps can't log in to it.

The **Path** rule is a second layer. Other paths on `travel.adamcasada.com` then fall through to
the tunnel's catch-all, which answers 404. The app enforces the same allowlist on its own, so
it holds even if the path field is left empty, and the outside test below checks it. If the
dashboard rejects the regular expression, `^/api/v1/ingest/` is enough. `cloudflared` treats the
field as a Go regular expression and matches it anywhere in the path unless it is anchored, which
is why `^` and `$` are there.

### 2. DNS record

Saving the route normally creates this record for you. If it says a record already exists, delete
that record under **DNS → Records** and save the route again. If you add it yourself, use:

| Type | Name | Target | Proxy status | TTL |
|---|---|---|---|---|
| `CNAME` | `travel` | `<main tunnel UUID>.cfargotunnel.com` | Proxied (orange cloud) | Auto |

The UUID is on the tunnel's overview page and starts with the prefix noted in `~/infra/TUNNELS.md`.
Don't create any A or AAAA record for `travel`.

### 3. Bookkeeping

In `~/infra/TUNNELS.md`, update the travel-history row to read:
`8783 (tracker endpoint; the full app moves to 8780 at go-live) | travel-history |
~/apps/travel-history | travel.adamcasada.com (tracker paths only) | live <date>`. Adam makes
this edit, or approves it.

Not needed, and not changed: the firewall, the router, other apps, and zone-wide Cloudflare
settings.

## Outside-LAN test, with a throwaway token

Do this right after the route is live.

1. **Make a test token.** In the app on the LAN, open the account menu and choose
   **Location trackers**. Name the token `Outside test` and choose **Colota** (a Colota token
   works on both endpoints). Choose **Create token**, copy the token, then choose **Done, hide the
   token**.
2. **Through Cloudflare, from the server:** run `./dev tracker smoke https://travel.adamcasada.com`
   and paste the token at the hidden prompt. The request leaves the server, reaches Cloudflare
   and comes back through the tunnel. Expect `PASS`. The script checks:
   - every other path returns 404;
   - both endpoints accept the token;
   - HSTS and the other security headers are present;
   - the app sets no cookies;
   - neither the token nor anything shaped like one appears in the `ingest` log.

   The test messages store nothing (an OwnTracks `lwt` and an empty Overland batch).
3. **From truly outside:** on a phone with Wi-Fi off, open `https://travel.adamcasada.com/` and
   `https://travel.adamcasada.com/app/`. Both should show a bare "Not Found" or a Cloudflare 404,
   never the app.
4. **Revoke the token:** on **Location trackers**, choose **Revoke** next to `Outside test`. Run
   step 2 again with the same token. The two token checks must now fail with **401**, which
   proves the revocation took effect. Everything else should still pass.

If something fails:

| Symptom | Cause and fix |
|---|---|
| 411 on the token checks | **Disable Chunked Encoding** is off on the route. Turn it on. |
| 403 with a Cloudflare HTML page | A zone security feature (Bot Fight Mode or a WAF rule) is challenging the requests. A skip rule for `/api/v1/ingest/` on this host is a zone change, so it's Adam's call. The ntfy phone app works through the same zone, so this is unlikely. |
| 502 or 1033 | The `ingest` service isn't running (`./dev tracker ps`, then `./dev tracker deploy`), or the route's URL is wrong. |
| 404 on the token checks | The route's Path field doesn't match. Compare it with the table above. |
| "site can't be found" | The home router remembers the failed lookup for up to 30 minutes (`~/infra/TUNNELS.md`). Test on mobile data. |

## Rollback

Any one of these is enough. They're listed fastest first.

1. **Server-side switch, no dashboard needed:** `./dev tracker stop`. The tunnel then answers 502.
   The phones keep their points queued and send them once the endpoint is back
   (`./dev tracker deploy`).
2. **Dashboard:** delete the `travel.adamcasada.com` route on the tunnel, then delete the
   `travel` CNAME under **DNS → Records** if it remains.
3. **A token leaked:** revoke it on **Location trackers**. This takes effect at once and is
   final. Create a new one for the phone.

Nothing else needs undoing. The dev stack and other sites never depended on the route.

## Setting up your phone (the bake-off starts here)

Do this once the outside test passes.

1. In the app on the LAN, open the account menu and choose **Location trackers**. Name the phone
   (e.g. "Adam's Pixel"), choose the tracker app, and choose **Create token**. On Android,
   [Colota](colota.md) is recommended. On iPhone, use [OwnTracks](owntracks.md), or
   [Overland](overland.md) for detailed tracks.
2. The page shows a **setup QR code and link**. They already carry
   `https://travel.adamcasada.com`, because `TRACKER_BASE_URL` is set in `.env`. Follow the
   app's guide:
   - **Colota:** scan the QR with the phone's camera, or open the link, then confirm on Colota's
     setup screen.
   - **OwnTracks on iPhone:** scan the QR. **OwnTracks on Android:** open the link on the phone.
   - **Overland:** open the link on the phone.
3. Grant the background-location and battery settings from the
   [battery section](README.md#battery). Without them the phone stops sending after a while.
4. Choose **Done, hide the token**. Walk around the block, then check two things:
   - **Location trackers** shows a recent "last used" time and a growing point count;
   - the new points appear on the **History** map.
5. Keep Google Timeline running alongside, so the bake-off can compare the two
   ([design §9.3](../design/tracking.md)).

The [setup guides](README.md) also cover revoking, what is stored, and troubleshooting.

## Operating notes

- **Deploying changes:** the `ingest` service runs the image built at its last deploy. After
  any backend change, run `./dev tracker deploy`. It rebuilds, restarts, waits for the health
  check and runs the local smoke test. The phones lose nothing during the restart: they retry.
- **Logs:** `./dev tracker logs`. The access log prints paths without query strings, and every
  application log line is redacted.
- **Smoke test, any time:** `./dev tracker smoke` checks the local service the way the tunnel
  calls it, including the plain-HTTP redirect and unknown-host checks. Add a token
  (`TRACKER_SMOKE_TOKEN` or the hidden prompt) to check that tokens are accepted. Add `--store`
  only with a synthetic account: it stores one synthetic point.
- **Dev and production stacks:**
  - Both stacks are the same compose project with the same database volume, and `web` is one
    service. They never run at the same time and their port `127.0.0.1:8780` never conflicts.
  - To switch, run `./dev down && docker compose -f compose.yaml up -d --build`. To switch back,
    run `docker compose -f compose.yaml down && ./dev up`.
  - `ingest` (`127.0.0.1:8783`) runs alongside either one. Start it with
    `docker compose -f compose.yaml --profile tracker up -d ingest` under the production stack.
  - The dev stack uses `8780` (on `127.0.0.1` and the LAN address), `8781`, `8782` and `5173`
    (LAN only). Nothing else uses `8783`.
- **Client addresses:** `ingest` takes the per-address rate limit's address from
  `CF-Connecting-IP`. Cloudflare sets that header, and clients can't set it through Cloudflare.
  Trusting it is safe because only the server itself and this app's containers can reach the
  port without going through the tunnel. Docker 28 and later also blocks direct routing from the
  LAN to ports published on `127.0.0.1` (this host: Docker 29.8, with no `allow-direct-routing`
  override). The dev `web` (reachable on the LAN) keeps using the
  socket address.
- **If the route ever points at the dev server by mistake,** every path on the public hostname
  answers 404, the tracker paths included. A server running with DEBUG never answers the public
  hostname.
- **Go-live (phase 8):**
  - point the route at `localhost:8780` with no path rule;
  - set `TRAVEL_PUBLIC_SCOPE=all`, `DJANGO_BEHIND_TLS_PROXY=true` and
    `RATELIMIT_CLIENT_IP_HEADER=CF-Connecting-IP` for the production `web`;
  - remove the LAN binding;
  - retire `ingest`, or keep it behind a tracker-only path rule.

## How each item 8 condition is met

| Condition | Where |
|---|---|
| Only the tracker paths routed; everything else 404 until go-live | App guard `backend/travel/core/exposure.py`, which is on by default (`TRAVEL_PUBLIC_SCOPE=tracker`) for `TRAVEL_PUBLIC_HOSTS`. Ingest-only mode in the `ingest` service. Tunnel path rule as a second layer. Tests: `backend/tests/test_exposure.py`. Live check: `./dev tracker smoke`. |
| Production settings: DEBUG off, allowed hosts, HTTPS only, HSTS, security headers | The `ingest` service's environment in `compose.yaml`. `settings.py` refuses to start an ingest-only server without them. The response headers are HSTS (1 year), nosniff, X-Frame-Options DENY, Referrer-Policy, CSP and COOP, plus no-store. |
| T2 rate limiter on these paths | Per address (600/min, keyed on `CF-Connecting-IP`) and per token (120/min), both before the token lookup (D-77, D-82). |
| Per-device write-only tokens, hashed at rest, revocable | SHA-256 only, CHECK constraint, revocation final (D-82). |
| Request size cap and strict schema validation | 5 MB and 1,000 points, length required, whole-request rejection (D-82). |
| Plausibility flags | `implied_speed`, `reported_speed` (D-82). |
| Responses return no data | `[]` and `{"result":"ok"}` only. |
| Logs never contain tokens | The first middleware strips them, the formatters redact, and the access log omits query strings (D-82). The smoke test searches the live log. |
| Same public path as the other sites; Cloudflare visibility stated | Above: the shared tunnel, with TLS terminating at Cloudflare. |
| Proxy change and DNS record shown; applied only after "go" | Above. |
| Outside-LAN test with a throwaway token, then revoked | Above. |
| Phone setup walkthrough | Above. |
