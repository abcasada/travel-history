# Travel History — Plan

> Private, self-hosted catalog of a lifetime of travel for a family. Django + GeoDjango + PostGIS
> backend, React + TypeScript + MapLibre frontend, everything in Docker on a home server.
> This index plus the files it links are the source of truth for design and progress. Keep them
> current (CLAUDE.md requires it). Read the index every session; open design docs on demand.

**Status (2026-11-19):** Phase 1 complete; phase 2 (Timeline and tracking) in progress —
milestones 2.1–2.4 done (2.4 tracker ingestion built and tested locally). Work-order item 8
(tracker exposure) is prepared: the `ingest` service runs on `127.0.0.1:8783` with the exposure
guard and production settings; the tunnel route waits for Adam's "go"
([docs/tracking/exposure.md](docs/tracking/exposure.md)). Phase 4: the trips API (T18) is done (item 13, 2026-11-19); the catalog UI's first slice (T19 session 1, item 20, 2026-11-19) lets you add, view and edit trips with legs, stops and people, on the map; patterns in [docs/design/frontend-patterns.md](docs/design/frontend-patterns.md). Milestone 4.1 (item 17, 2026-11-18): self-hosted Valhalla 3.9.1 with Kansas tiles runs as its own compose project on the `valhalla` network ([docs/valhalla.md](docs/valhalla.md)); routing proxy and manual routed legs done (item 25, 2026-11-19: Valhalla in Kansas, ORS once `ORS_API_KEY` is set, FOSSGIS fallback; D-92); drag-to-reshape editor core (item 26, gpx.studio port, D-93). Work now follows the
orchestrated work order in [docs/ROADMAP.md](docs/ROADMAP.md) (process:
[docs/ORCHESTRATION.md](docs/ORCHESTRATION.md)). Family go-live slice: the production stack
runs separately from dev (item 40a, 2026-11-19: `./dev prod …`, web on `127.0.0.1:8784`, not
exposed; [docs/production.md](docs/production.md), D-96).

| Phase | Status | Detail |
|---|---|---|
| 0 Adam (exports, backup key, NAS) | ⛔ waiting on Adam | [phases](docs/design/phases.md) |
| 1 Skeleton | ✅ 2026-10-20 | [phases](docs/design/phases.md) |
| 2 Timeline and tracking | 🔄 2.1–2.4 done | [phases](docs/design/phases.md) |
| 3 Flights | 🔄 3.1–3.2 done (synthetic) | [phases](docs/design/phases.md) |
| 4 Catalog · 5 Routes · 6 Statistics | ⏳ (4: trips API done, T18; catalog UI first slice, T19; 4.1 Valhalla Kansas done; 5.1 routing proxy, 5.2 manual routed legs and 5.3 drag editor core done) | [phases](docs/design/phases.md) |
| 7 Mobile and photos · 8 Family and public · 9 Android · 10 Later | ⏳ | [phases](docs/design/phases.md) |

## Section map

The old PLAN.md section numbers are kept inside each file, so a reference like "PLAN.md §6.3"
means §6.3 in the file below.

| § | Topic | File |
|---|---|---|
| 1 | Prior-art evaluation | [docs/research/prior-art.md](docs/research/prior-art.md) |
| 2 | Host and environment | [docs/design/host.md](docs/design/host.md) |
| 3 | Architecture | [docs/design/architecture.md](docs/design/architecture.md) |
| 4 | Stack and libraries | [docs/design/stack.md](docs/design/stack.md) |
| 5 | Data model | [docs/design/data-model.md](docs/design/data-model.md) |
| 6 | Permissions and visibility (matrix §6.3, public pages §6.5) | [docs/design/permissions.md](docs/design/permissions.md) |
| 7 | Auth, access requests, email, push | [docs/design/auth.md](docs/design/auth.md) |
| 8 | Google Timeline import | [docs/design/timeline-import.md](docs/design/timeline-import.md) |
| 9 | Live location tracking | [docs/design/tracking.md](docs/design/tracking.md) |
| 10 | Home history | [docs/design/home-history.md](docs/design/home-history.md) |
| 11 | Trip auto-detection | [docs/design/trip-detection.md](docs/design/trip-detection.md) |
| 12 | Flights | [docs/design/flights.md](docs/design/flights.md) |
| 13 | Routing, map matching, Valhalla | [docs/design/routing.md](docs/design/routing.md) |
| 14 | Map rendering | [docs/design/map-rendering.md](docs/design/map-rendering.md) |
| 15 | Statistics and reverse geocoding | [docs/design/statistics.md](docs/design/statistics.md) |
| 16 | Photos and Immich | [docs/design/photos.md](docs/design/photos.md) |
| 17 | API outline | [docs/design/api.md](docs/design/api.md) |
| 18 | UI layouts and keyboard shortcuts | [docs/design/ui.md](docs/design/ui.md) |
| 19 | Android companion and desktop wrapper | [docs/design/android-desktop.md](docs/design/android-desktop.md) |
| 20 | Threat model | [docs/design/threat-model.md](docs/design/threat-model.md) |
| 21 | Resource budget | [docs/design/resource-budget.md](docs/design/resource-budget.md) |
| 22 | Backup, restore, export | [docs/design/backup.md](docs/design/backup.md) |
| 23 | Phases, milestones, acceptance criteria | [docs/design/phases.md](docs/design/phases.md) |
| 24 | Decisions log (full text and reasoning) | [docs/decisions.md](docs/decisions.md) |
| 25 | Open questions | below, in this file |
| 26 | External facts register | [docs/research/facts-register.md](docs/research/facts-register.md) |
| 27 | Licenses and attributions | [docs/design/licenses.md](docs/design/licenses.md) |
| 28 | Trip spreadsheet import (design; template in docs/trips/) | [docs/design/trip-sheet.md](docs/design/trip-sheet.md) |

Frontend conventions: [docs/design/frontend-patterns.md](docs/design/frontend-patterns.md) (pages, data, forms, errors, map layers, tests). Other guides: [the production stack](docs/production.md), [backups to the NAS](docs/backup-nas.md), [restore](docs/restore.md),
[Timeline export](docs/timeline-export.md); research notes in `docs/research/` (read only when needed).

## Decisions (one line each; full text and reasoning in [docs/decisions.md](docs/decisions.md))

🔒 = locked by the brief. Changes need Adam's approval.

- D-01 Build fresh; don't fork AdventureLog 🔒
- D-02 Django + GeoDjango on PostgreSQL + PostGIS 🔒
- D-03 PostgreSQL-backed job queue, no Redis 🔒
- D-04 Procrastinate as the queue
- D-05 Django Ninja instead of DRF
- D-06 TypeScript 6.0 for now (not 7)
- D-07 Authlib for OIDC login; joserfc for bearer tokens
- D-08 Dev OIDC provider: mock-oauth2-server
- D-09 Push: Web Push (VAPID) via the PWA, email fallback, ntfy optional
- D-10 Own PostgreSQL-backed rate limiter
- D-11 Email: Resend recommended; Mailpit in dev
- D-12 Raw points as vector tiles via `ST_AsMVT` in Django 🔒
- D-13 Hosted OpenFreeMap basemap; style URL configurable 🔒
- D-14 Drag-to-reshape = port of gpx.studio anchor routing (MIT)
- D-15 Routing chain Valhalla → ORS → FOSSGIS OSRM via a backend proxy 🔒
- D-16 Google routing excluded 🔒
- D-17 Only the owner deletes a trip; Admin can edit but not delete
- D-18 React + TS + MapLibre; one codebase, desktop and mobile shells 🔒
- D-19 Desktop = installable PWA; platform features behind adapters 🔒
- D-20 Offline reverse geocoding in PostGIS, no Nominatim/Photon 🔒
- D-21 Managing user decides public consent for persons without accounts
- D-22 Contributor legs use `participant_scope = author`
- D-23 RLS design: owner/app/public roles, transaction-local `app.user_id`, tests as `travel_app`
- D-24 Public pages read only snapshot tables via `travel_public`
- D-25 Privacy zones clip every route portion inside a home buffer
- D-26 Desktop wrapper later: Tauri 2 over Electron
- D-27 Viewer role is read-only
- D-28 Exposure: dev `127.0.0.1:8780` plus the LAN address; production web `127.0.0.1:8784` only (amended by D-96)
- D-29 Valhalla in `valhalla/` as its own compose project
- D-30 Backups encrypted with age; private key offline; NAS pulls
- D-31 Python 3.13
- D-32 PostgreSQL 18 + PostGIS 3.6
- D-33 Resumable chunked uploads (32 MB chunks)
- D-34 Basic photos stored only as metadata-free re-encodes
- D-35 GitHub repo stays public; everything committed is public-safe
- D-36 Leg mode shown on public maps (line styling only)
- D-37 gitleaks for the pre-commit scan, in Docker
- D-38 Parser handles Android and iOS Timeline; iOS unverified
- D-39 Reassigned/closed airport codes resolved by date
- D-40 Road snapping with Valhalla map matching 🔒
- D-41 Mode detection reimplemented from ideas, user-correctable
- D-42 Android companion: AppAuth + UIDT/WorkManager uploads
- D-43 No open-source license yet (superseded by D-80)
- D-44 Postgres runs as uid 999; other containers as the host user
- D-45 Table grants applied by one module after every migrate
- D-46 Dev stack = compose.yaml + compose.dev.yaml; tests in a tools container
- D-47 Route geometry is a MultiLineString
- D-48 `location_point.device`/`.import_batch` use PROTECT
- D-49 Integrity triggers for immutable routes, raw files, points, segment versions, vehicle ownership
- D-50 All foreign keys use database-level `on_delete`
- D-51 Narrow system contexts (`app.ctx`): auth, ingest, public_form, transfer
- D-52 `INSERT … RETURNING` read-back limited to the current transaction's rows
- D-53 Deactivated users have no access; Admin can't change own role
- D-54 New accounts are Members; first Admin set via `set_role`
- D-55 Bearer tokens only for accounts created at a web sign-in
- D-56 Login wall = deny-by-default path allowlist
- D-57 Dev only: OIDC back-channel to the mock provider's internal address
- D-58 Re-auth freshness from `auth_time`; 10 s provider timeouts
- D-59 SPA under `/app/`; `/` is the public landing page
- D-60 Own small shortcut adapter instead of tinykeys
- D-61 MapLibre worker bundled explicitly
- D-62 Typed client generated by orval from the OpenAPI schema
- D-63 Browser smoke test: headless Chrome + playwright-core
- D-64 Backup container: daily pg_dump → zstd → age at 03:30
- D-65 Upload protocol: create → ordered checksummed chunks → complete
- D-66 Formats without an importer are archived as `unsupported`
- D-67 Wipe synthetic dev data before the first real import
- D-68 Re-import matching key and per-chunk diffing
- D-69 iOS path points sharing a timestamp spread by 1 s
- D-70 Google HOME/WORK labels stored as `PlaceHint` rows
- D-71 Dev worker under watchfiles; `rerun_import` command
- D-72 Account privacy: family sees only display names; email/OIDC subject self + Admin only
- D-73 Before go-live, only tracker ingestion paths are public
- D-74 Build method: orchestrator at Opus high + Opus subagents
- D-75 Orchestrator owns the roadmap; scope/decision changes need Adam
- D-76 D-72 enforced by a row policy on `accounts_user` + a `security_barrier` directory view (names, person link, active flag), not column grants
- D-77 Rate limiter: atomic upsert on a dedicated autocommit connection, HMAC keys, hourly cleanup
- D-78 Base images pinned to exact version + digest (≥ 14 days old)
- D-79 `./dev test-quick` skips `slow` tests; `./dev test` runs all
- D-80 MIT license
- D-81 Trips API: 404 for invisible, 403 for forbidden; removing a participant clears their leg overrides; sharing settings to core editors only; reference guards
- D-82 Tracker ingestion: plain views, strict whole-request validation, flags in `extra`, per-token + per-address limits, Member-only point inserts with the owner's live token, tokens stripped from requests and logs
- D-83 History tiles under RLS: InitPlan `is_family()` + Morton `tile_key` index
- D-84 Bulk storage temporarily on the SSD (`var/bulk`) until the HDD is replaced
- D-85 Tracker exposure: tracker-only `ingest` service on `127.0.0.1:8783` behind the tunnel; app-level public-host guard (404 except ingest paths; DEBUG answers nothing); production settings enforced at startup
- D-86 History map at scale: trigger-maintained per-day/per-year point roll-up (RLS), quadtree `seg_key` for segments, dense segment tiles merged instead of truncated
- D-88 Flight imports: pinned reference downloads, bundled code overrides, user-owned `flight_record` staging table, CLI import under RLS (pending Adam)
- D-87 Cross-user periodic jobs: `app.job_user_ids` enumerator (ids of active users, `jobs` context only), one RLS transaction per user, failures isolated, advisory run lock; first job `stale_uploads`
- D-89 Rest of the trips API: contributions editable by their author only while on the trip; the trip owner may delete a removed participant's contributions (Q-16); stop places own or already on the trip; all-or-nothing bulk edit; hidden vehicles filter like missing ones; merge left to T35 (pending Adam)
- D-90 Catalog UI architecture: URL as state, generated hooks only, no form library, trip map from `GET /trips/map` until routes exist, stops by map/airport/coordinates, "Add me" creates the own person (pending Adam)
- D-91 Valhalla: own build script on the pinned 3.9.1 image (non-root, generic User-Agent, md5 check, atomic `current` switch), Kansas coverage polygon with the Missouri corner cut, no default speeds; dev web `DB_CONN_MAX_AGE=0` (pending Adam)
- D-92 Routing proxy: "no route" ends the chain; ORS/FOSSGIS limits server-wide; per-user proposal cache under RLS; saving uses the server's cached proposal, stores attribution and simplified copies; road modes only
- D-93 Drag editor saves pieces: cached proposals, own versions, validated drawn points; `hand_edited` with per-source provenance (pending Adam)
- D-94 GeoNames gazetteer: cities500 + US populated places, pinned snapshot + SHA-256 (cache is the pin, `--latest` re-pins); prefix search on folded names by population; city picker suggests stop name and zone
- D-95 Trip spreadsheet: one trip per `.xlsx` tab; trip block, stops header, legs header found by content; legs cite stops by row number, label or `=ROW()`; places never guessed; preview before commit; re-import by trip key, never deletes by absence (pending Adam)
- D-96 Production stack: own compose project, DB and `.env.prod` beside the repo; deployed only from pushed `main` via a release directory, images tagged by commit; §7.7 enforced at startup; trips.* redirects to travel.*; dev never answers a public name (pending Adam)

## 25. Open questions (for Adam, answer whenever — nothing is blocked on these)

| ID | Question | Current assumption |
|---|---|---|
| Q-1 | The GitHub repo `abcasada/travel-history` already exists and is **public**. Make it private? (`gh repo edit abcasada/travel-history --visibility private --accept-visibility-change-consequences`) | **Answered 2026-11-10:** leave public; keep contents public-safe. |
| Q-2 | When will the Ryzen 5 3600 / 32 GB migration happen? | **Answered 2026-11-10:** probably about 2 months out (around mid-January 2027). Develop on the current host with small data until then. |
| Q-3 | The SSD's volume group seems to have ~55 GB unallocated. Extend the root LV (`sudo lvextend -r -l +100%FREE ubuntu-vg/ubuntu-lv`)? It's a host change, so I won't do it. | **Done by Adam 2026-11-10:** root LV is 108 GB (about 70 GB free). Bulk data goes on the 1 TB HDD. |
| Q-4 | North America Valhalla build: rented cloud VM (first build, a few dollars) or local on the Ryzen host? | Locally on the Ryzen host: this Xeon lacks the RAM (11 GiB vs about 16–28 GB peak). Kansas extract until then. |
| Q-5 | Backup NAS: what OS/filesystem (ZFS, btrfs, Synology…)? Needed to make `docs/backup-nas.md` concrete. | Generic rsync-over-SSH pull + snapshots. |
| Q-6 | Should Viewers be able to contribute (notes/photos) to trips they're on, or stay read-only? | **Answered 2026-11-10:** read-only. |
| Q-7 | For participants without accounts (e.g. kids), who decides whether their name/legs appear on public pages? | **Answered 2026-11-10:** the managing user decides. |
| Q-8 | PWA install/service-worker testing needs HTTPS. Over plain LAN HTTP it won't install. Options: (a) SSH port-forward to `localhost`, (b) a dev hostname through the tunnel behind Cloudflare Access (that's exposure → your call), (c) a local CA. | **Answered 2026-11-10:** (a) SSH port-forward to localhost. |
| Q-9 | OpenRouteService's terms prohibit transmitting personal data. OK to send only user-drawn waypoints (outside NA / Valhalla down), or skip ORS and use only the FOSSGIS fallback there? | **Answered 2026-11-10:** user-drawn waypoints only, no identity. No ORS key yet; Valhalla only with the ORS fallback stubbed until a key is added. Item 25 built the ORS path (tested against mocks); it goes live when `ORS_API_KEY` is set. |
| Q-10 | Email: Resend (recommended) or SMTP2GO? Is Cloudflare Email Routing active on adamcasada.com (so I can double-check the SPF/DMARC records)? | **Answered 2026-11-17:** Resend. |
| Q-11 | Defaults OK? Privacy-zone radius 1 km; public pages show dates only; home addresses private by default. | **Still open (2026-11-10):** 1 km is the default for now, but Adam may revisit the radius soon; keep it a single setting that is easy to change. Dates-only and private home addresses assumed yes. |
| Q-12 | Switch the secret scanner from gitleaks (now security-patches-only) to its successor Betterleaks? | **Answered 2026-11-17:** keep gitleaks; item 41 (the security review) tries Betterleaks. |
| Q-13 | Any intention to publish the source? (Would decide a license, e.g. MIT or AGPL.) | **Answered 2026-11-10:** MIT license (D-80). |
| Q-14 | Should family members be able to see each other's **vehicles' ownership history** (who owned it when), or only the vehicle and current owner? | **Answered 2026-11-10:** full history visible to family unless hidden. |
| Q-15 | The server's LAN address is DHCP-assigned. A DHCP reservation on the EdgeRouter would keep the dev binding stable (router change → yours). | **Resolved 2026-11-10:** the server already has a fixed address outside the router's DHCP range. |
| Q-16 | A participant contributed their own leg (e.g. a separate flight home) and is later removed from the trip. Should that leg keep sharing the trip with them, and who may delete it? | **Answered 2026-11-17:** the trip owner may delete a removed participant's leg. Built in item 13 (2026-11-19), for notes, tracks, tags and photos too (D-89). |
| Q-17 | GPSLogger's setup link (`gpslogger://properties/<https URL>`) downloads a settings file from a web address. Serving one would mean handing the token to anyone with that address (even short-lived, it passes through any proxy's logs). OK to skip it? | **Answered 2026-11-17:** yes, no hosted GPSLogger profile; copyable fields plus a token QR. |
| Q-18 | Trip spreadsheet layout (§28.2): the template puts the trip's fields (title, dates, purpose, people…) in a small block above the stops header. The block is optional, so row 1 can be the stops header, with the tab name as the title. OK? | **Answered 2026-11-18 (orchestrator, under Adam's delegation):** yes, an optional trip block above the stops header. |
| Q-19 | Trip spreadsheet re-import (§28.9): a stop or leg removed from the sheet is kept (rule 6). Should the preview offer an unticked, per-trip "also remove these N stops and legs" option, or should removal only ever happen in the app? | **Answered 2026-11-18 (orchestrator, under Adam's delegation):** yes, an unticked per-trip option in the preview; without it, missing rows are kept (rule 6). |
| Q-20 | Trip spreadsheet people (§28.3): a name in People that matches nobody in the app. Refuse the tab until the person is added in the app, or create the person during the import? | **Answered 2026-11-18 (orchestrator, under Adam's delegation):** neither silently: the preview lists unknown names with an unticked "create these people" option; left unticked, the tab is refused. |
| Q-21 | Trip spreadsheet: one trip per tab only, or also several small trips stacked in one tab (each with its own trip block)? | **Answered 2026-11-18 (orchestrator, under Adam's delegation):** one trip per tab for now. |
