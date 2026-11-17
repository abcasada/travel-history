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
    counted into grid cells (`n` per cell). Below z14 a cell is exactly a zoom z+7 tile; a dense
    tile at z14+ gets zoom-20 cells (the key's resolution: 64 a side at z14, 16 at z16, 4 at
    z18). A cell is a key prefix, so counts are integer work without touching geometry.
    Otherwise one feature per point with `ts` (epoch s) and `src`. Each tile also draws a 4-cell
    margin from its neighbours (read from their adjacent quarter-tiles) so circles aren't cut at
    tile edges.
  - *Point roll-up (work-order item 5a, history migration 0010):* cell counts come from
    `history_pointrollup`, not from the points: per owner, cell zoom (8, 10, …, 20; a tile uses
    the first level at or below its cell zoom and groups by prefix), grain (UTC day, or UTC year
    with `period` = 1 January), source and cell, the number of points. A date range is split
    into whole UTC years (year rows), whole UTC days (day rows) and the partial days at its ends
    (raw points by key range), so the result is exactly what counting the points would give
    (tests compare both at every zoom band and range shape). Statement-level AFTER INSERT/DELETE
    triggers on `history_locationpoint` (transition tables) keep it equal to the points in the
    same transaction: an insert adds what was really inserted (`ON CONFLICT DO NOTHING`
    duplicates aren't in the transition table), a delete subtracts and removes emptied rows.
    Points are append-only and a re-import never deletes (rule 6), so imports, re-imports,
    tracker ingestion and purges all stay consistent without application code. Upserts run in
    key order (no lock-order deadlocks between writers of one owner), and tracker and import
    points never share a row (the source is in the key). RLS like the points: `own_all` for
    every command, the triggers run as the caller. Not mirrored: TRUNCATE (test teardown only).
  - *Segments layer `segments`* (`/history/segments/tiles/…`, z5–18): current versions only,
    simplified to ~1 px, with `id`, `kind`, `activity`, `semantic`, `t0`/`t1`. Segments carry a
    generated quadtree key `seg_key` (history migration 0011): the smallest tile (zoom ≤ 20)
    holding the whole bounding box, as its zoom-20 Morton prefix `<< 5 | zoom`, with a partial
    (owner, seg_key) index on current versions. Quadtree tiles are nested or disjoint, so a
    segment can touch a map tile (or its margin pieces) only if its key lies in a piece's key
    range or equals one of the pieces' ancestors' keys; both are leakproof bigint conditions
    under RLS. Over 3,000 segments in a tile, nothing is dropped any more: geometries are
    snapped to a 64 × 64 lattice per tile (4 px), and those that coincide (same shape, kind and
    activity) merge into one feature with `n` and the span `t0`/`t1` (`X-Tile-Aggregated: 1`).
    Only if even the merged features exceed 10,000 are the least travelled left out
    (`X-Tile-Truncated: 1`).
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
