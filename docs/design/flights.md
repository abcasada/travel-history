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

`resolve_airport(code, flight_date)` (`travel/flights/resolve.py`): (1) manual override in
`airport_code_history`, then the bundled overrides (`geo/data/airport_code_overrides.csv`, source
`bundled`);
(2) an active airport with that IATA/ICAO code whose known service period covers the date;
(3) a closed airport whose `keywords` list the code and whose closure is after the date (closure
dates entered manually where known); (4) otherwise flagged for the user. Same idea for airlines:
ICAO first, then IATA among airlines plausible at that date, else flagged.

Details settled in D-88: an override for a code excludes that airport (or airline) at dates
outside its period, so `BER` in 2015 doesn't resolve to the 2020 airport. A closed airport with a
known closure on or after the date beats an active one only through an override; otherwise both
fitting is ambiguous. A closed airport with an unknown closure resolves only when nothing else
fits, with a warning. Partial dates must fit wholly inside one period. Text without a code may
match one scheduled-service airport by city or name (warning). Airline candidates prefer full
ICAO+IATA codes, active airlines for flights after the OpenFlights snapshot (2017-02-02), and the
flight-number prefix; reused IATA codes have dated rows in `airline_code_history` (bundled
`geo/data/airline_code_overrides.csv`). Aircraft: ICAO type, IATA type, then name; never blocks.

### 12.3 Template and conversion

- **Import template** (`docs/flights/template.csv`, guide in `docs/flights/README.md`): `trip_key` (optional), `date` (YYYY-MM-DD,
  or YYYY-MM / YYYY for partial dates), `dep_time`, `arr_time` (local, optional), `arr_date`
  (optional), `from`, `to` (IATA or ICAO), `airline` (name or code), `flight_number`,
  `aircraft` (type code or name), `registration`, `seat`, `cabin_class`, `seat_type`, `purpose`,
  `notes`, `participants` (`;`-separated names).
- **Conversion script** `./dev manage flights_convert data/private/<file>` reads Adam's
  spreadsheet (CSV/XLSX), maps its columns to the template (mapping saved in a small YAML next to
  it in `data/private/`), and writes a converted CSV plus a report of rows it could not match
  (unknown airport, ambiguous code, unknown airline, bad date). Until the real file exists, it
  is tested against the synthetic `backend/tests/fixtures/flights/flights_synthetic.csv` (with
  small reference-data subsets next to it). `./dev` mounts `data/private` (and
  `data/fixtures`, read-only) into the tools container at `/data`.
- **Import (D-88):** `./dev manage flights_import <email> <template.csv>` (or an upload with kind
  `flights_template`) archives the file as the user's raw file and runs the `flights_template`
  importer: one `flight_record` per row, the user's raw history under own-only RLS, with what
  each code resolved to and the problems/warnings. Re-imports match rows by a key over date,
  airports, airline, flight number and departure time plus the occurrence number, skip identical
  rows, update changed ones and never delete absent ones. Milestone 3.3 groups the records into
  trips and legs.
- **Status (2026-11-18):** 3.1 and 3.2 built on synthetic data (work-order item 10). Loaded:
  OurAirports `airports.csv` at commit 845fd12 (2026-11-17, 86,371 rows), OpenFlights
  `airlines.dat` at 5d623a6 (2017-02-02, 6,161 rows) and `planes.dat` at 4847887 (2019-05-07, 246
  rows), each checked against a pinned SHA-256; `--latest` follows the default branch. Bundled
  overrides: DEN, HKG, MUC, TXL, BER, FBU (airports), PA, TW (airlines).
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
