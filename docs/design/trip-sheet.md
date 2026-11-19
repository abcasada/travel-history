# Trip spreadsheet import

New section (2026-11-18), design only: no importer code exists yet. Decision D-95 (pending Adam);
open questions Q-18 to Q-21 in PLAN.md §25. Template: [docs/trips/trip-template.xlsx](../trips/trip-template.xlsx),
rebuilt by `scripts/make_trip_template.py` (SYNTHETIC example).

## 28. Trip spreadsheet import

Adam's request (2026-11-18): enter trips in a spreadsheet as stops and legs, with legs referring
to stops by row number in the same tab; a template with a second row of column headers for the
legs, which the importer looks for, so the number of stop rows above it can vary.

The importer is a client of the trips service layer: everything it writes goes through the same
functions, policy checks and RLS as the API ([api.md](api.md) §17, [permissions.md](permissions.md)
§6.3). It reuses the flight import's normalisers and date-aware code resolvers
([flights.md](flights.md) §12.2–12.3) and the GeoNames gazetteer of work-order item 14
(`GET /reference/places`).

### 28.1 File and tabs

- **`.xlsx` only.** Excel, LibreOffice, Numbers and Google Sheets all save it; `.xls` and `.ods`
  are saved as `.xlsx` first. CSV can't hold several tabs.
- **One trip per tab.** Leg row numbers are local to a tab, so a tab is the natural unit: a trip
  can be copied from the example, viewed whole, and re-imported on its own. The parser reads a tab
  as a sequence of sections (trip block, stops, legs), so allowing several trips per tab later,
  each starting with its own trip block, extends the format without changing it (Q-21).
- **Skipped tabs:** `Instructions` and any tab whose name starts with `_` (the template's
  `_Example`, so a forgotten example never becomes a trip). Hidden tabs are imported: hiding is a
  view setting.
- **Limits:** file ≤ 10 MB; uncompressed zip members ≤ 100 MB in all (checked before parsing);
  ≤ 500 trip tabs; ≤ 2,000 rows and 40 columns read per tab. Read with openpyxl in read-only
  mode; `defusedxml` is added to the requirements so openpyxl parses the XML safely (it uses it
  when installed). Formulas are never evaluated (§28.5 reads two forms from the formula text).

### 28.2 Tab layout

```
row  A           B                         C       D      E                 …
1    Title       Example: Colorado and …                                       ┐ trip block
2    Key         example-southwest-2015                                        │ (optional)
…    Start, End, Purpose, People, Tags, Visibility, Notes                      ┘
11   Stop        Place                     Name    Kind   Arrive    …          ← stops header
12   home        Kansas City, MO, US               waypoint …                    ┐ any number
13               DEN                               waypoint …                    │ of stop rows,
…                                                                              ┘ blank rows ok
22   Leg         From        To            Mode    Depart Arrive   …           ← legs header
23   out         12          13            flight  …                             ┐ to the end
24               13          springs       drive   …                             ┘ of the tab
```

- **Finding the blocks.** Scanning from row 1, the *stops header* is the first row with a cell
  `Place`; the *legs header* is the first later row with cells `From`, `To` and `Mode`. Header
  matching ignores case, surrounding spaces and a trailing `:` or `*`; column order is free.
- **Trip block:** the rows above the stops header, a field label in column A and its value in
  column B. It is optional: with no trip block, row 1 can be the stops header, the title and
  key default to the tab name and the dates come from the stops and legs (Q-18).
- **Stops block:** the rows between the two headers. **Legs block:** the rows after the legs
  header. A row with nothing in a known column is blank and skipped. Either block may be absent
  (a flights-only trip needs no stops, §28.5).
- **Unknown columns** (Adam's own, such as Cost) are ignored, with one info line per tab. A
  non-empty row in the trip block whose label isn't a field is a warning and ignored.

### 28.3 Trip fields

| Field | Format | Blank means | Stored as |
|---|---|---|---|
| Title | text ≤ 200 | the tab name | `trip.title` |
| Key | text ≤ 100 | the tab name | `trip_sheet_link.key` (§28.9): trimmed, case-folded, spaces collapsed; unique within the workbook and per owner |
| Start, End | `YYYY-MM-DD` or a date cell; `YYYY-MM` or `YYYY` (precision month/year: first and last day) | earliest / latest local date of the stops and legs; a problem if nothing gives a date | `start_date`, `end_date`, `date_precision` |
| Purpose | one of the caller's purposes (case-insensitive, archived included) | none | `trip.purpose`; unknown → problem listing the known names |
| People | names separated by `;`; `me` = the caller's own person | nobody | `trip_participant`. Matched by `display_name` (case-insensitive) among the persons the caller can see; unknown or several matches → problem (Q-20); `me` without a linked person → problem ("Add me" first) |
| Tags | names separated by `;` | none | the caller's tags; unknown names are created (the preview lists them) |
| Visibility | `private`, `participants`, `family` | the purpose's default (D-90) | `trip.visibility`; `public` is refused until phase 8 |
| Notes | text | none | `trip.notes` |

Imported trips are `status = confirmed`, `source = sheet_import` (new choice), owned by the
caller, with `edited_in_app_at` left empty.

### 28.4 Stops

| Column | Format | Notes |
|---|---|---|
| Stop | optional label ≤ 40, containing a letter | Lets legs say `springs` instead of a row number; unique per tab (case-insensitive). The letter rule keeps a label from reading as a row number. |
| Place | see below | required on a non-blank stop row |
| Name | text | the place's display name; default the gazetteer or airport name, or the coordinates |
| Kind | `lodging`, `destination`, `visit`, `waypoint` | default `destination` |
| Arrive, Depart | local time (§28.6) | optional |
| Time zone | IANA name | default from the place (§28.6) |
| Notes | text ≤ 20,000 | `stop.notes` (item 14b): private, never in a public snapshot (§6.5) |

**Place**, read in this order:

1. `geonames:<id>`: that gazetteer place.
2. **Coordinates** `lat, lon` in decimal degrees (also separated by a space or `;`), latitude
   first as in the app's place input. Out of range → problem.
3. **Airport code:** exactly 3 (IATA) or 4 (ICAO) capital letters, or `airport:<code>` in any
   case. Resolved with `resolve_airport(code, date)` (D-88) at the stop's arrival date (else
   departure, else trip start), with the flight import's reasons (`ambiguous_airport`,
   `airport_closed`, …).
4. Otherwise a **city**: `Name[, region][, country]`, the region as admin-1 code or name, the
   country as ISO code or name. Matched exactly on the gazetteer's names and alternate names
   (accents and case folded), filtered by the qualifiers. **One match → resolved. Several →
   problem `ambiguous_place`** listing up to five candidates, each with the exact text that
   would pick it (`Paris, Île-de-France, FR` or `geonames:<id>`). None → `unknown_place` with the
   nearest names. Population ranks the picker's suggestions (item 14) but never chooses for the
   importer.

The stop's `place` is the caller's own `Place` with the same GeoNames id, the same airport, or
the same coordinates and name; otherwise a new one (`source = manual`, with `geonames_id`,
`country_code`, `admin1_code` when known). Stops are not tied to a leg (`stop.leg` stays empty).

### 28.5 Legs

| Column | Leg field | Notes |
|---|---|---|
| Leg | (identity only) | optional label, used to recognise the leg on re-import (§28.9) |
| From, To | `origin_stop`, `destination_stop` | a stop reference (below). May be blank on a flight whose airport column is filled: a connection airport needn't be a stop. |
| Mode | `mode` | `drive`, `flight`, `train`, `bus`, `boat`, `walk`, `other`; also car/auto, plane/air/fly, rail, coach, ferry/ship, foot/hike |
| Depart, Arrive | `start_utc`, `end_utc`, `time_precision` | local times (§28.6) |
| Depart zone, Arrive zone | `start_tz`, `end_tz` | default: the origin / destination stop's zone, else the airport's |
| From airport, To airport | `origin_airport`, `destination_airport` | code, resolved by the departure date. Blank and the stop is an airport → that airport. A flight with neither → problem `missing_airport`. On other modes: warning, ignored. |
| Airline, Flight, Aircraft, Registration, Seat, Cabin | the flight fields | the flight template's formats and resolvers; `WN 1234` gives the airline when Airline is blank; an unknown aircraft is a warning. On other modes: warning, ignored. |
| Vehicle | `vehicle` | nickname of a vehicle the caller may use (`can_use_vehicle`); unknown or several → problem |
| People | participant overrides | only when the leg's people differ from the trip's: exactly these people, stored as include/exclude overrides relative to the trip's set |
| Notes | `notes` | text ≤ 20,000 (item 14b): private, never in a public snapshot (§6.5) |

`sequence` is the row order; `author` the caller; `participant_scope = trip`; `origin_label` /
`destination_label` the stop names or airport codes; `import_batch` the batch.

**Stop references.** A From or To cell holds one of:

- a **row number** as shown on the sheet's left edge (`14`; a number cell `14.0` too);
- a stop **label** (`springs`);
- a **formula** `=ROW(B14)`, `=B14` or `=$A$14`: the referenced row is read from the formula
  text. Spreadsheets rewrite such references when rows are inserted, so they follow the stop.

The reference must land on a non-blank row of the same tab's stops block; otherwise a problem
names the row and the block's range ("row 31 is not a stop; stops are rows 12–19").

**Inserting rows.** Typed numbers don't follow inserted rows; that's the format's one trap. Three
defences: labels (recommended for anything that may be re-imported), the `=ROW()` formula, and a
preview that shows every leg as *stop name → stop name* with these warnings: a leg that doesn't
start where the previous one ended; a leg that departs before its origin stop's arrival or
arrives after its destination stop's departure; legs out of time order; a flight between stops
less than 50 km apart.

**Routes.** The import never creates, changes or recomputes a route on an existing leg (rule 5).
A new flight leg gets its great-circle version from the flight grouping's function (§12.4, item
11) once that exists; drive legs are routed later in the app.

### 28.6 Times and zones

- **Cells:** a date-time cell (read as wall-clock time in the row's zone), a date cell, or text
  `YYYY-MM-DD HH:MM[:SS]`, `YYYY-MM-DD`, `YYYY-MM`, `YYYY`, `14 Mar 2015`, and times like
  `7:05 PM` (the flight normaliser). Slash dates are read month first only when unambiguous
  (`3/14/2015`); `3/4/2015` is a problem (`ambiguous_date`). An offset (`2015-11-01 01:30 -05:00`)
  may be appended to settle a repeated hour.
- **Storage:** UTC plus the IANA zone (CLAUDE.md). A date-only value is stored as local midnight
  with precision `day` (month and year likewise). Legs have `time_precision`; stops get a new
  `time_precision` column (same enum, default `exact`) so a date-only stop isn't shown as
  midnight.
- **Zone when blank:** a city stop takes its gazetteer place's own zone (cities500's `timezone`
  column, which item 14's loader must keep); an airport or coordinates take the zone of the
  nearest gazetteer place within 50 km in the same country, shown as info in the preview; nothing
  near → problem `unknown_zone` ("type a Time zone"). A leg's zones default to its stops' or
  airports' zones. Zone boundaries (Arizona and the Navajo Nation, Indiana) can make the nearest
  place wrong; a time-zone boundary dataset could replace the rule later.
- **Never guessed:** a local time that doesn't exist (spring-forward gap) is a problem; one that
  happens twice (fall-back) without an offset is a problem listing both offsets.
- End before start (trip dates, stop arrive/depart, leg depart/arrive in UTC) is a problem.

### 28.7 Validation and the error report

- Each issue: tab, row, column (letter and header), field, severity (`problem`, `warning`,
  `info`), reason code, message, and a fix hint or candidates.
- **Problems block their tab only:** a tab with a problem can't be imported; clean tabs can.
  Workbook-level problems (two tabs with the same key, file too large) block the tabs involved.
- **Reasons:** the flight import's (`missing_field`, `bad_date`, `unknown_airport`,
  `ambiguous_airport`, `airport_closed`, `unknown_airline`, `ambiguous_airline`) plus
  `bad_time`, `ambiguous_date`, `ambiguous_time`, `nonexistent_time`, `unknown_zone`,
  `unknown_place`, `ambiguous_place`, `missing_airport`, `bad_reference` (not a stop row,
  unknown label), `duplicate_label`, `duplicate_key`, `unknown_person`, `ambiguous_person`,
  `unknown_purpose`, `unknown_vehicle`, `ambiguous_vehicle`, `bad_value` (kind, mode, cabin,
  visibility), `end_before_start`, `no_dates`, `too_large`.
- The preview lists issues by tab, sorted by row; a "Download report" button saves them as CSV
  (`tab,row,column,severity,reason,message,hint`) through the files adapter. The CLI writes the
  same CSV next to the input in `data/private/`.

### 28.8 Upload, preview, commit

1. **Upload** through the chunked upload API with kind `trip_sheet` (new `import_batch.kind`). The
   file is archived as the caller's `raw_file` (immutable, 0440, own-only; rules 12 and 1).
   Identical bytes → the existing batch is shown again.
2. **Parse** in the worker: one `trip_sheet_record` per trip tab (raw history, own-only RLS,
   append-only): batch, tab name and position, key, the normalised content (trip fields, stops,
   legs with resolved ids and UTC times), `content_hash`, issues. The batch moves to a new status
   `preview`. Parsing never writes trips.
3. **Preview** (`GET /imports/{id}/trip-sheet`): per tab, its outcome (*new*, *update*,
   *identical*, *review* because edited in the app, *skipped* because deleted in the app,
   *blocked* by problems), its issues, and the diff against the trip: trip fields old → new,
   stops and legs added, changed (field by field) and kept-not-in-sheet. A map layer draws the
   open tab's stops and legs (straight lines, great-circle for flights).
4. **Commit** (`POST /imports/{id}/commit`, `{records: [ids]}`, default every importable tab):
   one transaction per tab, as the caller under RLS, through `travel.trips.services`. A target
   trip changed since the preview (its `updated_at` is newer than the preview's snapshot) →
   409, preview again. The record and the link store the outcome; the batch becomes `done` with
   a summary. **Discard** (`POST /imports/{id}/discard`) ends the batch; the raw file stays.
5. **CLI:** `./dev manage trips_sheet_import <email> <file.xlsx>` prints the preview and writes
   the report; `--commit` applies every importable tab. Like `flights_import`, it runs as
   `travel_app` in the user's context, never as the owner role.

**UI** (frontend-patterns.md): an `imports/` feature folder. An imports page (upload, the
template link, the caller's batches) and a preview page `/imports/:id` with one card per tab
(outcome badge, issue table with row and column, diff) and an "Import N trips" button. Both
shells show the preview; its map layer is registered in `MapLayers` and draws only on that page.
Controls follow API flags (`can_commit`), never role checks. The template is served at
`GET /trips/sheet-template.xlsx` (the committed file).

### 28.9 Re-import

**Identity.**

- **Trip:** `trip_sheet_link` (owner, key unique per owner, `trip` → trip, set null on delete,
  last applied record, `applied_hash`, `applied_at`; own-only RLS). A link table rather than a
  column on `trip`, so a trip deleted in the app is remembered (rule 7). Keys match only the
  caller's own trips.
- **Stop:** its label, else place identity + local arrival (or departure) date + occurrence.
  **Leg:** its label, else mode + origin and destination (stop key or airport) + local departure
  date + occurrence. Stored as `sheet_key` on `stop` and `leg` (new columns, empty for rows made
  in the app); stops also get `import_batch`. Changing an unlabelled stop's place or date changes
  its key, so it shows as one new stop plus one kept-not-in-sheet; the preview puts them side by
  side and suggests a label.

**Outcome per tab.**

| Situation | Result |
|---|---|
| No link for the key | New trip and link. |
| Link; content hash equals `applied_hash` | Identical: nothing written. |
| Link; trip not edited in the app since `applied_at` | Update: matched stops and legs updated field by field, new ones inserted, ones missing from the sheet **kept** and listed. Sheet legs take the sheet's order; kept legs keep their place by time. A blank cell means "not given" and never clears a value. People and tags are only added. |
| Link; trip edited in the app since `applied_at` (`edited_in_app_at`, or a saved route version on one of its legs) | Nothing changes (rule 7): a `review_flag(source_changed)` holds the batch, record and diff; one open flag per trip and content hash. Resolving it later may apply the sheet version explicitly. |
| Link; trip deleted in the app | Skipped; the preview says when. Re-creating it is an explicit per-tab choice in the preview, off by default. |
| Link; the trip now belongs to someone else (transfer) | Skipped with an info line. |

**Absence is never deletion (rule 6).** A tab missing from a later workbook leaves its trip
alone; a missing row leaves its stop or leg alone. The preview lists what the sheet no longer
has. Recommended (Q-19): the preview offers a per-trip, unticked "Also remove these N stops and
legs from the trip", listing them. That is a deletion the user asks for, row by row, not one
inferred from absence. Without it, cleanup happens in the app, which marks the trip edited and
sends later sheet changes to the review queue.

Never touched by a re-import: contributed legs, notes, photos, tracks and other people's tags;
participants and tags already on the trip; route versions.

**Flights in both lists.** Item 11 (flight grouping, T14) must link an imported `flight_record`
to an existing flight leg of the same owner with the same date, airports and flight number
instead of creating a second leg; the sheet preview shows the match as info.

### 28.10 Ownership and permissions

- **Who:** `policy.can_import` (Admin and Member). Viewers get 403; the upload kind is refused
  like other imports.
- **What it creates** is owned or authored by the caller. A key never matches another user's
  trip, so the importer never edits someone else's trip, even where the Admin could in the app.
- **Lookups** run under the caller's RLS: persons the caller can see, own purposes, tags and
  places, vehicles the caller may use.
- **Writes** go through `travel.trips.services` with the API's checks (`can_create`,
  `can_add_participant`, `can_use_place`, `can_tag_trip`, `can_use_vehicle`,
  `can_set_leg_participation`), backed by RLS as `travel_app` with the transaction-local
  `app.user_id`.
- **New tables** `trip_sheet_record` and `trip_sheet_link` are own-only (the raw-history row of
  §6.3). New matrix rows: `import_trip_sheet`, `commit_own_trip_sheet`,
  `commit_other_users_batch` (never), `reimport_other_users_trip` (never), tested at the API
  and as `travel_app` (rule 3).
- **Never public** through an import.

### 28.11 Data model changes (for the importer item)

`import_batch.kind` + `trip_sheet`; `import_batch.status` + `preview`, `discarded`;
`trip.source` + `sheet_import`; `stop.time_precision`, `stop.sheet_key`, `stop.import_batch`;
`leg.sheet_key`; tables `trip_sheet_record`, `trip_sheet_link` (RLS in the same migration).
data-model.md §5.3 and §5.5 get the rows when the item lands.
