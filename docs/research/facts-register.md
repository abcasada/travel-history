# External facts register

Moved from PLAN.md §26 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 26. External facts register

Every external fact this plan relies on, with source, date checked and confidence
(H = official docs/source/API, M = maintainer statement or inference, L = estimate). Full detail
and more sources: `docs/research/*.md`. Re-verify before acting on anything older than ~3 months.

| Topic | Fact | Source | Checked | Conf |
|---|---|---|---|---|
| AdventureLog | GPL-3.0 (GitHub NOASSERTION), v0.13.0 2026-08-12, 3.8k★, top author 45–56 % of 12-mo commits | `gh api repos/seanmorley15/AdventureLog` | 2026-10-19 | H |
| gpx.studio | MIT since 2024-06-28; anchor routing in `routing-controls.ts`/`simplify.ts` | github.com/gpxstudio/gpx.studio (LICENSE history, source) | 2026-10-19 | H |
| AirTrail | GPL-3.0; v3.13.0 2026-09-26; importers for MyFlightRadar24, Flighty, App in the Air, TripIt, JetLog, byAir | github.com/johanohly/AirTrail | 2026-10-19 | H |
| TREK | AGPL-3.0 since 2026-03-19 | github.com/liketrek/TREK | 2026-10-19 | H |
| Reitti | AGPL-3.0 from v5.0.0 (2026-07-05), MIT before | github.com/dedicatedcode/reitti/releases/tag/v5.0.0 | 2026-10-19 | H |
| Dawarich | AGPL-3.0 | github.com/Freika/dawarich | 2026-10-19 | H |
| GeoPulse | custom BSL 1.1 since v1.4.2 (2025-11-17), change date 2075-01-01 | github.com/tess1o/geopulse LICENSE | 2026-10-19 | H |
| maplibre-gl-directions | MIT, v0.10.1 2026-09-22, requires maplibre-gl ^6 | github.com/maplibre/maplibre-gl-directions | 2026-10-19 | H |
| GPL/AGPL/MIT | APK distribution triggers GPL §5c/§6; AGPL §13 network clause; MIT notice retention | gnu.org/licenses/gpl-3.0.html, /agpl-3.0.html; opensource.org/license/mit | 2026-10-19 | H |
| Valhalla | MIT; 3.9.1 2026-10-06; image `ghcr.io/valhalla/valhalla-scripted`; `server_threads` sets build concurrency | github.com/valhalla/valhalla (releases, docker/README.md) | 2026-10-19 | H |
| Valhalla | `format: osrm` output; trace defaults max_shape 16,000, max_distance 200 km | valhalla docs api/turn-by-turn, api/map-matching | 2026-10-19 | H |
| Valhalla NA build | peak RAM ≈ 16–28 GB @4 threads, 120–150 GB disk, 2–6 h on NVMe | scaled from issues #5698, #5910, #6201, #6312, #6341, #4140 | 2026-10-19 | L |
| Valhalla on this CPU | no AVX flags in build | Dockerfile, CMakeLists | 2026-10-19 | M |
| Geofabrik | north-america 19.51 GB; kansas 117 MB | download.geofabrik.de (Content-Length) | 2026-10-19 | H |
| OpenRouteService | free: directions 2,000/day, 40/min; ≤ 50 waypoints; results CC-BY-SA 4.0; attribution required; prohibits transmitting personal data | account.heigit.org (plans bundle, /info/tos), openrouteservice.org/restrictions | 2026-10-19 | H |
| FOSSGIS OSRM | ≤ 1 req/s, valid User-Agent, no heavy use, attribution | routing.openstreetmap.de/about.html | 2026-10-19 | H |
| Google Maps Platform | ToS §3.2.3(e) no non-Google maps; SST §4.2/4.3, §17, §19: no non-Google map, lat/lng cache ≤ 30 days; §A.3 place IDs cacheable | cloud.google.com/maps-platform/terms (2026-08-26), …/maps-service-terms (2026-10-15) | 2026-10-19 | H |
| OpenFreeMap | free, no key, no request limits, commercial OK, attribution OpenMapTiles + OSM; bulk download ≤ 3,000 tiles/50 MB | openfreemap.org/tos (2026-10-14) | 2026-10-19 | H |
| PMTiles | go-pmtiles v1.31.2; `pmtiles extract --bbox/--region` | docs.protomaps.com | 2026-10-19 | H |
| Martin | v1.16.1; no built-in authentication | maplibre/martin docs (run-with-nginx) | 2026-10-19 | H |
| MapLibre | maplibre-gl 6.15.0 (BSD-3); react-map-gl 8.1.3 supports v6 | GitHub releases | 2026-10-19 | H |
| Antimeridian | MapLibre draws across 180° with unwrapped longitudes; turf greatCircle splits | maplibre example; turf README | 2026-10-19 | H |
| PostGIS image | `postgis/postgis:18-3.6`, amd64, PG18 volume at `/var/lib/postgresql` | Docker Hub, docker-postgis README | 2026-10-19 | H |
| Django | 6.1.2 (2026-10-06); 6.1 supported to Dec 2027; 6.2 LTS Apr 2027; Python 3.12–3.14; built-in CSP | djangoproject.com/download, release notes | 2026-10-19 | H |
| Procrastinate | 3.10.0; Django integration; queueing_lock; periodic tasks | procrastinate.readthedocs.io | 2026-10-19 | H |
| Django Ninja / DRF | Ninja 1.7.1 (Django 6.1 OK); DRF "feature-complete" | GitHub; django-rest-framework.org/community/contributing | 2026-10-19 | H |
| PostgreSQL RLS | owners bypass unless FORCE; BYPASSRLS bypasses; set_config local; views use owner privileges | postgresql.org/docs/current (ddl-rowsecurity, functions-admin, sql-createview) | 2026-10-19 | H |
| CPU compatibility | numpy ≥ 2.4 needs x86-64-v2; all chosen wheels/tools ran on this Xeon (no AVX) | numpy 2.4.0 notes; smoke tests on host | 2026-10-19 | H |
| Authentik | 2026.8.4 (2026-10-14); no Redis since 2025.10; ~2–2.5 GB RAM; app access via group bindings (none = everyone); invitations API; Authenticator Validation `configure`; WebAuthn/TOTP; SMTP env vars | docs.goauthentik.io, release notes, schema.yml 2026.8.4, issues #20537/#25683 | 2026-10-19 | H/M |
| OIDC libs | Authlib 1.9.1; mozilla-django-oidc 5.0.2 declares ≤ Django 5.2; allauth 65.20 | PyPI, project docs | 2026-10-19 | H |
| mock-oauth2-server | 6.1.2 (2026-10-18), PKCE, interactive login, claim mapping per subject | github.com/navikt/mock-oauth2-server | 2026-10-19 | H |
| Resend | free 3,000/month, 100/day, 3 domains, 30-day logs; SMTP smtp.resend.com:587 user `resend`; DNS MX/TXT on `send.`, DKIM `resend._domainkey` | resend.com/docs (quotas, send-with-smtp, knowledge-base/cloudflare) | 2026-10-19 | H |
| SMTP2GO | free 1,000/month, 200/day; CNAME-based DKIM/return-path | smtp2go.com/pricing, support articles | 2026-10-19 | H/M |
| SPF/DMARC | one SPF record per name (RFC 7208 §3.2), ≤ 10 lookups; DMARCbis RFC 9989 drops `pct` | rfc-editor.org/rfc/rfc7208; redsift.com | 2026-10-19 | H/M |
| Turnstile | free 20 widgets; siteverify endpoint; test keys `1x00000000000000000000AA` / secret `1x0000000000000000000000000000000AA` | developers.cloudflare.com/turnstile | 2026-10-19 | H |
| Web Push / ntfy | iOS 16.4+ home-screen only, no action buttons on Safari; ntfy v2.32.0, iOS needs upstream relay | MDN browser-compat-data; docs.ntfy.sh | 2026-10-19 | H |
| Cloudflare | 100 MB request body on Free; 125 s proxy timeout; multiple hostnames per tunnel | developers.cloudflare.com (413, 524, tunnel routing) | 2026-10-19 | H |
| Timeline export (Android) | `semanticSegments`/`rawSignals`/`userLocationProfile`; `"lat°, lng°"`; placeId only, no names | mlocati/gmaps-timeline-json schema; dawarich.app blog; bobg/lohi | 2026-10-19 | H |
| Timeline export (iOS) | bare array, `geo:lat,lng`, string numbers, `placeID`, minute-offset path points | dawarich #2587; RouteConverter #351 | 2026-10-19 | M-H (unverified here) |
| OwnTracks | HTTP POST JSON, Basic auth, `[]` response, `owntracks:///config?inline=` remote config | owntracks.org/booklet | 2026-10-19 | H |
| Overland | batch GeoJSON, Bearer token, `{"result":"ok"}`, `overland://setup?url=&token=&device_id=` | github.com/aaronpk/Overland-iOS README | 2026-10-19 | H |
| GPSLogger | custom URL with placeholders, no native OwnTracks format, v137 | mendhak/gpslogger FAQ | 2026-10-19 | H |
| Colota | AGPL-3.0 Android tracker v1.20.0; OwnTracks/Overland templates; `colota://setup?config=` QR | github.com/dietrichmax/colota docs | 2026-10-19 | H |
| Battery | dontkillmyapp.com vendor steps; Android 14 location FGS rules | dontkillmyapp.com; developer.android.com | 2026-10-19 | H |
| OurAirports | public domain (Unlicense), daily; closed airports have empty iata_code, old codes in keywords | github.com/davidmegginson/ourairports-data | 2026-10-19 | H |
| OpenFlights | ODbL + DbCL; airlines 2017, stale; Active unreliable | openflights.org/data.php | 2026-10-19 | H |
| Natural Earth | public domain; v5.1.x; use `ISO_A2_EH` | naturalearthdata.com | 2026-10-19 | H |
| Census | 2025 cartographic boundary counties `cb_2025_us_county_500k.zip` | www2.census.gov/geo/tiger/GENZ2025/shp/ | 2026-10-20 | H |
| GeoNames | CC BY 4.0; cities500 13 MB; admin1 codes often FIPS | download.geonames.org/export/dump/readme.txt | 2026-10-20 | H |
| ijson | 3.6.0 with C backend wheels | pypi.org/project/ijson | 2026-10-19 | H |
| Immich | v3.3.3; scoped API keys; `POST /api/search/metadata` with `filter.takenAt` (v3.2+); thumbnails `size=thumbnail|preview`; `PUT /api/assets/{id}` lat/long; no OAuth for third parties | immich OpenAPI spec v3.3.3; docs.immich.app | 2026-10-19 | H |
| Tauri | 2.12.4; global-shortcut, fs watch, notification plugins | crates.io | 2026-10-19 | H |
| Android | AppAuth-Android 0.11.1 (2021, still used); WorkManager 2.12.0; Android 15 dataSync 6 h/24 h; UIDT jobs API 34+; Play target API 36 | GitHub/Maven; developer.android.com | 2026-10-19 | H |
| Node | Node 24 LTS (EOL 2028-04-30); Node 26 LTS 2026-10-28 | nodejs/Release schedule.json | 2026-10-19 | H |
