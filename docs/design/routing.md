# Routing, map matching, Valhalla

Moved from PLAN.md §13 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 13. Routing, map matching, Valhalla

### 13.1 Routing proxy

The frontend calls only `POST /api/v1/routing/route` (authenticated). Request:
`{waypoints: [[lon, lat], …] (2–25), profile: "auto"}`. Response: **OSRM format**
(`{code, routes: [{geometry (GeoJSON LineString), distance, duration, legs: [...]}], waypoints}`)
plus `provenance: {engine, engine_version, data_date}` so the saved route records how it was
made.

Provider chain:

| Order | Provider | When | Notes |
|---|---|---|---|
| 1 | **Valhalla** (self-hosted, `valhalla:8002` on the shared network) | all waypoints inside the coverage polygon (North America once built; Kansas during development) and the service is healthy | `"format": "osrm"`, `shape_format: geojson` → already OSRM-shaped |
| 2 | **OpenRouteService** (hosted, API key in `.env`) | outside coverage, or Valhalla down | `driving-car`; polyline5 decoded and re-shaped to OSRM; free plan 2,000 directions/day, 40/min; results are CC-BY-SA 4.0 → attribution "© openrouteservice by HeiGIT, data © OpenStreetMap" wherever an ORS-derived route is shown, including public pages. **Their terms prohibit transmitting personal data**: only user-drawn waypoints are ever sent (never raw history or traces, never map-matching), and requests carry no user identity. See Q-9. |
| 3 | **FOSSGIS OSRM** (`routing.openstreetmap.de/routed-car`) | emergency only, when 1 and 2 fail | ≤ 1 request/s **globally** (token bucket in PostgreSQL), identifying `User-Agent: travel-history/<version> (+https://travel.adamcasada.com)` with **no personal data**, attribution + "fix the map" link, never for bulk work |

- Debounce in the client (300 ms after the last drag movement; at most one request in flight
  per editor) and throttle per user on the server (10 requests/10 s, burst 5). Identical
  requests within 10 minutes are served from a short-lived cache table.
- **Google routing is excluded (confirmed 2026-10-19):** the Google Maps Platform ToS §3.2.3(e)
  forbids using Google Maps Core Services "with or near a non-Google map", and the Service Specific
  Terms for the Directions API (§4.2–4.3), Routes API (§19.1–19.3) and Roads API (§17.2–17.3)
  forbid use with a non-Google map and allow caching lat/lng for at most 30 days. We draw on
  MapLibre/OpenFreeMap and store routes permanently, so Google is incompatible. (Google place IDs
  from Timeline may be stored indefinitely: SST §A.3.)

**As built (item 25, D-92):** `travel/routing/` — `providers.py` (the only code that builds
outbound requests: headers are the generic `ROUTING_USER_AGENT`, `Accept` and, for ORS only, the
key; bodies carry only the waypoints rounded to 6 decimals), `services.py` (chain, throttles,
cache), `api.py`. The answer adds `provenance.attribution` and `produced_at`, and `cached`.
A provider that answers "no route" ends the chain (422) so the waypoints don't go to the next
provider; "unavailable" (5xx, 401/403/429, timeout, no key) tries the next one. Limits: per user
10/10 s and 5/2 s (429 + Retry-After); ORS 40/min and 2,000/day and FOSSGIS 1/s counted for the
whole server (503, with Retry-After when FOSSGIS is only busy). The cache
(`routing_routerequestcache`) is per user under RLS (own rows only; Members and the Admin may
write) and purged hourly by the `routing_cache` user job. Settings: `VALHALLA_DATA_DATE`
(else the tile build time from `/status`), `ORS_API_KEY` (empty = ORS skipped), `ORS_URL`,
`FOSSGIS_OSRM_URL`, `ROUTING_FOSSGIS_ENABLED`, `ROUTING_TIMEOUT`, `ROUTING_CACHE_SECONDS`.
Saving: `POST /legs/{leg_id}/routes {waypoints, note}` takes geometry and provenance from the
caller's own cached proposal for exactly those waypoints (409 once it expired), never from the
client; only drive, bus and other legs take a road route (422). The hand-edited geometry of the
drag editor (item 26) saves through `POST /legs/{leg_id}/routes/edited` (§13.4, D-93).

### 13.2 Saved routes are frozen

A saved route stores geometry, control waypoints, kind, engine, engine version, data date,
attribution and time. It is **never recomputed**: there is no code path that re-routes a saved version; a DB
trigger rejects `UPDATE` on `route`; the editor always creates a new version. Saving inserts version n+1 (leg row locked), its
`route_simplified` copies (zoom buckets 3/6/9/12, `ST_SimplifyPreserveTopology` at about one
pixel), and moves `leg.current_route` and `leg.distance_m` (`travel/trips/route_versions.py`). Routing uses
today's road network; dragging is how old trips get fixed.

### 13.3 Map matching (Timeline drive legs)

Worker job per drive leg: take the owner's points in the leg's time range (RLS context = owner),
thin to ≥ 25 m spacing, cap to ≤ 16,000 shape points per request (Valhalla default
`max_shape`; longer legs are chunked with overlap and stitched), call Valhalla `trace_route`
with `shape_match: map_snap`, `costing: auto`, `use_timestamps: true`,
`trace_options.search_radius` from point accuracy (≤ 100 m), and store the result as route kind
`map_matched` with `source_time_range`. Discontinuities (no match) are kept as GPS straight
segments and flagged. Meili cache limits are set in the Valhalla config to bound RAM.

### 13.4 Drag-to-reshape: port gpx.studio's anchor routing (MIT, with attribution)

Chosen over `@maplibre/maplibre-gl-directions` (D-14): gpx.studio's approach can edit **any**
existing line (map-matched GPS, routed, hand-edited), shows anchors by zoom level, and re-routes
only the affected span; maplibre-gl-directions only edits routes it created itself, has no
zoom-dependent anchors and pins one MapLibre major per release.

Port (TypeScript, framework-free controller attached to the MapLibre map; React only renders
the toolbar):

- **Anchors** for a loaded line: Ramer–Douglas–Peucker with ε = 1 m on metric cross-track
  distance; each kept point gets `zoom = clamp(0..22, round(log2(R·cos(lat) / d)))`; endpoints
  zoom 0; one symbol layer per zoom with `minzoom`. Saved control waypoints are always zoom 0.
- **Neighbours** are the anchors visible at the current zoom.
- **Drag on the line** → temporary anchor; on release one request (previous anchor, new point,
  next anchor) through our proxy replaces the points between previous and next; the new point
  becomes a zoom-0 anchor; failure reverts.
- **Drag an anchor** → re-route its two adjacent spans; **delete an anchor** → re-route
  previous → next; **click the map** → append; **click the line** → insert an anchor without
  re-routing.
- Undo/redo stack; **save** creates a new frozen `route` version with `kind = hand_edited` (or
  `routed` if it came straight from a proposal), waypoints = the zoom-0 anchors.
- Attribution: gpx.studio's MIT notice is kept in the ported files' headers and in
  `THIRD_PARTY_NOTICES.md`.

**As built (item 26, D-93, pending Adam).** Ported from gpx.studio commit 2e0edc7 (2026-11-15)
into `frontend/src/routing/editor/`:

- `geometry.ts` (from gpx-rs `anchors.rs`, `simplify.rs`, `utils.rs` and `closest-point.ts`):
  iterative RDP with selection distances, `anchorZoom`, `computeAnchors`, closest point/segment.
- `model.ts` (the rules of `routing-controls.ts`): an immutable state of points, each with its
  anchor zoom (or none) and its source (a cached proposal, a saved version, or drawn); plans for
  move, drag-the-line, append and delete; `applyRoute` splices an answer between the kept
  anchors exactly as `routeBetweenAnchors`; `toPieces` turns the line into save pieces.
  Adaptations: dragging the line first splits it at the grabbed place (a straight drawn line has
  no track point there); clicking the line marks a point within 1 m or inserts one.
- `controller.ts` (the map half of `routing-controls.ts`): one GeoJSON source of anchors
  filtered by `minZoom`, a wide invisible hit line, the temporary anchor that follows the
  pointer along the line, drag with pan disabled; shift-click or right-click deletes (item 27 added the popup and
  touch), a click elsewhere appends.
- `editorStore.ts` (zustand): undo/redo of whole states (100 steps; `u` / `Shift+U`), one
  routing request in flight (edits while routing are ignored; requests go out on release, not
  while dragging, so no debounce is needed), errors snap the line back.
- `RouteEditor.tsx` / `RouteEditorLayer.tsx`: lazy chunks rendered only in the desktop shell from
  the leg route page. "Reshape on the map" starts from the unsaved proposal, else the current
  version (its control points become fixed anchors), else a straight line between the leg's
  stops. While editing, trip-line clicks don't navigate and the propose form is hidden.

Saving (`POST /legs/{id}/routes/edited`, `travel/trips/route_edits.py`): proposal slices come
from the caller's own cache, version slices from this leg's saved versions, drawn points are
validated (ranges, ≤ 10,000 drawn, ≤ 2,000 pieces, ≤ 200,000 points, ≤ 20,000 km). The version
is `hand_edited` (or `routed` for exactly one whole proposal) with `Route.sources` (per source:
engine, points, verified), engine = the one engine or `mixed`, the oldest road-data date and
every provider's credit. Expired proposals: 409 with their piece positions; the editor resends
them once as drawn points with an `engine` claim (credit only).

**Polish (item 27, D-106).** Frontend only; no API change.

- **Anchor popup** (gpx.studio's anchor popup): clicking an anchor opens a MapLibre popup
  saying whether it is a fixed point (saved with the version) or a shape point, with
  "Remove this point" and, for shape points, "Keep as a fixed point". A click elsewhere or
  Escape closes it; shift-click and right-click still remove at once.
- **Touch:** a finger on an anchor drags it (pan off while dragging; a second finger cancels);
  a tap opens its popup; holding the line still for 400 ms grabs it (a plain swipe pans the
  map), and releasing without moving keeps a fixed point there. Browser follow-ups of a touch
  (emulated mouse events, the long-press context menu) are ignored for 800 ms, so a long press
  never deletes. The editor still renders only in the desktop shell (tablets, touch laptops).
- **Version list:** each version shows `Route.sources` ("Made from: Valhalla (self-hosted)
  route, 1,204 points, checked; 2 points drawn by hand, not checked").
- **Expired proposals are re-proposed:** on the save's 409, the editor asks
  `/api/v1/routing/route` again for each expired proposal's exact waypoints (about one request
  a second to stay under the per-user limit; one retry after a 429; at most 20). If the answer
  has exactly the points the line uses, the server has it cached again and the piece saves as
  verified; otherwise (roads or provider changed, routing failed, over the cap) only that piece
  goes as drawn points with its engine claim. The user's line is never replaced by the new
  answer, and nothing re-routes a saved version (rule 5).

### 13.5 Valhalla service and tile-build strategy

- **Image:** `ghcr.io/valhalla/valhalla-scripted:3.9.1` (the old gis-ops image is deprecated).
  Own compose project `valhalla` in `valhalla/`, on the external network `valhalla`; no
  published ports (optional `127.0.0.1` debug port). Build flags: admins + time zones on,
  **elevation off** (only matters for bike/foot costing; ~80–120 GB for North America),
  transit off, tar on.
- **Development now: Kansas** (Geofabrik `kansas-latest.osm.pbf`, 117 MB). Expected on this
  host: < 2 GB RAM with `server_threads=2`, ~1–2 GB disk, tens of minutes. **Measured
  2026-11-18 (item 17, [resource-budget §21.2](resource-budget.md)):** 188 s, 773 MiB peak,
  422 MB per build; service 130–237 MiB. Coverage polygon = the Kansas bbox with the north-east
  corner cut along the Missouri River (`backend/travel/routing/coverage/kansas.geojson`, D-91).
- **As built (item 17, D-91; operations in [docs/valhalla.md](../valhalla.md)):** image pinned by
  digest; our `valhalla/build.sh` replaces the image's root entrypoint (non-root, generic
  User-Agent, md5 check, builds into `valhalla/data/builds/<ts>/`, then switches `current`);
  the service runs `valhalla_service` read-only with a `/status` health check. Config: trace
  `max_shape` 16,000, `max_distance` 200 km, accuracy/search radius ≤ 100 m, tile cache 256 MB
  per thread, Meili grid cache at its default; default speeds not applied.
- **Full North America (19.5 GB PBF, 2026-10-18) — ask Adam before running.** Estimates (scaled
  from published planet builds; low confidence):

  | Resource | Estimate |
  |---|---|
  | Peak RAM | ≈ 16–28 GB with 4 build threads; RAM scales with thread count (Europe ran out of memory at 16 GB with default threads; North America was built on 64 GB) |
  | Disk (SSD/NVMe) | ≈ 120–150 GB free during the build: PBF 19.5 GB + intermediate files ≈ 50 GB + tiles 15–30 GB, briefly twice during tar creation |
  | Disk after build | ≈ 20–35 GB (tile tar + admin/tz DBs); PBF and intermediates deleted |
  | Duration | ≈ 2–6 h on a Ryzen 5 3600 with NVMe and 4 threads; many hours to days on the current host's HDD (and it lacks the RAM) |
  | Serving | a few hundred MB RAM + OS page cache; tiles memory-mapped |

- **Options on a shared 32 GB machine** (all need approval):
  1. **Local build on the Ryzen host (recommended for quarterly rebuilds):** `server_threads=4`
     (sets build concurrency), container `mem_limit: 26g`, a temporary 16 GB swap file on the SSD
     as insurance (host change → needs approval), pause heavy services (Immich ML, other batch
     jobs) during the window, run overnight, build into a new directory and swap the tar in
     atomically so routing stays up during rebuilds.
  2. **Rented cloud machine (recommended for the first build if the Ryzen isn't ready):** e.g. an
     8 vCPU / 32–64 GB VM with NVMe for a few hours (cost: a few dollars; needs Adam's account),
     build with 8 threads, then `rsync` the ~20–35 GB tar home and delete the VM.
  3. **Not on the current host:** 11 GiB RAM, 28 GB free SSD, HDD-only bulk space.
- **Rebuild cadence:** quarterly, after Geofabrik's update; the old tiles keep serving until the
  new tar is verified (a smoke test of 20 known routes compared with the previous build).
