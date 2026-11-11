# Roadmap

Only the orchestrator and the planner edit this file. Status values: todo · in progress · done · deferred · blocked.

## Work order
Tiers: [M] builder-medium, [H] builder-high, [X] builder-xhigh, [R] reviewer-xhigh. Task IDs (T1…T46) and finding numbers (#1…#16) are from the 2026-10-21 audit; their descriptions and dependencies are in the Task reference below. Each item is one dispatch unless noted.

1. **[M] Stage 0 housekeeping** (details below). Skip it if already done.
   - Status: done (2026-11-10)

   **Item 1 details: Stage 0 housekeeping**
   1. **Restructure PLAN.md** (it's ~35k tokens):
      - It becomes an index of 400 lines or fewer: status, a pointer to ROADMAP.md, open questions, one line per decision, and links to the docs.
      - Move §3–§22 to `docs/design/<area>.md`, and §1 plus the facts register (§26) to `docs/research/`.
      - Merge the decisions log into `docs/decisions.md`, keeping the entries already there.
      - Verify that every old heading appears in exactly one new file, and that the word count, excluding the new index, is within 2% of the original. Report both checks.
   2. **Enrich docs/ROADMAP.md** with each task's description and dependencies from STATUS.md, without changing the order or tiers. Then delete STATUS.md without committing it.
   3. **Add deny rules in `.claude/settings.json`** for reading `frontend/src/api/generated.ts`, `frontend/dist/`, minified bundles, and lockfiles. Verify the rule syntax in the docs first.
   4. **T1:**
      - write `docs/timeline-export.md`;
      - fix the doc drift from findings #3 and #11;
      - record that the current mobile tabs are interim.
   5. **T3:**
      - raise the Vite dev container's memory limit;
      - make the browser smoke test clean up its import batch;
      - hide the desktop search box until it's wired up.
   6. **Finding #12:** pin the Python, Node, and PostGIS base images to exact versions at least 14 days old.
   7. **T46:**
      - Make the permission matrix stop rebuilding its fixture for every case, without weakening anything: all 315 cases must still run and pass.
      - Mark slow tests with a `slow` marker and add a quick-suite command that excludes them.
      - Report before and after timings.
   8. **Finish:** full suite, lint, and type checks green; commit and push.
2. **[X] T4 + T2:** account privacy, and the database-backed rate limiter. Tests must cover concurrent requests.
   - Status: done (2026-11-11)
3. **[M] T5:** a 500 MB–1 GB synthetic import test. Record time, peak memory, and database growth. If it's over budget or fails: ESCALATE.
   - Status: blocked (2026-11-11): the HDD behind /bulk is read-only with I/O errors; needs Adam to fix or replace the disk.
4. **[M] T11 + real import:**
   - Wipe the synthetic data, after confirming the target is the dev database and holds only synthetic data.
   - Import my real export and verify the counts.
   - Confirm a nightly backup has run that includes real data.
   - Needs `AGE_RECIPIENT` and my export; if either is missing, defer this item.
   - Status: deferred (no AGE_RECIPIENT or export yet; /bulk also needs a working disk)
5. **[H] T6:** raw-history map. ← my history becomes viewable
   - Status: done (2026-11-11)
   - **5a. [H] T6 follow-ups:**
     - a per-day grid roll-up so z0–6 tiles stay fast with millions of points;
     - a spatial key for segment tiles;
     - make the e2e upload check verify its own upload, not an earlier one.

     Run after item 3 has measured tile timings at 500 MB–1 GB. Then run `./dev restore-test` once the disk is fixed, to confirm the generated `tile_key` column restores.
     - Status: todo (waits on item 3)
6. **[X] T18 core:** the permission-critical trips API, with endpoint tests for every role and visibility rule.
   - Status: in progress (dispatched 2026-11-11)
7. **[X] T7:** tracker endpoints, built and tested locally.
   - Status: todo
8. **[X] Tracker exposure, under all of these conditions:**
   - Route only the tracker paths. Every other path on that hostname returns 404 at the proxy until go-live.
   - The exposed service runs with production settings: DEBUG off, allowed hosts set, HTTPS only, HSTS, security headers.
   - Before exposure, all of these are in place:
     - the T2 rate limiter on these paths;
     - per-device write-only tokens, hashed at rest and revocable;
     - a request size cap and strict schema validation;
     - plausibility flags for impossible speeds or jumps;
     - responses that return no data;
     - logs that never contain tokens.
   - Use the same public path my existing sites use. If it passes through Cloudflare's proxy or Tunnel, say so, because Cloudflare can then see the location payloads in transit.
   - Show me the proxy change and the exact DNS record, and apply the change only after I reply "go". I add the DNS record myself.
   - Test from outside the LAN with a test token, then revoke it.
   - Walk me through setting up my phone with the setup guide and QR code. ← the bake-off starts
   - Status: todo
9. **[H] T8:** nightly jobs that cover all users under RLS.
   - Status: todo
10. **[M] T12 + T13:** flight datasets, the import template, and the conversion. Use my spreadsheet if it's present; otherwise synthetic data.
    - Status: todo
11. **[M] T14 + T15:** flights on the map, grouping into trips, and dedupe against Timeline. ← my flights become viewable
    - Status: todo
12. **[M] T10:** coverage report, without the trip comparison.
    - Status: todo
    - **→ Review pause A:** history, flights, and tracking are live. I'll try them.
13. **[H] The rest of T18.**
    - Status: todo
14. **[M] T26:** places.
    - Status: todo
15. **[H] T9:** home-period detection.
    - Status: todo
16. **[M] T9:** the review UI and manual entry.
    - Status: todo
17. **[M] T17:** Valhalla with a Kansas extract. Check free disk first.
    - Status: todo
18. **[X] T20 core:** trip detection and data integrity, including the locking of confirmed trips.
    - Status: todo
19. **[H] T20:** the review queue.
    - Status: todo
20. **[H] T19 session 1:** catalog UI architecture plus `docs/design/frontend-patterns.md`.
    - Status: todo
21. **[M] The rest of T19,** following the patterns doc (2 dispatches).
    - Status: todo
    - **→ Review pause B:** the desktop catalog UI.
22. **[M] T20 polish,** plus the T10 trip comparison.
    - Status: todo
23. **[H] T21:** vehicles.
    - Status: todo
24. **[M] T22:** map-matched routes.
    - Status: todo
25. **[M] T23 + T24:** routing proxy and manual trips. Without an ORS key, use Valhalla only and leave the ORS fallback stubbed.
    - Status: todo
26. **[H] T25 core:** the drag editor, ported from gpx.studio (MIT, with attribution).
    - Status: todo
27. **[M] T25 polish.**
    - Status: todo
28. **[H] T27:** territory stats.
    - Status: todo
29. **[M] T28:** distance and flight stats.
    - Status: todo
30. **[M] T29:** mobile features. Decide the final mobile tabs here.
    - Status: todo
31. **[H] T31:** basic photos. Tests must prove no EXIF, XMP, IPTC, maker notes, or HEIC metadata survive.
    - Status: todo
32. **[M] T30 + T32:** PWA polish (needs Q-8), plus upload docs and bearer-token photo upload.
    - Status: todo
33. **[H] T34:** roles and contributions.
    - Status: todo
34. **[X] T35:** the merge tool.
    - Status: todo
35. **[H] T36:** transfers.
    - Status: todo
36. **[X] T33 core:** request access, the auth flows, and abuse protection.
    - Status: todo
37. **[H] The rest of T33.**
    - Status: todo
38. **[X] T37 core:** the public snapshot builder, privacy-zone clipping, consent, and leak tests.
    - Status: todo
39. **[H] The rest of T37.**
    - Status: todo
40. **[M] T38:** the go-live checklist.
    - Status: todo
41. **[R] Security and data-integrity review, read-only:**
    - RLS, public routes, tokens, rate limits, headers, secrets, dependencies, leak tests;
    - the integrity of trip-detection locking (T20), the merge tool (T35), and transfers (T36).
    - Status: todo
    - **→ Pause:** the findings summary.
42. **[H] Blocker fixes.**
    - Status: todo
43. **[M] Other fixes.**
    - Status: todo
44. **[H] T39 session 1:** Android architecture plus a patterns doc.
    - Status: todo
45. **[M] The rest of T39.**
    - Status: todo
46. **[M] Optional, in order:** T16, T41, T42, T45.
    - Status: todo

**Later, only when I ask:**
- T40 Immich [X, then H].
- T43 bake-off conclusion [H], after 4–6 weeks of tracking data.
- T44 North America Valhalla build [H], after the Ryzen migration and with my approval.

## Task reference (from the 2026-10-21 audit)

Reference only: the work order above sets order, tiers and status. Folded in from the audit's STATUS.md on 2026-11-10 (Stage 0); PLAN §N references now resolve through the section map in PLAN.md.

### Tasks

Nature: mech = mechanical, mod = moderate, hard. Size is S/M/L/XL with approximate files and lines. "Conf" = confidence it fits one focused session.

| ID | Task (phase) | Size | Nature | Risk if wrong | Ambiguity | Depends on | Conf |
|---|---|---|---|---|---|---|---|
| T1 | Write `docs/timeline-export.md`; fix PLAN/CLAUDE drift (#3, #10–12) | S (3 files, ~120) | mech | low | settled | — | high |
| T2 | PostgreSQL rate limiter (`travel/core/ratelimit.py`) + tests (#2) | M (3 files, ~200) | mod | medium (abuse of public endpoints) | settled (D-10) | — | high |
| T3 | Raise Vite memory limit; e2e cleanup; hide or wire the search box (#5, #8, #9) | S (3 files, ~40) | mech | low | settled | — | high |
| T4 | Decide account-row visibility; restrict via a view or column grants (#6) | S–M (2 files, ~120) | hard (RLS) | medium (privacy) | **needs decision** | Adam (or accept a proposed default) | high |
| T5 | Realistic-size import test (500 MB–1 GB synthetic: time, RSS, DB size) (#4) | M (1 script, ~150) | mod | high if skipped (real import OOM or timeouts) | settled | — | high |
| T6 | 2.3 Raw-history map: points MVT (RLS, grid aggregation), segments overlay, date filter, coverage strip | M–L (~8 files, ~700) | mod | medium (privacy; RLS backs it) | settled (§14) | — | medium |
| T7 | 2.4 Tracker ingestion: OwnTracks/Overland endpoints, device tokens UI, QR/deep links (OwnTracks, Overland, Colota, GPSLogger), `docs/tracking/` | L (~12 files, ~1200) | hard | high (public write endpoints, tokens) | settled (§9) | T2 | medium |
| T8 | Design + implement cross-user periodic jobs under RLS (user enumerator function / per-user scheduling) | S–M (~3 files, ~150) | hard | medium | **not designed in PLAN** | — | high |
| T9 | 2.5 Home periods: night-location algorithm, suggestions, review UI, manual entry (map pin), gap/overlap validation | L (~10 files, ~1200) | hard | medium-high (feeds detection and privacy zones) | mostly settled (thresholds) | T6; address search needs T26 | low–medium (likely 2 sessions) |
| T10 | 2.6 Daily coverage job + bake-off page | M (~6 files, ~500) | mod | low | trip-comparison part needs 4.2 | T7, T8, (T20) | medium |
| T11 | Wipe synthetic dev data before the first real import (D-67) | S | mech | high (must touch dev data only) | settled | Adam's export | high |
| T12 | 3.1 OurAirports/OpenFlights loaders, `DatasetVersion`, attribution page | M (~5 files, ~400) | mod | low | settled | — | high |
| T13 | 3.2 Flight template, spreadsheet conversion script, date-aware code resolution, unmatched report | L (~6 files, ~800) | mod | medium (wrong airports) | mostly settled | T12; Adam's spreadsheet (synthetic first) | medium |
| T14 | 3.3 Great-circle arcs (antimeridian), flights on the map, trip grouping (trip key or auto-group candidates) | M–L (~6 files, ~600) | mod | medium | settled | T13 | medium |
| T15 | 3.4 Dedupe flights vs Timeline FLYING segments | S–M (~2 files, ~200) | mod | medium | settled | T13 | high |
| T16 | 3.5 Six other flight importers (MFR24, Flighty, App in the Air, TripIt, JetLog, byAir) | L (~8 files, ~900) | mod | low | formats medium-confidence | T13 | low (2 sessions) |
| T17 | 4.1 Valhalla compose project, Kansas tiles, backend client, `trace_route` wrapper | M (~5 files, ~400) | mod | low-medium (resources) | settled | — | high |
| T18 | 4.3a Trips/legs/participants/tags/stops API using `policy` + API-level permission tests | L–XL (~10 files, ~1500) | hard | high (permission leaks) | settled (§6, §17) | — | low (2 sessions) |
| T19 | 4.3b Desktop catalog UI: map home (trip MVT from `route_simplified`), list+map, filters, bulk edit, tags, participants, shortcuts | XL (~15 files, ~2000) | hard (UI) | medium | settled (§18) | T18 | low (2–3 sessions) |
| T20 | 4.2 Trip auto-detection (overnight, day trips, stay points, modes, legs, flight matching, fingerprints) + keyboard review queue | XL (~12 files, ~2000) | hard | high (data integrity, locked trips) | mostly settled; tune with real data | T9, T18, T13, (T17) | low (2–3 sessions) |
| T21 | 4.4 Vehicles: CRUD, ownership-history UI, "is it this one?" (SECURITY DEFINER plate match), merge, rental quick-add | L (~8 files, ~1000) | hard | medium (merge integrity, private fields) | settled | T18 | medium |
| T22 | 4.5 Map matching of drive legs (chunk, stitch, frozen route versions, simplified copies) | M (~4 files, ~400) | mod | medium | settled | T17, T20 | medium |
| T23 | 5.1 Routing proxy (Valhalla→ORS→FOSSGIS, OSRM normalization, throttle, cache, provenance) | M–L (~6 files, ~600) | mod | medium (ToS, personal data) | Q-9 open | T17, T2; ORS key (Adam) | medium |
| T24 | 5.2 Manual trip creation with proposed route | M (~5 files, ~500) | mod | low | settled | T23, T19 | medium |
| T25 | 5.3 Drag-to-reshape editor (gpx.studio MIT port, zoom anchors, undo/redo, save as new version) | XL (~8 files, ~1800) | hard (UI) | medium-high (rework) | settled (§13.4) | T23, T19 | low (2–3 sessions) |
| T26 | 6.1 Natural Earth, Census, GeoNames loaders + offline reverse geocoding | M (~5 files, ~500) | mod | low | settled | — | high |
| T27 | 6.2 Territories visited (through vs stopped-in; airports only for flights; cache + rebuild) | L (~6 files, ~800) | hard (geometry performance) | medium | settled | T26, T18, routes | medium |
| T28 | 6.3 Distances by vehicle/mode/year, flight stats, stats pages | M (~6 files, ~700) | mod | low | settled | T27, T21 | medium |
| T29 | 7.1 Mobile shell features (browse, filter, edit tags/participants/notes/contributions) | M–L (~8 files, ~800) | mod | medium | settled | T18, T19 | medium |
| T30 | 7.2 PWA polish (install, offline shell, iOS meta) | S–M (~4 files, ~200) | mech | low | Q-8 (HTTPS for testing) | Adam for HTTPS test path | high |
| T31 | 7.3 Basic photos: upload, Pillow re-encode, GPS/EXIF strip tests, thumbnails, limits, cover, protected serving, orphan sweep | L (~10 files, ~1000) | mod | high (GPS leak) | settled (§16.1) | T18 | medium |
| T32 | 7.4 Companion upload API docs + bearer photo upload | S–M (~3 files, ~200) | mod | medium | settled | T31 | high |
| T33 | 8.1 Request access: landing, form, Turnstile, rate limits, Web Push (VAPID), email, re-auth approve, provisioner stub, invites/QR, allowlist, onboarding | XL (~18 files, ~2000) | hard | high (abuse, account takeover) | mostly settled (§7.3–7.5) | T2; real keys later (Adam) | low (2–3 sessions) |
| T34 | 8.2 Roles + contributions UI (notes, photos, own legs, own tags, consent, own-leg participation) | L (~10 files, ~1200) | hard | high (permissions) | settled | T18, T19, T31 | medium |
| T35 | 8.3 Duplicate check / join / merge tool | L (~6 files, ~800) | hard | high (data integrity) | outline settled | T18, T34 | medium |
| T36 | 8.4 Transfers (bulk offers, SECURITY DEFINER accept, vehicles) | M–L (~6 files, ~700) | hard | high (ownership) | settled | T21, T34 | medium |
| T37 | 8.5 Public trips/profiles: snapshot builder, `travel_public` renderer, privacy-zone clipping, consent, noindex, rate limits, sentinel leak tests | XL (~14 files, ~1800) | hard | **high (privacy leak)** | settled (§6.5) | T2, T9, T18, T31 | low (2 sessions) |
| T38 | 8.6 Go-live checklist doc | S (1 file, ~150) | mech (careful) | medium | settled | T33, T37 | high |
| T39 | 9 Android companion (Kotlin, AppAuth, UIDT/WorkManager resumable uploader, share target, trip picker, Docker build, signing) | XL (new project, ~3000) | hard | medium | settled (§19.1) | T32; Authentik for real use | low (3+ sessions) |
| T40 | 10 Immich integration (encrypted per-user keys, SSRF rules, suggestions, thumbnail proxy, stripped public copies) | L–XL (~10 files, ~1200) | hard | high (credentials, SSRF) | settled (§16.2) | Adam's Immich | medium |
| T41 | 10 Tauri desktop wrapper | M | mod | low | settled | T19 | medium |
| T42 | 10 Regional PMTiles basemap | M | mod | low | needs OK on storage | — | medium |
| T43 | 10 Bake-off conclusion | S | analysis | low | — | 4–6 weeks of T7/T10 data | high |
| T44 | Full North America Valhalla build | M (ops) | mod | high (resources) | Q-4 | Adam approval; Ryzen or VM | medium |
| T45 | Optional: backend type checking (mypy + django-stubs) (#13) | M | mech | low | — | — | medium |
| T46 | Optional: faster tests (module-scoped scenario fixture; mark the memory test slow) | S–M | mod | low | — | — | high |

### Audit findings

| # | Finding | Paths | Severity |
|---|---|---|---|
| 1 | **Migration history rewritten after commit.** All initial migrations were regenerated in 57e9a01 (DB-level `on_delete`), and the RLS migration was edited in 8ea6efa. A DB built at an earlier commit can't migrate forward. The dev DB was reset, so the current state is consistent. | `backend/travel/*/migrations/0001_initial.py`, `core/migrations/0002_row_level_security.py` | cosmetic now; blocker if it ever happens after real data. Add a "never edit applied migrations" rule |
| 2 | **Rate limiter missing.** It is planned in D-10, §9.1 and §20, but `travel/core/ratelimit.py` doesn't exist and the `RateLimitBucket` model is unused. CLAUDE.md lists `ratelimit` as part of core. Needed before ingestion (2.4) and public routes (phase 8). | `backend/travel/core/`, `CLAUDE.md` | fix soon |
| 3 | **Broken doc link.** The phase-0 checklist links `docs/timeline-export.md`, which doesn't exist; the export steps are only in the History page. Also referenced but not yet built (future phases): `docs/tracking/`, `docs/flights/template.csv`, `data/fixtures/flights_synthetic.csv`. | `PLAN.md` §23 | fix soon (S) |
| 4 | **2.2 acceptance criterion loosened.** It required "a 1 GB synthetic file stays under the worker limit". The test instead compares ~3.5 MB and ~14 MB files and checks that peak memory stays flat. No realistic-size import (hundreds of MB) has been run, so real-scale time and memory are UNVERIFIED. | `backend/tests/test_timeline_import.py`, `PLAN.md` §23 | fix soon (before the first real import) |
| 5 | **Vite dev container at 82% of its memory limit.** Risk of an OOM kill. | `compose.dev.yaml` | fix soon (S) |
| 6 | **Every account row is readable by the whole family.** The `accounts_user` SELECT policy lets every family member read every user row, including email and OIDC subject, at the DB level. The API exposes only `/me` today. PLAN doesn't decide this. | `core/migrations/0002_row_level_security.py` | fix soon (decide before 8.2 lists users) |
| 7 | **Policy layer is ahead of the API.** 20 of 24 functions in `travel/core/policy.py` have no caller outside tests, because no trip, vehicle or home endpoints exist yet. Same for `has_recent_auth` and the frontend notifications adapter and `canWatchFolders`. This is planned code, not dead code, and nothing tests it at the API level. | `travel/core/policy.py`, `frontend/src/platform/*` | cosmetic (track) |
| 8 | **e2e leaves data behind.** Each smoke-test run leaves a duplicate import batch in the dev DB (8 so far). | `e2e/smoke.mjs` | cosmetic |
| 9 | **Desktop search box does nothing.** It has no handler. | `frontend/src/shells/DesktopShell.tsx` | cosmetic |
| 10 | **Mobile tabs drift from the plan.** The tab bar is Map/Trips/History; PLAN §18.3 says Map/Trips/Add/Me. | `frontend/src/shells/MobileShell.tsx` | cosmetic (PLAN drift) |
| 11 | **D-23 wording is wrong.** It says tests use `SET LOCAL ROLE`; the code uses `SET ROLE` with `RESET ROLE` on teardown. | `PLAN.md` §24, `backend/tests/conftest.py` | cosmetic |
| 12 | **Image tags aren't fully pinned.** CLAUDE.md says they are, but `python:3.13-slim-trixie`, `node:24-trixie-slim` and `postgis/postgis:18-3.6` are moving tags without digests. | `compose*.yaml`, Dockerfiles | cosmetic |
| 13 | **No backend type checking.** The conventions call for type hints, but nothing checks them. | `backend/` | cosmetic |
| 14 | **Duplicated or abandoned code: none found.** Each concern has one implementation. The resume-notes file and a stray file were removed before the first commit. | — | — |
| 15 | **Broken commits:** HEAD is verified green. Intermediate commits weren't re-tested (UNVERIFIED); each milestone message claims a green run. See #1 for migration incompatibility between commits. | — | cosmetic |
| 16 | **Permission tests that don't exist yet.** The matrix (45 actions × 7 actors) covers the RLS and policy layers, and the upload, import and preferences endpoints have API-level tests. Missing, because the features don't exist: API-level tests for trips, legs, vehicles and homes; public-page leak tests; ingestion-token tests. | — | track (each must land with its feature) |

## Changelog
- 2026-11-10: item 1 done and verified (commits pushed, tree clean, `./dev test-quick` 432 + 18 passed; builder-medium confirmed running Opus 5.5 at medium effort).
- 2026-11-11: item 2 done and verified (pushed, tree clean, `./dev test-quick` 512 + 18 passed; builder-xhigh confirmed running Opus 5.5 at xhigh).
- 2026-11-11: item 3 blocked because the /bulk HDD is failing (read-only, I/O errors); item 4 deferred. Skipping ahead to item 5, which doesn't write to /bulk.
- 2026-11-11: item 5 done and verified (pushed, tree clean, `./dev test-quick` 601 + 26 passed; builder-high confirmed at high; RLS migration 0007 checked: same conditions, evaluated once per statement). Added fix item 5a for low-zoom scaling, segment tile key and the e2e upload check, gated on item 3's measurements.
