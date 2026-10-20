# Research: stack, libraries, Immich, Tauri, Android (checked 2026-10-19)

Conf H/M/L. Versions from live PyPI/npm/Maven/Docker Hub unless noted.

## CPU (Xeon W3565: x86-64-v2, no AVX/AVX2/AES-NI) — smoke-tested on this host, all OK (H)
numpy 2.5.4 (baseline X86_V2), shapely 2.2.0, pyproj 3.8.0, timezonefinder 9.0.0 (+h3 4.5.0),
Pillow 13.0.0, pillow-heif 1.8.1, zstandard 0.25.0, ijson 3.6.0 (yajl2_c), psycopg[binary] 3.3.6,
orjson 3.13.0, pydantic 2.14.1, granian 2.8.4, cryptography 50.0.2, pywebpush; Vite 8.3.4
(Rolldown), @tailwindcss/vite 4.3.3 + lightningcss 1.33, esbuild 0.28.2, TypeScript 7.0.2 native,
Biome 2.5.15, Bun 1.4.3, Vitest 5.0.5, Node 26.12; Playwright Chromium 156 headless (WebGL2 ok);
gitleaks v8.30.1; Android AAPT2 9.4.1. NumPy ≥ 2.4 requires x86-64-v2
(numpy.org/doc/stable/release/2.4.0-notes.html); Immich v3 ML requires x86-64-v2
(docs.immich.app/install/requirements/).

## Django
- Latest 6.1.2 (2026-10-06); 6.1 released 2026-08-05; 5.2 LTS to Apr 2028; 6.1 to Dec 2027;
  6.2 LTS due Apr 2027 (to Apr 2030) (djangoproject.com/download) — H.
- 6.0/6.1 support Python 3.12–3.14; 6.1 needs PostgreSQL 15+ — H.
- Built-in CSP middleware since 6.0 (`SECURE_CSP`) → django-csp not needed — H.
- `django.tasks` core has only Immediate/Dummy backends; DB backend is third-party
  django-tasks-db 0.13.0 (immature) — H.

## Job queue
- **Procrastinate 3.10.0** (2026-09-23): Django contrib, `manage.py procrastinate worker`,
  LISTEN/NOTIFY, periodic tasks, retries, priorities, `lock`, `queueing_lock` (AlreadyEnqueued),
  closes Django connections around tasks (3.9+). LISTEN needs a direct/session connection.
  (procrastinate.readthedocs.io) — H.
- Alternatives: Chancy 0.26.0 (0.x, timeouts), PgQueuer 1.6.0 (not Django-native), django-q2
  1.11.1 (ORM broker polls), django-tasks-db 0.13.0.

## API
- DRF 3.18.3 (2026-10-06), self-described "feature-complete" (maintenance mode in practice) — H.
- **Django Ninja 1.7.1** (2026-09-19), Pydantic 2 (2.14.1), native OpenAPI, Django 6.1 OK;
  geojson-pydantic 2.2.0 — H.
- drf-spectacular 0.30.0; djangorestframework-gis 1.3.0.
- TS clients: openapi-typescript 7.13.0 / openapi-fetch 0.17.0 (peer typescript ^5); orval 8.43.0
  (Node ≥ 22.18, TanStack Query hooks); @hey-api/openapi-ts 0.99.0.

## RLS (postgresql.org/docs/current/ddl-rowsecurity.html, functions-admin.html, sql-createview.html) — H
- Owners bypass RLS unless FORCE; superusers/BYPASSRLS always bypass; enabled + no policy =
  deny; FK/unique checks bypass RLS (covert channel); `row_security=off` errors instead of
  filtering (backups).
- `set_config(name, value, true)` is transaction-local; `current_setting(name, true)` returns NULL
  if missing, but may return '' after being set once in a session → use NULLIF.
- Views use the view owner's privileges unless `security_invoker = true`.
- Django psycopg pool since 5.1 (`OPTIONS: {"pool": ...}`, `CONN_MAX_AGE = 0`); session-level SET
  leaks across requests with pooling → transaction-local only.
- Test runner creates the test DB as the connecting role (owner) → RLS bypassed unless handled (M).
- django-rls 2.0.1 uses session-level set_config by default (risky); hand-written RunSQL
  recommended.

## Python libraries
psycopg 3.3.6, psycopg-pool 3.3.3; ijson 3.6.0; timezonefinder 9.0.0 (numba optional); pyproj
3.8.0; shapely 2.2.0; numpy 2.5.4; Pillow 13.0.0; pillow-heif 1.8.1 (bundles libheif/x265 —
check GPL/LGPL if redistributed); django-ratelimit 4.1.0 (**stale**, 2023); django-axes 8.3.1;
whitenoise 6.12.0; gunicorn 26.2.0 (classifiers to 3.13); granian 2.8.4; pywebpush 2.5.0;
qrcode 8.2; gpxpy 1.6.2; polyline 2.0.4; zstandard 0.25.0; python-magic 0.4.27 (2022);
puremagic 2.2.0; environs 15.2.0; django-environ 0.14.0; pytest-django 4.14.0; factory_boy
3.3.3; hypothesis 6.170.2; ruff 0.17.1; mypy 2.4.0; django-stubs 6.1.2. Secret scanners:
gitleaks v8.30.1 ("feature complete… security patches only", author moved to Betterleaks v1.9.0,
MIT); trufflehog v3.99.2; detect-secrets 1.5.0 (stale).

## Frontend
React 19.3.1; TypeScript 7.0.2 (native Go tsc, no programmatic API until 7.1; TS 6.0.3 for
tooling via `npm:@typescript/typescript6`); Vite 8.3.4 (Node ^20.19 or ≥ 22.12);
vite-plugin-pwa 2.0.0; TanStack Query 5.104.5 / Router 1.170.45; React Router 8.5.0;
maplibre-gl 6.15.0; react-map-gl 8.1.3; @turf/turf 7.4.0; Zustand 5.0.15; Vitest 5.0.5;
Playwright 1.64.1; @testing-library/react 16.3.3; react-resizable-panels 4.14.6 (persisted
layouts); tinykeys 4.0.1; react-hotkeys-hook 5.3.3; Tailwind 4.3.3; radix-ui 1.8.1; Biome 2.5.15.

## Node
Node 24 (24.22.0) Active LTS → maintenance 2026-10-20, EOL 2028-04-30; Node 26 LTS on 2026-10-28,
EOL 2029-04-30 (nodejs/Release schedule.json) — H.

## Immich (v3.3.3, 2026-10-14; open-api/immich-openapi-specs.json) — H
- Auth: `x-api-key`, bearer, cookie. API keys are **scoped** (`permissions[]`: asset.read,
  asset.view, asset.update, album.read, …). No OAuth for third-party apps → per-user API keys.
- `POST /api/search/metadata` (asset.read) — v3.2+: use `filter.takenAt {gte, lt}`
  (takenAfter/takenBefore/page deprecated), cursor pagination (`nextCursor`), size ≤ 1000,
  `withExif`.
- `GET /api/assets/{id}/thumbnail?size=thumbnail|preview|fullsize` (asset.view);
  `GET /api/assets/{id}` (exifInfo lat/long/timeZone); `PUT /api/assets/{id}` latitude/longitude
  (asset.update); `PUT /api/assets` bulk; albums; `GET /api/map/markers`.
- ML container needs x86-64-v2; 6 GB RAM min, 8 GB recommended.

## Tauri vs Electron
Tauri 2.12.4 (v3 alpha); plugins global-shortcut 2.4.1, fs 2.7.1 (watch), notification 2.7.0;
Linux uses WebKitGTK (test MapLibre). Electron 44.9.0 (heavier).

## Android
Kotlin 2.4.21; AGP 9.4.1 (Gradle ≥ 9.6, JDK 17, API ≤ 37); Gradle 9.8.2; cmdline-tools 23.0,
build-tools 37.0.0; Play requires target API 36 from 2026-08-31 (Play only); build image:
eclipse-temurin + cmdline-tools (own image).
