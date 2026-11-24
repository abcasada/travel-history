# NEXT-14a-1

Handoff for item 14a-1 (lane 1, branch `item/14a-1`). Fold into NEXT.md at merge (after 40e).

- **Done (2026-11-24):** `travel/geo/boundaries.py` + `./dev manage load_boundaries` (Natural
  Earth 1:10m admin-0/1 v5.1.2 at commit f1890d9 + SHA-256; Census 2025 counties by URL +
  SHA-256; upsert by `ne_id`/GEOID; invalid polygons repaired), migration `geo.0005_boundary_keys`
  (adds `ne_id`, `adm0_a3`), `travel/geo/reverse.py` `reverse_geocode(lon, lat)` with labels
  "near <town>, <state>, <country>". `./dev load-reference` now also runs `load_boundaries`.
  Tests: `backend/tests/test_boundaries.py` (SYNTHETIC boxes in `tests/fixtures/boundaries/`).
  Decision D-107 (42a had not taken it; if 42a lands a D-107 first, renumber this one).
  Docs: statistics.md §15.1, data-model.md §5.8, licenses.md, facts register (two rows),
  resource-budget.md §21.6, phases.md 6.1, PLAN.md decision line.
- **Real loads in the lane:** 258 / 4,596 / 3,235 rows, ~25 s from cache, 94 MB of DB, 66 MB
  of downloads, loader peak 247 MiB. Reverse geocoding median 9 ms.
- **At merge:** the main checkout's `var/bulk/reference` lacks the three boundary files; the
  first `./dev load-reference` (and production's) downloads them (pinned, ~66 MB). Production
  also needs `./dev prod manage load_boundaries` after deploying (or the import-from-dev copy
  after a dev load).
- **For 14a-2:** `ReverseGeocode` gives `country.code` (ISO alpha-2), `region.code` (ISO 3166-2)
  plus `region_geonames_id`, `county.code` (GEOID) and `place.geonameid`; `place` carries the
  town's own admin-1 and country, which can differ from the point's region near a border. The
  label is "" at sea. Central Tokyo gives "near Chūō" (wards are populated places in GeoNames).
