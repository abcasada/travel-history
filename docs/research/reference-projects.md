# Research: reference projects — licenses, maintenance, ideas (checked 2026-10-19)

GitHub REST API (`/repos`, `/releases`, `/contributors?anon=1`, `/commits?since=2025-10-19`,
`/commits?path=LICENSE`). Default branch only. Shallow clones read, nothing executed.

| Project | Repo | License | Latest release | Last commit | 12-mo commits | Contributors (all / 12-mo) | Top-author share | Stars | Conf |
|---|---|---|---|---|---|---|---|---|---|
| gpx.studio | gpxstudio/gpx.studio | MIT | none (continuous deploy) | 2026-07-24 (branches to 2026-10-18) | 663 | 11 / 4 | vcoppe 99.4% | 1,244 | H |
| AirTrail | johanohly/AirTrail | GPL-3.0 | v3.13.0 2026-09-26 | 2026-09-26 | 269 | 44 / 33 | johanohly 60.2% | 1,649 | H |
| TREK | liketrek/TREK (was mauriceboe/TREK) | AGPL-3.0 (+ trademark policy) | v4.3.3 2026-09-26 | 2026-09-26 | 2,796 | 86 / 86 | mauriceboe 58.4% | 14,841 | H |
| Reitti | dedicatedcode/reitti | AGPL-3.0 since v5.0.0 (2026-07-05); MIT before | v5.7.0 2026-10-14 | 2026-10-19 | 515 | 23 / 17 | dgraf-gh 59.6% | 2,672 | H |
| Dawarich | Freika/dawarich | AGPL-3.0 | 1.16.0 2026-10-17 | 2026-10-17 | 3,213 | 81 / 44 | Freika 93.6% | 10,697 | H |
| GeoPulse | tess1o/geopulse | custom BSL 1.1 since v1.4.2 (2025-11-17); AGPL before | v2.0.0 2026-10-17 | 2026-10-19 | 846 | 15 / 15 | tess1o 97.9% | 1,445 | H |
| maplibre-gl-directions | maplibre/maplibre-gl-directions | MIT | v0.10.1 2026-09-22 | 2026-09-22 | 29 (15 bots) | 10 / 4 | smellyshovel 44.8% (13/14 human) | 173 | H |
| AdventureLog | seanmorley15/AdventureLog | GPL-3.0 | v0.13.0 2026-08-12 | 2026-08-12 | 183 | 54 / 22 | seanmorley15 56.3% | 3,824 | H |

License history: gpx.studio MIT since 2024-06-28; AirTrail GPL-3.0 since 2024-09-05; TREK MIT for
one day then AGPL-3.0 (2026-03-19); Reitti MIT until v4.0.5, AGPL-3.0 from v5.0.0 (release notes:
github.com/dedicatedcode/reitti/releases/tag/v5.0.0); Dawarich AGPL-3.0 since 2024-04-07;
GeoPulse AGPL-3.0 → custom BSL (Change Date 2075-01-01, Change License AGPL-3.0-only, personal
non-commercial grant only); maplibre-gl-directions MIT since 2022.

## gpx.studio drag-to-reshape (MIT — portable with attribution)
Files (commit 6a0d434, `website/src/lib/`): `components/toolbar/tools/routing/routing-controls.ts`
(1,137 lines, RoutingControls), `routing.ts` (305, back-end clients), `simplify.ts` (51, anchors +
zoom levels), repo-root `gpx/src/simplify.ts` (162, RDP with metric cross-track distance),
`utils.ts` (`getClosestLinePoint`).
- Anchors computed on load: RDP ε = 1 m; each kept point gets
  `zoom = clamp(0..22, round(log2(R·cos(lat)/d)))` (R = 6,371,008.8 m, d = RDP deviation);
  endpoints zoom 0. One symbol layer per zoom (minzoom = z).
- Neighbours = anchors visible at the current zoom; dragging zoomed-out reroutes the longer span.
- Hovering the line shows a temporary anchor (hidden > 20 px from line or < 10 px from an anchor);
  drag disables dragPan, moves the marker via `updateData`; on mouseup snaps to nearest
  trackpoint and makes **one** routing request (prev anchor, new point, next anchor) replacing
  points between prev and next; waypoints become zoom-0 anchors; failure reverts.
- Click on line inserts an anchor without rerouting; click on map appends (route from last
  anchor); delete anchor reroutes prev→next; undo via action manager.
- Back ends: gpx.studio's own GraphHopper (no car profile) and brouter.de — not usable by third
  parties (no published terms) — M.
- Portability to React + MapLibre: high (plain GeoJSON sources, symbol layers, updateData,
  queryRenderedFeatures; Svelte stores are the only framework coupling).

## AirTrail import formats (described from code, nothing copied; reimplement from these specs)
Header normalisation: lowercase, non-alphanumeric runs → `_`, trim `_`. Local times → UTC via
airport tz; if arrival < departure add days.
- **MyFlightRadar24 CSV:** date (YYYY | YYYY-MM | YYYY-MM-DD), flight_number, from, to,
  dep_time, arr_time (HH:MM:SS local; 00:00:00 = unknown → arrival from duration), duration,
  airline "Name (IATA/ICAO)", aircraft "Name (ICAO)", registration, seat_number, seat_type
  (1 window, 2 middle, 3 aisle), flight_class (1 economy, 2 business, 3 first, 4 economy+,
  5 private), flight_reason (1 leisure, 2 business, 3 crew, 4 other), note. Airports
  "Name (IATA/ICAO)". Vendor: support.fr24.com article 3000115530 (M).
- **Flighty CSV:** From, To (IATA); Gate Departure/Arrival (Actual/Scheduled), Take off/Landing
  (Scheduled/Actual) as local `YYYY-MM-DDTHH:MM`; terminals, gates, PNR, Canceled, Diverted To,
  Airline (ICAO then IATA), Flight (number), Seat Type, Seat, Cabin Class, Flight Reason, Tail
  Number, Aircraft Type Name, Notes. No public schema (M).
- **App in the Air TXT:** trip blocks starting `Ownership.<…>;`, flights between `flights:` and
  `hotels:`; `;`-separated: cabin class, seat (`None`), …, airline IATA, flight number, …, origin
  IATA, destination IATA, four `YYYY-MM-DDTHH:MM[:SS]` datetimes (first two = dep/arr UTC).
  Service shut down Sep 2024 (M/L).
- **TripIt ICS:** RFC 5545; all-day events skipped; flights = VEVENT with SUMMARY
  "<airline><number> <IATA> to <IATA>", DTSTART/DTEND UTC or TZID (M).
- **JetLog CSV:** date, origin, destination (ICAO), departure_time, arrival_time (HH:MM local),
  arrival_date?, seat (window/middle/aisle), ticket_class (economy/economy+/business/first/
  private), purpose, duration, distance, airplane, airline (ICAO), tail_number, flight_number,
  notes. JetLog is GPL-2.0.
- **byAir CSV:** flight_date, flight_code (`SL*1508` codeshare `*`), departure/arrival_airport_code
  (IATA), departure/arrival_time (HH:MM local), booking_code, seat_number, seat_type, seat_class
  (economy, economy_plus, premium_economy, business, first_class, private, cockpit, jumpseat),
  purpose, notes, ownership, byair_flight_id, byair_codeshare_id.
- Also: JetLovers CSV, OpenFlights CSV, Miles & More JSON (private API), AirTrail JSON.

## Ideas only (AGPL/BSL — never copy code)
- **TREK Atlas:** countries from trips (started trips count; planned shown dashed), manual
  marking, bucket list hatch, admin-1 regions from zoom 5, stats (countries, continents, days,
  streaks), Dawarich-suggested countries confirmed by user; geoBoundaries (CC BY 4.0).
  Journal: photo-first per-day entries, mood/weather/pros-cons, carousel over map, public share
  toggles that strip photo coordinates when the map is off.
- **Reitti modes:** 60-s windows, mean speed per window, ordered per-user (mode, max km/h)
  thresholds (walk < 7, cycle < 20, drive < 120, transit), sparse windows pooled, merge equal
  neighbours, absorb implausible short runs iteratively, user overrides as timestamped modes.
  Ingests OwnTracks, GPSLogger, Overland, Home Assistant, REST, GPX/FIT/GeoJSON, Takeout,
  Timeline (Android and iOS importers).
- **Dawarich Timeline notes:** Android on-device export = object with `semanticSegments`,
  `rawSignals`, `userLocationProfile`, coordinates `"lat°, lng°"`; **iOS export = top-level
  array** of visit/activity/timelinePath objects with `"geo:lat,lng"` and path points carrying
  `durationMinutesOffsetFromStartTime`; detection by key sniffing; streaming in batches; tied
  timestamps nudged. Visits: dwell sweep (100 m, drift cap 1.5×), bridge silences < 1 h if same
  place resumes, movement vetoes, merge fragments within 15 min, min 5 min/3 points, user edits as
  overlays surviving re-runs.
- **GeoPulse classification:** rule cascade on avg/peak speed/variance/water overlap: flight
  avg ≥ 400 or peak ≥ 500 km/h; boat by water overlap; train avg 30–150, peak 40–200, low
  variance; bicycle; running; car avg ≥ 10 or peak ≥ 15; walk avg ≤ 6, peak ≤ 8; reject > 1,200
  km/h; gap-inferred trips (> 1,000 km at > 350 km/h = flight).

## maplibre-gl-directions (MIT)
OSRM/Mapbox-compatible APIs (subclass `buildRequest`/`fetch`), drag line to add waypoints, drag
waypoints, alternatives; one maintainer, ~1.7k weekly downloads; each release supports exactly one
MapLibre major (0.10.x → maplibre-gl ^6); no React wrapper (works via `getMap()`); no zoom-based
anchor simplification, no editing of recorded tracks.

## License implications (not legal advice)
- GPL-3.0: private use carries no obligations; distributing an APK = distributing object code →
  complete corresponding source + whole work under GPL (§5c, §6) (gnu.org/licenses/gpl-3.0.html).
- AGPL-3.0 §13: network users of a modified version must be offered source
  (gnu.org/licenses/agpl-3.0.html#section13).
- BSL 1.1 (GeoPulse variant): personal non-commercial only until 2075 (mariadb.com/bsl11).
- MIT: keep copyright + permission notice in copies/substantial portions (opensource.org/license/mit).
- Reimplementing formats/ideas does not import a license (17 U.S.C. §102(b)); data licenses still
  apply (e.g. geoBoundaries CC BY).
