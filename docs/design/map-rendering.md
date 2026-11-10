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
- **Trips as vector tiles:** `GET /api/v1/tiles/trips/{z}/{x}/{y}.mvt` reads
  `route_simplified` for the matching zoom bucket (precomputed with `ST_SimplifyPreserveTopology`
  at 4 tolerances when a route version is created), filtered by RLS visibility.
- Flights as great-circle arcs, split at the antimeridian (§12).
- Why not Martin: it has no built-in per-user authorization; serving private points through it
  would need a separate auth proxy and a second path around RLS. In-Django `ST_AsMVT` keeps one
  authorization path (§24, D-12).
