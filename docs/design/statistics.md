# Statistics and reverse geocoding

Moved from PLAN.md §15 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 15. Statistics and reverse geocoding

All computed locally in PostGIS; no external geocoder (no Nominatim/Photon).

### 15.1 Reverse geocoding

- **Admin areas:** point-in-polygon against `country` (Natural Earth admin-0), `region`
  (admin-1) and `us_county` (Census cartographic boundaries), all GiST-indexed. The smallest
  polygon holding the point wins (enclaves); a point just off the 1:10m coastline (a beach, a
  pier) gets the nearest polygon within 2 km.
- **Place names:** among `geonames_place` rows within 25 km (cities500 plus the US populated
  places; not neighbourhoods PPLX or abandoned/historical places), the lowest
  distance / (1 + log10(1 + population)), so a city a few km farther beats the hamlet next door
  but a village beats a city more than about twice as far → "near Salina, Kansas, United
  States". The town's own admin-1 and country name it (from the gazetteer); without a town the
  label is "<region>, <country>" from the boundaries, at sea empty. Lodging and destination
  stops get `name` from the user or the nearest place (item 14a-2).
- **Code:** loaders `travel/geo/boundaries.py` (`./dev manage load_boundaries`, also in
  `./dev load-reference`; pins and keys in D-112); service
  `travel.geo.reverse.reverse_geocode(lon, lat)` → country (ISO alpha-2), region (ISO 3166-2
  and its GeoNames id), county (GEOID), nearby place with distance, label. Runs as the app role
  (the `geo_` tables are read-only to it). Measured sizes and timings: resource-budget.md §21.6.
- Google place IDs from Timeline visits are stored on `place.google_place_id` (allowed to be kept
  indefinitely under Google's terms, see §26), but names come from local data.

### 15.2 Territories visited

| Count | Rule |
|---|---|
| **Through** (default) | Any saved route geometry of a leg the person was on intersects the polygon (drive/train/bus/boat/walk legs), plus stops inside it. |
| **Stopped in** (stricter) | A stop/visit inside the polygon with dwell ≥ 30 min (configurable), or a leg endpoint inside it. |
| Flights | Only the departure and arrival airports' locations count — never territory flown over. |

Per person, using effective leg participation, so family members' stats come from the same
trips. Results are cached in a `territory_visit` table (person, level, code, first date,
mode through/stopped, trip ids) rebuilt when routes or participation change.

### 15.3 Distances

- Miles by vehicle, by mode and by year from `route.length_m` of the **current** frozen route of
  each leg (`ST_Length(geom::geography)`), great-circle distance for flights.
- Flight stats: airports (count, map), airlines, aircraft types, routes, longest/shortest,
  cabin classes.
