# Research: routing and map stack (checked 2026-10-19/20)

Confidence: H official docs/code/API · M maintainer comment or inference · L estimate/scaling.

## Valhalla
| Fact | Value | Source | Conf |
|---|---|---|---|
| License | MIT | github.com/valhalla/valhalla/blob/master/COPYING | H |
| Latest | 3.9.1 (2026-10-06); 3.9.0 (2026-09-19) | GitHub releases API | H |
| Image | `ghcr.io/valhalla/valhalla-scripted` (docker/Dockerfile-scripted); gis-ops/nilsnolde docker-valhalla archived/deprecated (#5698) | valhalla docker/README.md; issues/5698 | H |
| AVX | No `-march`/`-mavx`/`x86-64-v` flags in repo; Ubuntu 24.04 gcc Release build | docker/Dockerfile, CMakeLists.txt | M-H (untested here) |
| Runtime RAM | "a few 100 MB"; tiles mmapped from tar; `mjolnir.max_cache_size` 1 GB per thread default | issues/4140; valhalla_build_config | M/H |
| Meili RAM | location cache can explode with large match requests → cap in `meili` config | discussions/4947 | M |
| Env vars | tile_urls, use_tiles_ignore_pbf, force_rebuild, build_elevation, build_admins, build_time_zones, build_transit, build_tar, server_threads (also sets mjolnir.concurrency), serve_tiles, tileset_name, update_existing_config, use_default_speeds_config | docker/README.md, configure_valhalla.sh | H |
| Geofabrik sizes | north-america 19.51 GB (2026-10-18); US 11.4 GB; Canada 6.1 GB; Mexico 617 MB; **Kansas 117 MB**; planet 95.4 GB | HTTP Content-Length | H |
| Build RAM | planet: 16 CPU/64 GB proven (#6341); "only need 32 GB" (#6201); Europe OOM at 16 GB default threads (#5910); NA on 8 vCPU/64 GiB (#5698); RAM scales with threads (#5910) | GitHub issues | M |
| NA build RAM est. | 32 GB with 4–8 threads comfortable; 16 GB with 2–4 risky; 11 GiB not enough | scaled | L |
| Build scratch | planet .bin ~251 GiB (#6312) → NA ~50 GiB | scaled | L |
| Tiles | planet ~70–140 GB → NA 15–30 GB tar (+ same again during tar step) | #4140, #3953 | L |
| Total disk NA | ~120–150 GB free SSD/NVMe without elevation | scaled; #6341 | L |
| Duration | planet 4–18 h on 16–32 cores; slow random I/O → ~1 week (fixed in 3.9.0, #6312) → NA 1–4 h on modern 8–16-core NVMe; many hours–days on this 4-core HDD host | #5910, #6201, #6312 | L |
| Elevation | world ~1.6 TB; NA ~80–120 GB; only matters for bike/foot costing → skip | docs; #6163 | L/M |
| Map matching | `trace_route`/`trace_attributes`; `shape` [{lat, lon, time?, type?}] or `encoded_polyline` (p6); shape_match edge_walk / map_snap / walk_or_snap (default); defaults max_distance 200 km, max_shape 16,000, max_gps_accuracy 100, max_search_radius 100 (editable) | docs/api/map-matching.md | H |
| OSRM format | `"format":"osrm"` OSRM-compatible JSON; shape_format polyline6/polyline5/geojson/no_shape | route API reference | H |

## OpenRouteService (hosted, HeiGIT)
- Standard (free) quotas: directions 2,000/day, 40/min; matrix 500/40; snap 2,000/100;
  geocode 1,000/100 (Tyk policies in account.heigit.org bundle) — H.
- Per-request: directions ≤ 6,000 km, ≤ 50 waypoints (openrouteservice.org/restrictions) — H.
- ToS (account.heigit.org/info/tos) — H: results CC-BY-SA 4.0; attribution
  "© openrouteservice by HeiGIT | Data from OpenStreetMap" required; no commercial ban found;
  **prohibits transmitting personal data**; repeated over-limit → block; one account per person.
- Encoded polyline precision 5; profiles driving-car etc.; global coverage (M); backend v10.1.0.

## OSRM demo servers
- routing.openstreetmap.de (FOSSGIS): max 1 request/s, valid User-Agent (+ referrer), no heavy
  use/scraping, attribution + "fix the map" link, requests logged; OSRM 5.27.1; car/bike/foot
  worldwide (routing.openstreetmap.de/about.html) — H.
- router.project-osrm.org: ≤ 1 req/s, reasonable non-commercial use, identifying User-Agent,
  ODbL + OSRM attribution (OSRM wiki Demo-server / Api-usage-policy, last edited 2020-12-17) — H.

## Google Maps Platform terms
- ToS (cloud.google.com/maps-platform/terms, modified 2026-08-26): §3.2.3(a) no scraping/storing
  outside the Services; (b) no caching except as permitted; (e) **no use with or near a non-Google
  map** — H.
- Service Specific Terms (…/maps-service-terms, modified 2026-10-15): §A.3 place IDs may be cached
  indefinitely; Directions §4.2 must not be used with a non-Google map, §4.3 lat/lng cache ≤ 30
  days; Routes §19.1–19.3 same; Roads §17.2–17.3 same; Geocoding §6.2/6.3 — H.

## OpenFreeMap / PMTiles
- OpenFreeMap (openfreemap.org, /tos 2026-10-14): free, no key, no view/request limits,
  commercial OK; attribution OpenFreeMap (optional) © OpenMapTiles © OpenStreetMap; bulk/offline
  download ≤ 3,000 tiles or 50 MB; as-is, may be discontinued. Styles liberty/bright/positron
  (+ dark, fiord). Self-hosting ~200 GB disk. Weekly planet PMTiles 87.1 GB supports range
  requests → `pmtiles extract` a region — H/M.
- go-pmtiles v1.31.2 (2026-07-22, BSD-3); `pmtiles extract IN OUT --bbox=... | --region=...
  --maxzoom`; Protomaps tiles ODbL, code BSD-3, styles CC0 — H.

## Martin
- v1.16.1 (2026-09-09) stable; v2.0.0-beta.3; Apache-2.0/MIT. Function sources get z/x/y +
  client-controlled query JSON. "Martin does not authenticate requests" → needs an auth proxy — H.
- Recommendation: MVT in Django with ST_AsMVT for per-user private data — M.

## MapLibre / react-map-gl
- maplibre-gl v6.15.0 (2026-10-18), v6.0.0 2026-07-22, BSD-3 — H.
- react-map-gl v8.1.3 (2026-09-02), `react-map-gl/maplibre`; MapLibre v6 support since 8.1.2, MIT — H.

## Antimeridian
- MapLibre draws across 180° when longitudes are unwrapped past ±180 (official example) — H.
- Turf greatCircle 7.4.0 splits into MultiLineString across the antimeridian; `npoints` 100 — H.

## PostGIS image
- `postgis/postgis:18-3.6` (PG 18, PostGIS 3.6.4, trixie) = latest; also 17-3.6, 17-3.5; amd64
  only; rebuilt weekly; entrypoint starts as root and drops to `postgres` (uid 999) — H.
- PG18: PGDATA `/var/lib/postgresql/18/docker`, VOLUME `/var/lib/postgresql` — H.

Incident note: during research one test GET to router.project-osrm.org carried the user's email
address in its User-Agent. The app's User-Agent must never contain personal data.
