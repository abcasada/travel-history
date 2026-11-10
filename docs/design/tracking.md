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
  owner), revocable, last-used shown, per-token rate limit (default 120 requests/min, 1,000
  points/request) and body cap (5 MB). Query-string tokens are redacted in logs.
- **Writes:** the endpoint validates, converts to `location_point` rows (`source` from the
  token kind, `device` = token) and inserts with `ON CONFLICT DO NOTHING` in one statement; no
  other processing on the request path. Everything else (coverage, detection, home suggestions)
  runs asynchronously in the worker.
- **Time handling:** OwnTracks `tst` (epoch s), Overland ISO 8601 → UTC; points more than 1 day
  in the future or before 2000 are rejected and counted.

### 9.2 Trackers and setup guides (`docs/tracking/`)

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
