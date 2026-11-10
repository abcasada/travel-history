# Flights

Moved from PLAN.md §12 on 2026-11-10. Section numbers (§N.M) are kept so references
like "PLAN.md §N" still resolve; the section map in PLAN.md says which file holds each §.

## 12. Flights

### 12.1 Reference data

- **Airports:** OurAirports `airports.csv` (public domain, updated daily; 86k rows including
  13.6k `closed`). Closed airports have an **empty** `iata_code`; former codes survive only in
  `keywords` (e.g. Denver Stapleton "DEN", Berlin Tegel "TXL", Kai Tak "HKG"). The loader parses
  3-letter tokens from `keywords` into `airport_code_history` candidates.
- **Airlines / aircraft:** OpenFlights `airlines.dat` (6.2k rows; 4.9k inactive) and `planes.dat`
  (246 types), ODbL — attribution "Airline and aircraft data: OpenFlights.org (ODbL)" on the
  About page. The data is stale (last updated 2017/2019) and IATA airline codes are reused
  (PA, TW…), so matching uses the flight date and prefers ICAO codes; unmatched airlines become
  user-confirmed manual entries.

### 12.2 Code resolution by date

`resolve_airport(code, flight_date)`: (1) manual override in `airport_code_history`;
(2) an active airport with that IATA/ICAO code whose known service period covers the date;
(3) a closed airport whose `keywords` list the code and whose closure is after the date (closure
dates entered manually where known); (4) otherwise flagged for the user. Same idea for airlines:
ICAO first, then IATA among airlines plausible at that date, else flagged.

### 12.3 Template and conversion

- **Import template** (`docs/flights/template.csv`): `trip_key` (optional), `date` (YYYY-MM-DD,
  or YYYY-MM / YYYY for partial dates), `dep_time`, `arr_time` (local, optional), `arr_date`
  (optional), `from`, `to` (IATA or ICAO), `airline` (name or code), `flight_number`,
  `aircraft` (type code or name), `registration`, `seat`, `cabin_class`, `seat_type`, `purpose`,
  `notes`, `participants` (`;`-separated names).
- **Conversion script** `./dev manage flights_convert data/private/<file>` reads Adam's
  spreadsheet (CSV/XLSX), maps its columns to the template (mapping saved in a small YAML next to
  it in `data/private/`), and writes a converted CSV plus a report of rows it could not match
  (unknown airport, ambiguous code, unknown airline, bad date). Until the real file exists, it
  runs against `data/fixtures/flights_synthetic.csv`.
- **Other formats** (phase 3.5 or 10): MyFlightRadar24, Flighty, App in the Air, TripIt (ICS),
  JetLog, byAir — reimplemented from the specs in `docs/research/reference-projects.md`.

### 12.4 Geometry, grouping, dedupe

- Route kind `great_circle`: 128 points along the geodesic (`ST_Segmentize` on geography),
  **split at ±180°** into a MultiLineString for storage and stats; for display, the frontend
  unwraps longitudes past ±180 so MapLibre draws one continuous arc (§26).
- Distance = great-circle distance between the two airports.
- **Grouping:** rows sharing a `trip_key` form one trip. Otherwise auto-group: consecutive flights
  where the next departs from the previous arrival airport within 36 h (connections) form one
  journey; an outbound journey and a later return to the origin within 60 days form one trip
  candidate; all auto-groups go to the review queue.
- **Dedupe vs Timeline:** a Timeline `FLYING` activity overlapping a flight's time window (±2 h)
  with endpoints ≤ 30 km from the airports is linked to that flight leg instead of creating a
  second leg.
