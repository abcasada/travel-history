# Map rendering

Moved from PLAN.md §14 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 14. Map rendering

- Basemap: hosted OpenFreeMap style (no key). The style URL is configuration, so a self-hosted
  regional PMTiles basemap can replace it later without code changes.
- **Raw points as vector tiles**, never GeoJSON: `GET /api/v1/history/tiles/{z}/{x}/{y}.mvt?from=&to=&source=`
  generated in PostGIS with `ST_AsMVTGeom`/`ST_AsMVT` inside the request's RLS transaction, so a
  user can only ever tile their own points. At low zooms points are aggregated to a grid
  (`ST_SnapToGrid` by zoom) to keep tiles small. Tiles carry `Cache-Control: private`.
- **Implementation (milestone 2.3, 2026-11-11):** `backend/travel/history/tiles.py`.
  - *Why a key, not the GiST index:* under RLS, PostgreSQL uses a query condition as an index
    condition only if its operator is LEAKPROOF. PostGIS's `&&` is not, so `travel_app` could not
    use the GiST index on `geom` and every tile scanned the user's whole history (135 ms per
    empty z16 tile at 300k points, growing linearly). Points therefore carry a generated
    `tile_key` bigint (the point's zoom-20 Web Mercator tile, x/y bits interleaved; history
    migration 0008) with a btree index on (owner, tile_key). A map tile at zoom ≤ 20 is one
    contiguous key range; bigint comparisons are leakproof. Ranges are bound as constants, not
    joined from an array, so the planner estimates them from statistics.
  - *Points layer `points`:* below z14, and in tiles with over 10,000 points above it, points are
    counted into a 128 × 128 grid per tile (`n` per cell). Below z14 a cell is exactly a zoom
    z+7 tile, so cells are grouped by key prefix (`tile_key >> shift`), integer work off the
    index; dense z14+ tiles use the same grid computed from coordinates. Otherwise one feature
    per point with `ts` (epoch s) and `src`. Each tile also draws a 4-cell margin from its
    neighbours (read from their adjacent quarter-tiles) so circles aren't cut at tile edges.
  - *Segments layer `segments`* (`/history/segments/tiles/…`, z5–18): current versions only,
    simplified to ~1 px, newest 3,000 per tile (`X-Tile-Truncated` when capped), with `kind`,
    `activity`, `semantic`, `t0`/`t1`. Segment tiles still scan the user's segments (no key yet);
    fine at tens of thousands of segments.
  - *Bounds:* zoom 0–18 (404 otherwise), x/y inside the grid, a 10 s statement timeout per tile
    query (→ 503 + `Retry-After`, in a savepoint so the request's RLS transaction survives), JIT
    off for these queries (compiling cost 0.5–1 s). Worst case ≤ 136² cells per points tile.
    Responses are gzipped when accepted; `Cache-Control: private, max-age=300`; the client adds
    `rev=` (latest import) to bust its cache after an import.
  - *Coverage strip:* `GET /history/coverage?from=&to=&tz=` counts points and current segments
    per local day (a segment counts on every day it touches), ≤ 400 days per request, plus the
    user's first and last day with data.
  - *Timings* (synthetic: one user, 300k points on a year-long random walk + 50k points of
    another user at the same place; 1,666 path segments; current Xeon host, dev DB, warm):
    z2 204 ms · z6 252 ms · z10 98 ms (98 KiB, before gzip) · z13 34 ms · z16 19 ms ·
    z6 one month 60 ms · segments z5 38 ms (84 KiB) / z9 18 ms / z13 14 ms · coverage, one
    year 285 ms. Low zooms without a date filter read every point of the user (~0.7 µs/point),
    so a multi-million-point history will approach the timeout at z0–6; the planned fix is a
    per-day grid roll-up maintained by imports and ingestion (deferred; measure with the T5
    large-import test or the real export first).
- **Trips as vector tiles:** `GET /api/v1/tiles/trips/{z}/{x}/{y}.mvt` reads
  `route_simplified` for the matching zoom bucket (precomputed with `ST_SimplifyPreserveTopology`
  at 4 tolerances when a route version is created), filtered by RLS visibility.
- Flights as great-circle arcs, split at the antimeridian (§12).
- Why not Martin: it has no built-in per-user authorization; serving private points through it
  would need a separate auth proxy and a second path around RLS. In-Django `ST_AsMVT` keeps one
  authorization path (§24, D-12).
