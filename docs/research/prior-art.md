# Prior-art evaluation

Moved from PLAN.md §1 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 1. Prior-art evaluation

Full notes: `docs/research/adventurelog-evaluation.md`, `docs/research/reference-projects.md`.

### 1.1 AdventureLog as a fork base → **not forked; building fresh**

AdventureLog (Django 5.2 + GeoDjango + PostGIS + SvelteKit, GPL-3.0-only in practice) was
cloned read-only and its models, views, permissions, settings and tests were read on 2026-10-19
(branches `main` v0.13.0, `development`, and the unreleased trip-rework branch).

| Criterion | Finding | Score (0–3) |
|---|---|---|
| Backend stack | Django 5.2, GeoDjango, PostGIS — matches | 3 |
| Frontend stack | SvelteKit 2 / Svelte 5 (~52k lines Svelte, 0 frontend tests) — would be discarded | 1 |
| Trips → ordered legs | `Collection` + generic `CollectionItineraryItem`; no legs | 1 |
| Frozen versioned routes | No LineString fields anywhere; transport has two points | 0 |
| Participants + per-leg overrides | Only `Collection.shared_with` (users) | 0 |
| Contribution permissions (author attribution, edit-own-only) | Shared users get full write; their items are re-owned by the collection owner | 0–1 |
| Row-level security | None (queryset filtering only) | 0 |
| Vehicles with ownership history, home periods, person ≠ user | None | 0 |
| Raw imports, append-only points, Timeline import, tracker ingestion | None (backup ZIP, GPX per activity, Strava) | 0 |
| Routing / drag-to-reshape | None | 0 |
| Offline reverse geocoding, county stats | Online Nominatim/Google; region/city counts; no counties | 1 |
| Flights with airport/airline data | Free-text codes on `Transportation` | 1 |
| Public pages with allowlist + privacy zones | `is_public` flags; allowlist only on the unreleased branch; no privacy zones | 1 |
| OIDC | django-allauth (old 0.63) `openid_connect`, Authentik guide | 3 |
| Immich | Proxied thumbnails, but API key stored in plaintext and returned to the client, `Cache-Control: public` on private images, no SSRF check | 2 |
| Security posture | DEBUG defaults on, `ALLOWED_HOSTS=['*']`, default admin/admin, uploads keep EXIF GPS; good protected-media pattern | — |
| Tests | 189 backend tests (4 for collection sharing), 0 frontend | — |
| Maintenance | Active: 8 releases in 2 years (v0.13.0 on 2026-08-12), 3.8k stars, 22–44 authors/yr; top author 45–56 % of recent commits, 89 % all-time → bus factor ≈ 1; a hosted commercial "cloud/billing" mode is being added | — |
| Upstream merge cost | ~2 months of upstream touched 318 files (+28k/−14k lines); the trip rework branch rewrites `Collection` again. Estimated < 10 % of future upstream commits would still apply after rewriting its core models and replacing its frontend | — |

**Decision rule applied:** fork only if it saves substantial work *and* its core models can
absorb ours without being rewritten. Neither holds: every core model (trips/legs/routes,
participation, RLS, vehicles, home periods, raw history) would be new or rewritten, the frontend
would be replaced, and upstream churn makes merging impractical. A fork would be "building fresh
with extra baggage" plus GPL-3.0 obligations on the Android APK. **Outcome: build fresh** (D-01).
Ideas worth reimplementing (not copying): exactly-one-parent constraints, an allowlist with
sections off by default, protected media served via the app with permission checks, prefixed
hashed API keys, a tiered-access Immich proxy (but private caching, encrypted key).

### 1.2 Reference projects

| Project | License (checked 2026-10-19) | Activity / bus factor | How we use it |
|---|---|---|---|
| gpx.studio | **MIT** (since 2024-06) | 663 commits/yr, one author ≈ 99 % | **Port** its anchor-point drag-to-reshape (`routing-controls.ts`, `simplify.ts`) to a React/TS controller **with attribution** (§13.4, §27). Its routing servers are its own (GraphHopper without a car profile, brouter.de) — not used. |
| AirTrail | **GPL-3.0** | v3.13.0 (2026-09), 33 authors/yr, top 60 % | **Reimplement** importers for MyFlightRadar24, Flighty, App in the Air, TripIt, JetLog, byAir from format specs written in our own words (`docs/research/reference-projects.md`). No code copied → no GPL obligation. |
| TREK | **AGPL-3.0** (MIT for one day in 2026-03) | very active, top 58 % | Ideas only: Atlas (visited countries/regions, planned vs visited, region marking from zoom 5, streaks), photo-first journal. |
| Reitti | **AGPL-3.0 since v5.0.0 (2026-07-05)**, MIT before | active, top ≈ 60–90 % | Ideas only: per-window speed classification with per-user thresholds, smoothing of implausible short runs, user overrides as timestamped modes. |
| Dawarich | **AGPL-3.0** | very active, top ≈ 94 % | Ideas only: Android vs iOS Timeline format detection by keys, streaming in batches, dwell-sweep visit detection, user edits as overlays that survive re-runs. |
| GeoPulse | **custom BSL 1.1** since 2025-11 (AGPL before), change date 2075 | active, top ≈ 98 % | Ideas only: rule cascade for trip classification (flight/boat/train/bike/car/walk by avg/peak speed, variance, water overlap), noise rejection. |
| maplibre-gl-directions | MIT | v0.10.1 (2026-09), one main maintainer | Considered for drag-to-reshape; not chosen (no zoom-dependent anchors, no editing of recorded tracks, pinned to one MapLibre major per release) — D-14. |

**License consequences (recorded per the brief):**

- No code from AGPL (TREK, Reitti v5+, Dawarich) or BSL (GeoPulse) projects, ever.
- No code from GPL-3.0 projects (AdventureLog, AirTrail) either: copying any would make this
  project GPL-3.0, and **distributing the Android companion APK is distribution of object code**
  (GPL §6) — we would have to offer complete source to every recipient and license the whole
  work under GPL-3.0 (§5c). Reimplementing from format descriptions avoids this; copyright does
  not cover ideas or methods (17 U.S.C. §102(b)).
- MIT code (gpx.studio) may be used with its copyright and permission notice kept (§27).
- Datasets carry their own licenses (§27): ODbL for OpenFlights, CC BY 4.0 for GeoNames.
