# Valhalla (self-hosted routing)

Design: [docs/design/routing.md §13](design/routing.md) (D-15, D-29, D-40). Measurements:
[resource-budget.md §21.2](design/resource-budget.md).

## What runs where

- Its own compose project `valhalla` in `valhalla/` (`valhalla/compose.yaml`), image
  `ghcr.io/valhalla/valhalla-scripted:3.9.1` pinned by digest (D-78; checked on the non-AVX
  Xeon). It runs as your uid, read-only, with no published ports.
- The app reaches it as `http://valhalla:8002` (`VALHALLA_URL`) over the external Docker
  network `valhalla`, which `./dev setup` creates and the app's backend services join.
- Data lives in `valhalla/data/` (git-ignored, on the SSD):
  `pbf/` the extract, `builds/<UTC timestamp>/` complete builds (config, `tiles.tar`, admin and
  time-zone databases, `BUILD_INFO.json`), and `current` → the build the service loads. The
  newest two builds are kept for rollback.
- The coverage polygon the routing proxy uses to choose Valhalla is
  `backend/travel/routing/coverage/<name>.geojson`, picked by `VALHALLA_COVERAGE` (default
  `kansas`; `travel.routing.coverage.in_valhalla_coverage`).

## Commands

```
./dev valhalla build     # download the extract (if newer) and build tiles into a new directory
./dev valhalla up        # start (or restart into) the current build; waits for the health check
./dev valhalla status    # container, BUILD_INFO.json, /status
./dev valhalla smoke     # from the app's tools container: route Wichita → Salina, then map-match
                         # a synthetic track made from that route
./dev valhalla logs | down
```

`build` restarts a running service so it picks up the new tiles. The service keeps serving the
old build while a new one is being made, and a failed build removes its directory and never
moves `current`.

Debug access from the host (optional, never commit it): add
`ports: ["127.0.0.1:8784:8002"]` to the service in a local override, or run
`docker compose -f valhalla/compose.yaml exec valhalla curl -s localhost:8002/status`.

## Settings (environment for `./dev valhalla build`)

| Variable | Default | Meaning |
|---|---|---|
| `VALHALLA_PBF_URL` | Geofabrik `north-america/us/kansas-latest.osm.pbf` | the extract; Geofabrik's `.md5` is checked |
| `VALHALLA_BUILD_THREADS` | 2 | build concurrency (peak RAM grows with it) |
| `VALHALLA_BUILD_MEM_LIMIT` | 4g | container limit for the build |
| `VALHALLA_SKIP_DOWNLOAD` | 0 | 1 = rebuild from the extract already in `data/pbf/` |
| `VALHALLA_SERVER_THREADS` / `VALHALLA_MEM_LIMIT` | 2 / 1g | the service |

The build disables elevation and transit and builds admins and time zones. Config limits
(routing.md §13.3): trace `max_shape` 16,000, `max_distance` 200 km, GPS accuracy and search
radius ≤ 100 m; the tile cache is capped at 256 MB per thread; Meili's grid cache keeps its
default size. Every download (the extract, its checksum, the time-zone shapefile that
`valhalla_build_timezones` fetches from GitHub) uses the generic User-Agent in `valhalla/curlrc`.
OSMSpeeds' default speeds are not applied (they come from an unpinned URL); add them deliberately
if duration estimates need it.

## Update the extract

Geofabrik refreshes extracts daily. `./dev valhalla build` downloads only when the file is newer
(`curl -z`), builds, switches and restarts. Then run `./dev valhalla smoke`. Saved routes are
never recomputed (routing.md §13.2), so new tiles affect only new routing and matching.

## Roll back

```
cd valhalla/data && ls builds/ && ln -sfn builds/<previous> current.new && mv -Tf current.new current
./dev valhalla up
```

## Swap in North America later (ask Adam first)

The full North America build is on the stop-and-ask list (CLAUDE.md; Q-4, T44): it needs
≈ 16–28 GB RAM and 120–150 GB of free SSD, which this host doesn't have. When approved, on the
Ryzen host or a rented VM:

1. `VALHALLA_PBF_URL=https://download.geofabrik.de/north-america-latest.osm.pbf
   VALHALLA_BUILD_THREADS=4 VALHALLA_BUILD_MEM_LIMIT=26g ./dev valhalla build`
   (or build elsewhere and copy the finished `builds/<timestamp>/` directory over; its config
   uses `/data/builds/<timestamp>/...` paths, so keep the name and point `current` at it).
2. Add `backend/travel/routing/coverage/north-america.geojson` and set
   `VALHALLA_COVERAGE=north-america` in `.env`; restart web and worker.
3. Raise `VALHALLA_MEM_LIMIT` if the service needs more than 1 GB (tiles are memory-mapped, so
   most of it is page cache), then `./dev valhalla up` and `./dev valhalla smoke`, and compare
   about 20 known routes with the previous build (routing.md §13.5).
4. Delete the old Kansas build and the North America PBF once it's verified.
