# Live location tracking

Moved from PLAN.md §9 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 9. Live location tracking

Available to every user, optional. Goal: replace Google Timeline only if self-hosted tracking is
at least as reliable (bake-off below).

### 9.1 Ingestion endpoints (outside the login wall, device token required)

| Endpoint | Accepts | Auth | Response |
|---|---|---|---|
| `POST /api/v1/ingest/owntracks` | OwnTracks HTTP JSON (one message per request; `_type: location` stored, `transition`/`waypoint`/`status` stored in `extra` or ignored; `lwt`, `card`, `cmd`, zero-length bodies ignored; `encrypted` rejected with a clear error) — also used by GPSLogger (JSON body template), Colota (OwnTracks template) | HTTP Basic (`username` = anything, `password` = token), or `Authorization: Bearer`, or `?token=` | `[]` |
| `POST /api/v1/ingest/overland` | Overland batch (`locations[]` GeoJSON Points, `[lon, lat]`) — Overland on iPhone, Colota (Overland template) | `Authorization: Bearer` or `?token=` | exactly `{"result":"ok"}` |

- **Device tokens** (`device_token`): self-service, `trk_` + 32 random bytes base64url, shown
  once, stored as SHA-256, write-only (they authorize nothing but appending points for their
  owner), revocable (final), last-used shown, per-token rate limit (default 120 requests/min,
  1,000 points/request), per-address limit (600 requests/min) and body cap (5 MB).
  Query-string tokens are removed from the request before anything logs it.
- **Writes:** the endpoint validates, converts to `location_point` rows (`source` from the
  token kind, `device` = token) and inserts with `ON CONFLICT DO NOTHING` in one statement; no
  other processing on the request path. Everything else (coverage, detection, home suggestions)
  runs asynchronously in the worker.
- **Time handling:** OwnTracks `tst` (epoch s), Overland ISO 8601 → UTC; points more than 1 day
  in the future or before 2000 are rejected and counted.

**Implementation (milestone 2.4, work-order item 7, D-82).** Code in `backend/travel/tracking/`.

- **Endpoints** are plain Django views outside the JSON API (`views.py`; no session, no CSRF),
  at `/api/v1/ingest/owntracks` and `/api/v1/ingest/overland` (a trailing slash is accepted).
  Checks, in order: POST only (405) → per-address limit `ingest-ip` (600/min, before anything
  else is read) → headers: declared length ≤ 5 MB (413), no chunked (411) or compressed (415)
  bodies → token well formed, per-token limit `ingest-token` (120/min, keyed by the token's
  SHA-256), lookup (401 for unknown, malformed, revoked, wrong endpoint, inactive or Viewer
  owner; one answer for all) → `Content-Type: application/json` (415) → strict parse (400/413)
  → store. Limits are settings (`TRACKER_*`); 429s carry `Retry-After`.
- **Token kinds per endpoint:** OwnTracks takes owntracks, gpslogger, colota and generic tokens;
  Overland takes overland, colota and generic. `source` follows the kind (generic → `other`).
- **Strict validation** (`payloads.py`, Pydantic strict mode, `extra="forbid"`): every field the
  apps may send is listed with type and range; unknown fields, wrong types (strings or booleans
  for numbers), NaN/Infinity, out-of-range values and naive Overland timestamps reject the whole
  request with 400, naming fields but never values. The app keeps the data and retries, so an
  app update that adds a field loses nothing; the field name shows in the server log. OwnTracks
  `lwt`, `card`, `cmd`, `transition`, `waypoint(s)`, `status`, `steps`, `beacon`, `request` and
  `configuration` messages and zero-length bodies are answered `[]` and not stored; `encrypted`
  is refused with a clear message; Overland trip/visit records are skipped.
- **Stored:** time, position, accuracy, altitude, speed (OwnTracks km/h → m/s), course and
  battery; `-1` "unknown" values become NULL. Everything else (Wi-Fi names, regions, images,
  motion) is discarded. Points dated before 2000 or more than a day ahead are refused and
  counted in the log line.
- **Plausibility flags** (`plausibility.py`): `extra = {"flags": [...]}` on the point, which is
  still stored. `implied_speed`: reaching the point from the device's previous point needs more
  than `TRACKER_MAX_SPEED_MPS` (400 m/s) after subtracting both points' accuracy, and also from
  the last unflagged point (so a single spike flags only itself). `reported_speed`: the device's
  own speed is over the limit. The previous points come from the same device within the time
  any jump on Earth could matter (≈ 14 h).
- **Writes** run as the token's owner: the lookup uses the `ingest` context (token rows only,
  D-51), then the request switches to the owner's context; `policy.can_ingest_points` and
  history migration 0009 (an INSERT naming a device needs the owner's unrevoked token, and every
  point INSERT needs an Admin or Member) both enforce it. One `INSERT … ON CONFLICT DO NOTHING`
  per request; `last_used_at` and `points_received` are updated in the same transaction.
- **Tokens never logged:** the first middleware (`middleware.py`) removes the `Authorization`
  header and any `?token=` from the request (`QUERY_STRING`, `RAW_URI`, `REQUEST_URI`, which
  gunicorn's access log reads) and keeps only the hash; token-holding functions are
  `sensitive_variables`; every log handler uses a redacting formatter
  (`travel/core/logredact.py`); Django's `mail_admins` handler is removed; the production
  access log prints the path without the query. Tests capture every log record of every request
  path, the 500 report Django would mail, and search every table for the token
  (`tests/test_tracking_secrets.py`).
- **Responses** are exactly `[]` (OwnTracks) or `{"result":"ok"}` (Overland) with
  `Cache-Control: no-store`; errors are `{"detail", "errors"?}`.

**Exposure before go-live (work-order item 8, D-73, D-85; [guide](../tracking/exposure.md)).**
The endpoints are reachable from the internet at `https://travel.adamcasada.com` through the
shared Cloudflare Tunnel; Cloudflare terminates TLS and so sees tokens and payloads in transit.
The tunnel points at the `ingest` service (`compose.prod.yaml`, profile `tracker`,
`127.0.0.1:8783`, part of the production stack since item 40a, D-96): the production image with forced production settings (DEBUG off, HTTPS-only
redirect, HSTS, secure cookies; `settings.py` refuses to start it otherwise) that answers only
the two ingest paths whatever the Host header says. Every backend service also guards the
public host names (`TRAVEL_PUBLIC_HOSTS`, `travel/core/exposure.py`): with
`TRAVEL_PUBLIC_SCOPE=tracker` (default) only the ingest paths answer there, every other path
404s, and a DEBUG server answers 404 to all of them. `ingest` takes client addresses from
`CF-Connecting-IP`. The route needs **Disable Chunked Encoding** (cloudflared otherwise sends
chunked bodies, which the endpoints refuse with 411). `./dev prod tracker start` starts
and smoke-tests it with the deployed production image (`scripts/tracker-smoke.sh`); `./dev prod
deploy` restarts it if it runs; the development stack has no `ingest`.

### 9.2 Trackers and setup guides (`docs/tracking/`)

Guides: [docs/tracking/](../tracking/README.md). Tokens are made on the SPA's **Location
trackers** page (`/app/trackers`, from the account menu) through `GET/POST
/api/v1/tracking/tokens` and `POST /api/v1/tracking/tokens/{id}/revoke`. The create response is
the only place the token appears, with a setup link and QR codes (SVG data URIs) built from it
(`setup.py`): OwnTracks `owntracks:///config?inline=…`, Overland `overland://setup?…`, Colota
`colota://setup?config=…` (its OwnTracks template, Bearer auth; format checked against
colota.app/docs/guides/deep-link-setup on 2026-11-16). GPSLogger gets fields to copy and a QR of
the token alone, not its `gpslogger://properties/<https URL>` link, which would need the token
served from a public address (Q-17). Links use `TRACKER_BASE_URL`, or the address the page was
opened at when it's empty. At most 20 active tokens per user.

| Tracker | Platform | Status 2026-10 | Format / setup |
|---|---|---|---|
| OwnTracks | Android 2.5.9, iOS 27.1.2 | active | HTTP mode. Setup: `owntracks:///config?inline=<base64 .otrc>` link + QR (`{"_type":"configuration","mode":3,"url":…,"auth":true,"username":"travel","password":"<token>","deviceId":…,"tid":…,"monitoring":1}`). QR import is documented for iOS; Android uses the link or the `.otrc` file. |
| Overland | iOS (App Store 1.3) | active repo, infrequent store releases | `overland://setup?url=…&token=…&device_id=…` link + QR. Needs "Always" location. |
| Colota | Android 1.20 (Play, F-Droid) | very active | **Qualifies**: OwnTracks or Overland template; `colota://setup?config=<base64 JSON>` link + QR (shows a confirmation screen). Recommended Android tracker. |
| GPSLogger | Android v137 (F-Droid) | active | Custom URL: POST, `Content-Type: application/json`, body template `{"_type":"location","lat":%LAT,"lon":%LON,"tst":%TIMESTAMP,"acc":%ACC,"alt":%ALT,"vel":%SPD_KPH,"batt":%BATT,"tid":"gl"}`; Basic auth with the token. Profile link `gpslogger://properties/<https URL>`. |
| PhoneTrack-Android | — | unmaintained since 2020 | Not recommended. |

Battery notes per platform (from dontkillmyapp.com and Android 14+ rules): Unrestricted battery
for the tracker; Samsung "Never sleeping apps" and re-check after updates; Xiaomi Autostart +
"No restrictions"; Android "Allow all the time" location; iOS "Always" + OwnTracks *significant*
mode (≈ 500 m / ≥ 5 min, light on battery) or *move* mode for detailed trips; force-quitting the
app on iOS stops tracking.

### 9.3 Bake-off (≥ 4–6 weeks, including a road trip)

- Run self-hosted tracking in parallel with Google Timeline; merge periodic Timeline exports
  through the diff importer (§8).
- **Daily coverage report** per user and source: points, hours with ≥ 1 point, list of empty
  hours (timezone-local), longest gap.
- **Trip comparison:** run detection (§11) per source over the same window; list trips found by
  one source but not the other, and boundary differences > 30 min.
- Recommendation written into this plan at the end (phase 10): turn Google off only if
  self-hosted coverage ≥ Google's on ≥ 95 % of days and no trip is missed.
