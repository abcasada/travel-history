# Travel History — Plan

> Private, self-hosted catalog of a lifetime of travel for a family. Django + GeoDjango + PostGIS
> backend, React + TypeScript + MapLibre frontend, everything in Docker on a home server.
> This index plus the files it links are the source of truth for design and progress. Keep them
> current (CLAUDE.md requires it). Read the index every session; open design docs on demand.

**Status (2026-11-11):** Phase 1 complete; phase 2 (Timeline and tracking) in progress —
milestones 2.1–2.3 done. Phase 4: the trips API core (T18 core) is done. Work now follows the
orchestrated work order in [docs/ROADMAP.md](docs/ROADMAP.md) (process:
[docs/ORCHESTRATION.md](docs/ORCHESTRATION.md)).

| Phase | Status | Detail |
|---|---|---|
| 0 Adam (exports, backup key, NAS) | ⛔ waiting on Adam | [phases](docs/design/phases.md) |
| 1 Skeleton | ✅ 2026-10-20 | [phases](docs/design/phases.md) |
| 2 Timeline and tracking | 🔄 2.1–2.3 done | [phases](docs/design/phases.md) |
| 3 Flights · 4 Catalog · 5 Routes · 6 Statistics | ⏳ (4: trips API core done) | [phases](docs/design/phases.md) |
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

Other guides: [backups to the NAS](docs/backup-nas.md), [restore](docs/restore.md),
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
- D-28 Exposure: `127.0.0.1:8780` plus the LAN address only
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
- D-81 Trips API: 404 for invisible, 403 for forbidden; removing a participant clears their leg overrides; sharing settings to core editors only; reference guards (pending Adam)

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
| Q-9 | OpenRouteService's terms prohibit transmitting personal data. OK to send only user-drawn waypoints (outside NA / Valhalla down), or skip ORS and use only the FOSSGIS fallback there? | **Answered 2026-11-10:** user-drawn waypoints only, no identity. No ORS key yet; Valhalla only with the ORS fallback stubbed until a key is added. |
| Q-10 | Email: Resend (recommended) or SMTP2GO? Is Cloudflare Email Routing active on adamcasada.com (so I can double-check the SPF/DMARC records)? | Resend; existing apex SPF untouched. |
| Q-11 | Defaults OK? Privacy-zone radius 1 km; public pages show dates only; home addresses private by default. | **Still open (2026-11-10):** 1 km is the default for now, but Adam may revisit the radius soon; keep it a single setting that is easy to change. Dates-only and private home addresses assumed yes. |
| Q-12 | Switch the secret scanner from gitleaks (now security-patches-only) to its successor Betterleaks? | Keep gitleaks for now. |
| Q-13 | Any intention to publish the source? (Would decide a license, e.g. MIT or AGPL.) | **Answered 2026-11-10:** MIT license (D-80). |
| Q-14 | Should family members be able to see each other's **vehicles' ownership history** (who owned it when), or only the vehicle and current owner? | **Answered 2026-11-10:** full history visible to family unless hidden. |
| Q-15 | The server's LAN address is DHCP-assigned. A DHCP reservation on the EdgeRouter would keep the dev binding stable (router change → yours). | **Resolved 2026-11-10:** the server already has a fixed address outside the router's DHCP range. |
| Q-16 | A participant contributed their own leg (e.g. a separate flight home) and is later removed from the trip. Should that leg keep sharing the trip with them, and who may delete it? | Today: no. Visibility counts trip-level participants and per-leg includes only, so the removed person loses access to a "participants" trip; their leg stays, and nobody can delete it short of deleting the trip. Recommended: keep the visibility rule, and let the owner delete contributions by people no longer on the trip (item 13 / T34). |
