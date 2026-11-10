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

### 13.2 Saved routes are frozen

A saved route stores geometry, control waypoints, kind, engine, engine version, data date and
time. It is **never recomputed**: there is no code path that re-routes a saved version; a DB
trigger rejects `UPDATE` on `route`; the editor always creates a new version. Routing uses
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

### 13.5 Valhalla service and tile-build strategy

- **Image:** `ghcr.io/valhalla/valhalla-scripted:3.9.1` (the old gis-ops image is deprecated).
  Own compose project `valhalla` in `valhalla/`, on the external network `valhalla`; no
  published ports (optional `127.0.0.1` debug port). Build flags: admins + time zones on,
  **elevation off** (only matters for bike/foot costing; ~80–120 GB for North America),
  transit off, tar on.
- **Development now: Kansas** (Geofabrik `kansas-latest.osm.pbf`, 117 MB). Expected on this
  host: < 2 GB RAM with `server_threads=2`, ~1–2 GB disk, tens of minutes. Coverage polygon =
  Kansas bbox.
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
