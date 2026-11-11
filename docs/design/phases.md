# Phases, milestones, acceptance criteria

Moved from PLAN.md §23 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 23. Phases, milestones, acceptance criteria

At every milestone: all tests pass, this file is updated, commit + push, short summary posted.
Status markers: ✅ done · 🔄 in progress · ⏳ not started · ⛔ blocked on Adam.

### Phase 0 — Adam (in parallel; nothing waits on it)

- [ ] Export Timeline from the phone (Google Maps → Settings → Location & privacy (Android) /
      Your Timeline (iPhone) → Export Timeline data). See `docs/timeline-export.md`.
- [ ] Confirm Timeline retention is set to keep ("Auto-delete" off).
- [ ] Store the raw export in three places, one of them offline.
- [ ] Put the flight spreadsheet in `data/private/` (git-ignored).
- [ ] Optional now, needed by phase 8: decide on GitHub repo visibility (currently public).
- [ ] Create the backup key **on your laptop** (`age-keygen -o travel-backup.key`), keep the private
      key offline + in your password manager, put the public key in the server's `.env` as
      `AGE_RECIPIENT` (until then the nightly job writes nothing). See `docs/backup-nas.md`.
- [ ] Set up the NAS pull (read-only `rrsync` key + nightly rsync + snapshots): `docs/backup-nas.md`.

### Phase 1 — Skeleton ✅ (completed 2026-10-20)

| Milestone | Acceptance criteria | Status |
|---|---|---|
| 1.0 Prior-art evaluation, PLAN.md, CLAUDE.md, repo hygiene | Evaluation recorded (§1); plan and CLAUDE.md pushed; pre-commit secret scan + personal-data guard active | ✅ 2026-10-20 |
| 1.1 Compose stack | `./dev up` starts db, web, worker, mock OIDC, Mailpit, Vite; all healthy; DB has no published ports; all containers non-root; `./dev test` runs backend + frontend tests in containers | ✅ 2026-10-20 |
| 1.2 Full schema | Every table in §5 migrated (with constraints: vehicle-ownership exclusion + no-gap trigger, immutable route/raw_file, append-only points, segment version rules) | ✅ 2026-10-20 |
| 1.3 RLS + permission tests | RLS on every user-owned table (meta-test enumerates tables); permission matrix §6.3 tested at the SQL level as `travel_app` **and** against the app policy layer (`travel.core.policy`) that every endpoint must use; visibility rules §6.2 tested. Each API endpoint added later ships with its own API-level permission tests (CLAUDE.md rule 3) | ✅ 2026-10-20 (45 actions × 7 actors) |
| 1.4 OIDC + login wall | Login/callback/logout/re-auth against the mock provider; public-route allowlist test (§7.6); CSRF on; secure-cookie settings in production config | ✅ 2026-10-20 (also verified live against the running mock provider) |
| 1.5 Frontend shell + basemap | React + TS + MapLibre app with desktop/mobile shells and manual switch, OpenFreeMap basemap, auth state, PWA manifest; platform adapters stubbed; Vitest + type-check + build pass | ✅ 2026-10-20 (also verified in headless Chrome against the dev server and the production image: `./dev e2e`) |
| 1.6 Backups | Nightly backup job (pg_dump → zstd → age; raw/media incremental); `./dev restore-test` restores into a scratch DB and verifies; NAS pull instructions written | ✅ 2026-10-20 (restore test: all 64 tables/checks identical; raw-file checksum verification exercised from milestone 2.1 on, when raw files exist) |

### Phase 2 — Timeline and tracking 🔄 (← history becomes viewable)

| Milestone | Acceptance criteria |
|---|---|
| 2.1 Uploads + raw store ✅ 2026-10-20 | Resumable chunked upload API; raw file stored zstd, 0440, checksum-verified; identical re-upload detected by hash; per-user quota; `./dev restore-test` verifies raw-file checksums end to end (verified live: upload → worker → archive → backup → restore → checksum) |
| 2.2 Timeline import + diff ✅ 2026-10-21 | Streaming parse (memory bounded: peak memory stays flat as files grow — tested 20k vs 80k points); diff per §8.3; versions kept; absent ≠ deleted; in-app edits win; review flags; import summary page. iOS marked unverified until a real sample is checked (verified in the browser: upload → worker → summary) |
| 2.3 Raw-history map ✅ 2026-11-11 | MVT endpoint (own points only, RLS), date filter, segment overlay, coverage strip (points + segments tiles with grid aggregation and bounds, coverage API, both shells; permission tests at API and RLS level; timings in §14; verified in headless Chrome in both shells) |
| 2.4 Tracker ingestion | OwnTracks + Overland endpoints with device tokens (create/revoke/rate-limit); setup pages with QR/deep links; Colota evaluated; battery notes |
| 2.5 Home periods | Suggestions per §10.1 (synthetic multi-year fixture with two moves and a long stay detects all three), manual entry, gap/overlap validation |
| 2.6 Coverage + bake-off | Daily coverage per user and source; comparison of trips detected by each source; bake-off page |

### Phase 3 — Flights ⏳ (← flights become viewable)

| Milestone | Acceptance criteria |
|---|---|
| 3.1 Reference data | OurAirports, OpenFlights airlines/aircraft loaded by a management command with versions recorded; attribution page |
| 3.2 Template + conversion | Template CSV documented; conversion script reads the spreadsheet in `data/private/` (or the synthetic sample), flags rows it can't match; reassigned/closed codes resolved by date with manual override |
| 3.3 Arcs + grouping | Great-circle arcs split at ±180°; flights on the map; trip key or auto-grouping with review |
| 3.4 Dedupe | Flights deduplicated against Timeline flying segments |
| 3.5 Other importers | MyFlightRadar24, Flighty, App in the Air, TripIt, JetLog, byAir (from format specs) — may slip to phase 10 |

### Phase 4 — Catalog ⏳

| Milestone | Acceptance criteria |
|---|---|
| 4.1 Valhalla (Kansas) | `valhalla` compose project builds Kansas tiles; route + trace_route work through the backend; full NA build **not** run without approval |
| 4.2 Auto-detection + review queue | §11 on synthetic fixtures (overnight, day trip, multi-mode); review queue fully keyboard-driven; rejected never resurface; confirmed locked |
| 4.3 Desktop catalog | Map home screen; list + map with persisted divider; filters; tags; participants; bulk edit; shortcuts help |
| 4.4 Vehicles | Ownership history with exactly-one-owner constraint; "is it this one?" check; merge; rental quick-add |
| 4.5 Map matching | Drive legs map-matched with Valhalla; stored as frozen routes |

### Phase 5 — Routes ⏳

| Milestone | Acceptance criteria |
|---|---|
| 5.1 Routing proxy | Valhalla → ORS → FOSSGIS chain; OSRM-format normalization; throttle/debounce; provider policy compliance; provenance recorded |
| 5.2 Manual trips | Start/end/waypoints → proposed route → accept |
| 5.3 Drag-to-reshape | Anchor-point editing per §13; saved as a new frozen version; never recomputed (test) |

### Phase 6 — Statistics ⏳

| Milestone | Acceptance criteria |
|---|---|
| 6.1 Boundaries + geocoding | Natural Earth, Census counties, GeoNames loaded; stops named offline |
| 6.2 Territories | Countries/regions/counties visited, "through" vs "stopped in"; flights count airports only |
| 6.3 Distances + flight stats | Miles by vehicle, mode, year from saved geometry (great-circle for flights); airports, airlines, aircraft |

### Phase 7 — Mobile and photos ⏳

| Milestone | Acceptance criteria |
|---|---|
| 7.1 Mobile shell | Browse/filter/map; edit tags, participants, notes, own contributions |
| 7.2 PWA polish | Installable on Android, iOS, Windows/Linux; icons; offline shell |
| 7.3 Basic photos | Display + thumbnail on HDD; only capture time kept (test proves GPS stripped); limits; cover image |
| 7.4 Upload API for companion | Bearer-token auth on the same chunked upload API; documented |

### Phase 8 — Family and public ⏳

| Milestone | Acceptance criteria |
|---|---|
| 8.1 Request access | Landing, form, Turnstile (test keys), rate limits, push + email to Admin, re-auth approve, provisioner stub, invite links/QR, allowlist, onboarding |
| 8.2 Roles + contributions | Member/Viewer behaviour per §6.3 in the UI; contributions with attribution |
| 8.3 Duplicates | Overlap check offers "join existing trip"; merge tool (earlier creator stays owner) |
| 8.4 Transfers | Bulk transfer of trips/vehicles to a new member; shared trips stay with Adam |
| 8.5 Public | Snapshot builder, public renderer on `travel_public`, privacy zones, consent, leak tests, rate limits, profiles |
| 8.6 Go-live checklist | Written for Adam: Authentik + 2FA, SMTP account + DNS, Turnstile keys, tunnel hostname, removing the LAN binding |

### Phase 9 — Android companion ⏳ (against the mock OIDC provider until Authentik is live)

### Phase 10 — Later ⏳

Immich integration · desktop wrapper · regional PMTiles · remaining flight importers · bake-off
conclusion (after ≥ 4–6 weeks including a road trip).
