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
| 2.4 Tracker ingestion ✅ 2026-11-16 (local; exposure is item 8: prepared 2026-11-17, `ingest` service + guard + guide, waiting for Adam's "go") | OwnTracks + Overland endpoints with device tokens (create/revoke/rate-limit); setup pages with QR/deep links; Colota evaluated; battery notes (strict validation, size caps, plausibility flags, no-data responses, token-free logs; tests at API, RLS and log level; guides in docs/tracking/) |
| 2.5 Home periods | Suggestions per §10.1 (synthetic multi-year fixture with two moves and a long stay detects all three), manual entry, gap/overlap validation |
| 2.6 Coverage + bake-off | Daily coverage per user and source; comparison of trips detected by each source; bake-off page |

### Phase 3 — Flights 🔄 (← flights become viewable)

| Milestone | Acceptance criteria |
|---|---|
| 3.1 Reference data ✅ 2026-11-18 | OurAirports, OpenFlights airlines/aircraft loaded by a management command with versions recorded; attribution page. Done: `load_flight_reference` (pinned commits + SHA-256), About page in the app |
| 3.2 Template + conversion ✅ 2026-11-18 (synthetic) | Template CSV documented; conversion script reads the spreadsheet in `data/private/` (or the synthetic sample), flags rows it can't match; reassigned/closed codes resolved by date with manual override. Done: `flights_convert`, `flights_import`, `flight_record` (D-88), docs/flights/README.md; waits for Adam's real spreadsheet |
| 3.3 Arcs + grouping | Great-circle arcs split at ±180°; flights on the map; trip key or auto-grouping with review |
| 3.4 Dedupe | Flights deduplicated against Timeline flying segments |
| 3.5 Other importers | MyFlightRadar24, Flighty, App in the Air, TripIt, JetLog, byAir (from format specs) — may slip to phase 10 |

### Phase 4 — Catalog 🔄

| Milestone | Acceptance criteria |
|---|---|
| 4.1 Valhalla (Kansas) ✅ 2026-11-18 | `valhalla` compose project builds Kansas tiles; route + trace_route work through the backend; full NA build **not** run without approval. Item 17: 3.9.1 pinned by digest, runs on the non-AVX Xeon; build 188 s, peak 773 MiB anon; tiles 422 MB; `./dev valhalla build\|up\|down\|status\|smoke` route and map-match from the app network ([docs/valhalla.md](../valhalla.md), D-91). The backend proxy is item 25 |
| 4.2 Auto-detection + review queue | §11 on synthetic fixtures (overnight, day trip, multi-mode); review queue fully keyboard-driven; rejected never resurface; confirmed locked |
| 4.3 Desktop catalog 🔄 | Map home screen; list + map with persisted divider; filters; tags; participants; bulk edit; shortcuts help. Trips API core (T18 core, item 6) ✅ 2026-11-11: trips, legs, participants and consent endpoints with API-level tests for every role and RLS-level tests (matrix 65 actions × 7 actors); rest of T18 (item 13) ✅ 2026-11-19: tags, purposes, stops, notes, GPS tracks (time range), photo metadata, route versions (read-only), leg order, all-or-nothing bulk edit, list filters (purpose, tag, vehicle, mode, bbox); contributions follow the leg rule and the owner may delete a removed participant's (Q-16, D-89); matrix 95 actions × 7 actors. Duplicates/join/merge stay with T35. Catalog UI first slice (T19 session 1, item 20) ✅ 2026-11-19: map home and trip list with filters (text, dates, mode, purpose, tag, "only in map view"), trip detail, create/edit with people ("Add me", new people), stops (map click, airport, coordinates) and legs (stop to stop, reorder, flight airports), trips on the map (`GET /trips/map`, straight/great-circle until routed), a leg route view as the routing editor's slot; both shells; patterns in [frontend-patterns.md](frontend-patterns.md) (D-90); matrix 98 × 7. Stop and leg notes (item 14b) ✅ 2026-11-19: private free text on each stop and leg, edited by the stop's or leg's editors, shown on the trip page and in both editors, never public; Notes columns in the trip spreadsheet template. The list as a working tool (item 21a) ✅ 2026-11-24: keyboard cursor and selection (j/k, x, Shift+j/k, * a/n, Enter/o, e, f), bulk bar (tag incl. a new tag, purpose with 1-7, people, visibility; refused trips listed), paging ("Show more"), person and visibility filters, the desktop header search (`/`), selected trips highlighted on the map. The complete trip page (item 21b) ✅ 2026-11-24 (merges after 40e): tags with authors, notes, per-leg people and "I was on this leg", public consent, participants' own legs and their notes, flight airline/seat/cabin and airport codes, `/tags`, `/purposes`, `/people`, the trip status filter (`TripStatus`); `PATCH /persons`, `POST/PATCH /purposes`, `GET /reference/airlines`; Viewers can't edit people at the SQL level either (D-113); matrix 113 × 7. Leg vehicle picker waits for item 23 |
| 4.4 Vehicles | Ownership history with exactly-one-owner constraint; "is it this one?" check; merge; rental quick-add |
| 4.5 Map matching | Drive legs map-matched with Valhalla; stored as frozen routes |
| 4.6 Trip spreadsheet import | Trips entered in an `.xlsx` (one tab per trip: trip fields, stops, legs citing stops by row) are previewed with errors by tab/row/column and imported through the trips service layer; re-import by trip key follows rules 6 and 7. Design and template done 2026-11-18 ([trip-sheet.md](trip-sheet.md), D-95). Backend (item 14c-1) ✅ 2026-11-24: `trip_sheet` upload kind and worker parse to own-only records, preview / commit / discard API and CLI, re-import by key (rules 6 and 7), matrix 108 × 7 (D-100 to D-102); preview UI is item 14c-2 |

### Phase 5 — Routes ⏳

| Milestone | Acceptance criteria |
|---|---|
| 5.1 Routing proxy ✅ 2026-11-19 | Valhalla → ORS → FOSSGIS chain; OSRM-format normalization; throttle/debounce; provider policy compliance; provenance recorded. Item 25: `POST /api/v1/routing/route` (`travel/routing/`: providers, chain, per-user throttle, 10-minute per-user cache under RLS, ORS/FOSSGIS server-wide limits); ORS built and tested against mocks, live once `ORS_API_KEY` is set; FOSSGIS 1 req/s server-wide (D-92) |
| 5.2 Manual trips ✅ 2026-11-19 | Start/end/waypoints → proposed route → accept. Item 25: the leg route page proposes a route from the leg's stops through optional via points, shows provider, road-data date and attribution, and saves it (`POST /legs/{id}/routes`) as a new frozen version with simplified copies; routed legs draw solid on the trip map; e2e routes a Kansas leg through Valhalla |
| 5.3 Drag-to-reshape ✅ core 2026-11-19, polish 2026-11-24 (item 27, D-106) | Anchor-point editing per §13; saved as a new frozen version; never recomputed (test). Item 26: gpx.studio port (MIT) in `frontend/src/routing/editor/` (zoom-dependent anchors, drag anchor or line, click to add/append, shift/right-click to delete, undo/redo, desktop-only lazy chunk); `POST /legs/{id}/routes/edited` assembles the line from cached proposals, saved versions of the leg and validated drawn points, `hand_edited` with `Route.sources` (D-93). Item 27: anchor popup, touch, sources in the version list, expired proposals re-proposed before falling back to drawn (D-106) |

### Phase 6 — Statistics ⏳

| Milestone | Acceptance criteria |
|---|---|
| 6.1 Boundaries + geocoding 🔄 | Natural Earth, Census counties, GeoNames loaded; stops named offline. GeoNames part ✅ 2026-11-18 (item 14, D-94): `load_gazetteer` (cities500 + US populated places, country and admin-1 names; pinned snapshot + SHA-256), `GET /reference/places` (prefix, accents folded, by population, ", state" qualifier), "find a city" in the stop editor of both shells. Natural Earth, Census and reverse geocoding: item 14a |
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
| 8.0 Production stack ✅ 2026-11-19 (item 40a, D-96) | Separate compose project `travel-history-prod` with its own DB volume, networks and `.env.prod` (0600, outside the repo); deployed only from pushed `main` with images tagged by commit (`./dev prod deploy`); gunicorn + production SPA on `127.0.0.1:8784` only; `ingest` moved here (profile `tracker`, stopped); auth.md §7.7 enforced at startup; trips.* → travel.* redirect; dev never answers a public name; per-IP limits on `/`, `/auth/login`, `/auth/callback`; `./dev prod smoke` passes; memory in §21.4. Not exposed: sign-in (40c) and go-live (40e) follow |
| 8.0b Real data into production 🔄 2026-11-19 (item 40b, D-97) | `./dev prod import-from-dev`: refusals (migrations differ; a real identity in production), piped copy into a staging DB, dry-run inventory and pruning to `dev-admin`, verification against dev (batch 33 = 193,009 points), raw files copied and checksummed, swap. Rehearsal passed; `./dev prod restore-test` passes; `./dev prod import-test` runs it all against scratch containers with SYNTHETIC data (both refusals included). Open: the encrypted backup with the real key (`AGE_RECIPIENT`, G-2); the final copy runs in 40c |
| 8.0c Authentik sign-in, built ✅ 2026-11-23 (item 40c-1, D-103, D-104) | Production OIDC for Authentik: per-provider issuer (trailing slash either way), confidential client required, `travel-users` list and `amr` second factor (G-5) checked before any account, `auth_time` for re-auth, end-session logout with `id_token_hint`; tested against a synthetic Authentik through the real Authlib client. Sign-in over an SSH port-forward to `localhost:8784` (G-4) via `HttpsRedirectMiddleware`, public names unchanged. Owner-role `rebind_identity` (G-3) and `link_person`, with RLS-level tests. Open: deploy and final copy (40c-2), the handover after Adam's first sign-in (40c-3) |
| 8.0d Go-live hardening ✅ 2026-11-24 (item 42a, D-107 to D-111; the 41a review's F-1 to F-3, F-6 to F-11) | CSP and X-Frame-Options on the PWA's own files (WhiteNoise wrapped); per-endpoint body limits (2.5 MiB default, 32 MiB chunks, 5 MiB tracker posts); browser sessions back through Authentik hourly, refused sign-ins end the session, bearer tokens checked for `travel-users` per request, `deactivate_account` (owner role, dry run, audited, `--reactivate`, `--sign-out`); no API docs/schema in production, provider errors = no user with a 30 s back-off; tunnel requests need a public Host; scope `all` needs the provider; no public trips before T37 (422); e2e leftovers (persons, tags, SYNTHETIC trip sheets) in the dev copy and `e2e_cleanup`; base digests refreshed and builds take Debian's security updates (CPU smoke on the non-AVX host). `./dev golive-smoke local` checks each where it can. |
| 8.1 Request access | Landing, form, Turnstile (test keys), rate limits, push + email to Admin, re-auth approve, provisioner stub, invite links/QR, allowlist, onboarding |
| 8.2 Roles + contributions | Member/Viewer behaviour per §6.3 in the UI; contributions with attribution |
| 8.3 Duplicates | Overlap check offers "join existing trip"; merge tool (earlier creator stays owner) |
| 8.4 Transfers | Bulk transfer of trips/vehicles to a new member; shared trips stay with Adam |
| 8.5 Public | Snapshot builder, public renderer on `travel_public`, privacy zones, consent, leak tests, rate limits, profiles |
| 8.6 Go-live checklist 🔄 2026-11-23 (item 40d, D-105: the go-live slice) | Written for Adam in docs/go-live.md: Authentik checks (group binding, strict redirect URIs, forced second factor, removing G-4's temporary URIs), adding a family member (`travel-users` → second factor → Member → `link_person`), tunnel routes (travel.* and trips.* to the production `web` on `localhost:8784`, the tracker path rule retired, `ingest` stays stopped), DNS, the scope flip (`TRAVEL_PUBLIC_SCOPE=all`; TLS-proxy, HSTS and `CF-Connecting-IP` already forced by compose.prod.yaml), rollback, what Cloudflare sees. `./dev golive-smoke`: `local` runs HEAD's production image with scope `all` against a throwaway DB on 127.0.0.1 (for 41a), a URL checks through Cloudflare (40e). Open (item 40): SMTP account + DNS, Turnstile keys, request access, public pages |

### Phase 9 — Android companion ⏳ (against the mock OIDC provider until Authentik is live)

### Phase 10 — Later ⏳

Immich integration · desktop wrapper · regional PMTiles · remaining flight importers · bake-off
conclusion (after ≥ 4–6 weeks including a road trip).
