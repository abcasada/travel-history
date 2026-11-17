# Importing your flights

How a hand-kept flight list becomes flights in the app (PLAN.md §12.3, milestone 3.2). Your
file never leaves the server and is never committed: it lives in `data/private/`, which git
ignores.

## 1. Load the reference data (once, and whenever you want newer airports)

```sh
./dev manage load_flight_reference            # pinned versions, checksums verified
./dev manage load_flight_reference --latest   # newest OurAirports/OpenFlights commit instead
```

Airports come from OurAirports, airlines and aircraft types from OpenFlights, both downloaded
from their official GitHub repositories with a generic User-Agent. The versions loaded are
listed in the app under menu → *About and data sources*.

## 2. Put your spreadsheet in `data/private/`

CSV or XLSX (save old `.xls` files as `.xlsx` first). Any column order and names work; title
rows above the header are skipped. For example `data/private/flights.xlsx`.

## 3. Convert it

```sh
./dev manage flights_convert data/private/flights.xlsx
```

This reads the file (it is never changed) and writes three files next to it:

| File | What it is |
|---|---|
| `flights.mapping.yaml` | Which of your columns feeds which template column. Guessed on the first run; **check it**, edit it and run again. `dayfirst: true` reads `03/04/1998` as 3 April. Columns under `append_to_notes` are copied into notes as `Header: value`. `--redetect` guesses again. |
| `flights.template.csv` | Every row in the template format below, normalised. |
| `flights.unmatched.csv` | One line per problem (and per warning) with your original row number, the reason and a detail. |

Fix problems in your spreadsheet (an exact date instead of a year, an ICAO code instead of an
ambiguous IATA code, an airline's code instead of its name) and run the converter again until
the report has only what you accept. Rows with problems are still imported, marked *needs
attention*, so nothing is lost.

## 4. Import it as your data

```sh
./dev manage flights_import you@example.com data/private/flights.template.csv
```

The file is archived read-only as your raw file and imported as your import batch, under
row-level security as your account (only you see the records). Importing the same file again
does nothing; a newer version updates changed rows and adds new ones, and never deletes a
flight that is missing from it. Uploading the template through the app's upload API with kind
`flights_template` does the same.

Grouping flights into trips, arcs on the map and matching with Timeline flights come in
milestones 3.3 and 3.4.

## Template columns

| Column | Format | Required |
|---|---|---|
| `trip_key` | any text; rows sharing it form one trip | no |
| `date` | `YYYY-MM-DD`, or `YYYY-MM` / `YYYY` when that's all you know | yes |
| `dep_time`, `arr_time` | local time `HH:MM` (24 h) at the origin / destination | no |
| `arr_date` | `YYYY-MM-DD` when arrival is on another day | no |
| `from`, `to` | IATA (3 letters) or ICAO (4 letters) code | yes |
| `airline` | IATA or ICAO code, or name | no |
| `flight_number` | `UA1234` or `1234` | no |
| `aircraft` | type code (`B738`, `738`) or name | no |
| `registration`, `seat` | text | no |
| `cabin_class` | `economy`, `premium_economy`, `business`, `first`, `other` | no |
| `seat_type` | `window`, `middle`, `aisle`, `other` | no |
| `purpose`, `notes` | text | no |
| `participants` | names separated by `;` | no |

The converter accepts much messier input: dates like `3/14/1998`, `14 Mar 1998`, Excel dates;
times like `7:05 PM` or `0705`; airports like `Denver (DEN)` or a `Route` column `MCI-DEN`;
`UA 1234` in the flight column (the airline is taken from it); cabins like `Coach`, `J`, `F`.

## How codes are resolved by date

Airport and airline codes are reassigned over the years (Denver's `DEN` moved from Stapleton to
the new airport in 1995; `PA` was Pan Am until 1991). The resolver uses the flight date:

1. an override for the code whose dates cover the flight (manual overrides first, then the
   bundled list in `backend/travel/geo/data/airport_code_overrides.csv` and
   `airline_code_overrides.csv`);
2. an active airport with the code (ICAO, then ident, then GPS code for 4 letters);
3. a closed airport whose OurAirports keywords list the code and which closed after the date.

If more than one airport fits, or a partial date (`1995`) spans a change, the row is marked
ambiguous; give the exact date or the ICAO code. Airlines: date overrides, then ICAO code, then
IATA code (preferring airlines with full codes, and active ones for flights after 2017), then
name; the flight number's prefix breaks ties between airlines found by name. An unknown
aircraft type is only a warning.

To add an override for a code the bundled list doesn't know, add a line to the bundled CSV
(public facts only) and run `./dev manage load_flight_reference --overrides-only`.

## Unmatched reasons

| Reason | Meaning |
|---|---|
| `missing_field` | date, from or to is empty |
| `bad_date` | the date can't be read |
| `unknown_airport` | no airport has this code (or no code in the text) |
| `ambiguous_airport` | the code (or city name) fits more than one airport at that date |
| `airport_closed` | the airport with this code had closed by that date |
| `unknown_airline` | no airline matches |
| `ambiguous_airline` | the code or name fits more than one airline at that date |
