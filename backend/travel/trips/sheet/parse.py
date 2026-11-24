"""One trip tab -> normalised content and issues (§28.3-§28.7); the whole workbook (§28.1).

Parsing never writes trips. The content is what the commit applies: trip fields, stops and legs
with resolved ids and UTC times, `None` for every cell left blank (a blank cell means "not
given" and never clears a value on re-import, §28.9), and the defaults a new trip would take.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field

from travel.flights import normalize as n
from travel.flights.resolve import resolve_aircraft, resolve_airline
from travel.geo.gazetteer import fold

from .layout import STOP_COLUMNS, Block, Layout, find_blocks
from .reader import RawTab, SheetFileError, read_tabs
from .resolve import (
    Directory,
    Place,
    airport_place,
    distance_km,
    nearest_zone,
    resolve_code,
    resolve_place,
)
from .values import (
    STOP_KINDS,
    VISIBILITIES,
    CellProblem,
    Issue,
    LocalTime,
    StopRef,
    choice,
    coarsest,
    is_blank,
    local_time,
    mode,
    sheet_key,
    split_list,
    stop_label,
    stop_ref,
    text,
    to_utc,
    zone_name,
)

MAX_NOTES = 20_000
MAX_TITLE = 200
MAX_KEY = 100
FLIGHT_COLUMNS = (
    "from_airport",
    "to_airport",
    "airline",
    "flight",
    "aircraft",
    "registration",
    "seat",
    "cabin",
)
CLOSE_FLIGHT_KM = 50
# Not part of what a tab says: row numbers move when rows are inserted, and which tags or people
# are new depends on the app's data at parse time.
HASH_IGNORES = {"row", "origin_row", "destination_row", "new_tags", "unknown_people"}


@dataclass
class ParsedTab:
    name: str
    position: int
    key: str
    title: str
    content: dict
    issues: list[Issue] = field(default_factory=list)
    key_row: int | None = None

    @property
    def blocked(self) -> bool:
        return any(issue.severity == "problem" for issue in self.issues)

    @property
    def content_hash(self) -> str:
        return content_hash(self.content)


def _strip_rows(value):
    if isinstance(value, dict):
        return {k: _strip_rows(v) for k, v in value.items() if k not in HASH_IGNORES}
    if isinstance(value, list):
        return [_strip_rows(v) for v in value]
    return value


def content_hash(content: dict) -> str:
    canonical = json.dumps(_strip_rows(content), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class _Stop:
    row: int
    label: str
    place: Place | None = None
    name: str | None = None
    kind: str | None = None
    arrive: LocalTime | None = None
    depart: LocalTime | None = None
    tz_given: str | None = None
    tz: str = ""
    arrive_utc: dt.datetime | None = None
    depart_utc: dt.datetime | None = None
    notes: str | None = None
    key: str = ""

    def display(self) -> str:
        if self.name:
            return self.name
        if self.place is None:
            return f"row {self.row}"
        if self.place.name:
            return self.place.name
        return f"{self.place.lat:.4f}, {self.place.lon:.4f}"


@dataclass
class _Leg:
    row: int
    label: str
    origin: _Stop | None = None
    destination: _Stop | None = None
    mode: str | None = None
    depart: LocalTime | None = None
    arrive: LocalTime | None = None
    values: dict = field(default_factory=dict)
    origin_airport: object | None = None
    destination_airport: object | None = None
    start_utc: dt.datetime | None = None
    end_utc: dt.datetime | None = None
    key: str = ""


class TabParser:
    def __init__(self, raw: RawTab, directory: Directory):
        self.raw = raw
        self.dir = directory
        self.issues: list[Issue] = []
        self.layout: Layout = find_blocks(raw)
        self.unknown_people: list[str] = []
        self._zone_cache: dict[tuple, tuple[str, str] | None] = {}

    # --- issues -----------------------------------------------------------------------------

    def add(
        self,
        severity,
        reason,
        message,
        *,
        row=None,
        column="",
        header="",
        field="",
        hint="",
        candidates=None,
        creates="",
    ) -> None:
        issue = Issue(
            self.raw.name,
            row,
            column,
            header,
            field,
            severity,
            reason,
            message,
            hint,
            list(candidates or []),
        )
        if creates:
            issue.candidates = [creates]
            issue.hint = issue.hint or "tick 'create these people' in the preview"
            issue.reason = "unknown_person"
        self.issues.append(issue)

    def cell_issue(
        self,
        block: Block | None,
        row: int,
        name: str,
        problem: CellProblem,
        severity: str = "problem",
    ) -> None:
        column = block.letter(name) if block else ""
        header = block.headers.get(name, name) if block else name
        self.add(
            severity,
            problem.reason,
            problem.message,
            row=row,
            column=column,
            header=header,
            field=name,
            hint=problem.hint,
            candidates=problem.candidates,
        )

    def trip_issue(self, name: str, problem: CellProblem, severity: str = "problem") -> None:
        found = self.layout.trip.get(name)
        self.add(
            severity,
            problem.reason,
            problem.message,
            row=found.row if found else None,
            column="B" if found else "",
            header=name.capitalize(),
            field=name,
            hint=problem.hint,
            candidates=problem.candidates,
        )

    # --- trip block ---------------------------------------------------------------------------

    def trip_value(self, name: str):
        found = self.layout.trip.get(name)
        return found.cell if found else None

    def trip_text(self, name: str) -> str:
        cell = self.trip_value(name)
        return text(cell.value) if cell else ""

    def trip_date(self, name: str) -> LocalTime | None:
        cell = self.trip_value(name)
        if cell is None:
            return None
        try:
            value = local_time(cell.value, cell.number_format)
        except CellProblem as problem:
            self.trip_issue(name, problem)
            return None
        if value is not None and value.precision == "exact":
            value = LocalTime(dt.datetime.combine(value.date, dt.time()), "day")
        return value

    def limited(self, value: str, limit: int, field_name: str, issue) -> str:
        if len(value) > limit:
            issue(CellProblem("bad_value", f"{field_name} is longer than {limit} characters"))
            return value[:limit]
        return value

    def parse(self) -> ParsedTab:
        tab = self.raw.name
        if self.raw.truncated:
            self.add(
                "problem",
                "too_large",
                "the tab has data beyond 2,000 rows or 40 columns; split it into several tabs",
            )
        for row, label in self.layout.trip_unknown:
            message = (
                f"{label!r} isn't a trip field; the row is ignored"
                if label
                else "values without a field label in column A are ignored"
            )
            self.add("warning", "bad_value", message, row=row, column="A", header=label)
        for row, label in self.layout.trip_duplicates:
            self.add(
                "warning",
                "bad_value",
                f"{label} is given twice; the first one counts",
                row=row,
                column="A",
                header=label,
            )
        ignored = [
            name
            for block in (self.layout.stops, self.layout.legs)
            if block
            for name in block.unknown
        ]
        if ignored:
            self.add("info", "ignored_columns", "columns ignored: " + ", ".join(ignored))

        title = self.limited(
            self.trip_text("title"), MAX_TITLE, "Title", lambda p: self.trip_issue("title", p)
        )
        key_text = self.trip_text("key") or tab
        key_text = self.limited(key_text, MAX_KEY, "Key", lambda p: self.trip_issue("key", p))
        key = sheet_key(key_text)

        stops = self.parse_stops()
        legs = self.parse_legs(stops)
        start, end, precision = self.trip_dates(stops, legs)
        self.resolve_stops(stops, start)
        self.resolve_legs(legs, start)
        self.check_chain(legs)
        self.assign_keys(stops, legs)

        trip = self.trip_fields(title, start, end, precision)
        content = {
            "trip": trip,
            "stops": [self.stop_content(stop) for stop in stops],
            "legs": [self.leg_content(leg) for leg in legs],
            "unknown_people": self.unknown_people,
        }
        key_field = self.layout.trip.get("key")
        return ParsedTab(
            tab,
            self.raw.position,
            key,
            title or tab,
            content,
            self.issues,
            key_row=key_field.row if key_field else None,
        )

    def trip_fields(self, title, start, end, precision) -> dict:
        purpose = None
        if name := self.trip_text("purpose"):
            try:
                purpose = self.dir.purpose(name)
            except CellProblem as problem:
                self.trip_issue("purpose", problem)
        people = self.people(
            self.trip_value("people"), lambda p, creates="": self.trip_people_issue(p, creates)
        )
        tags = split_list(self.trip_value("tags").value) if self.trip_value("tags") else []
        new_tags = [t for t in tags if t.casefold() not in self.dir.tags]
        if new_tags:
            self.trip_issue(
                "tags",
                CellProblem("new_tags", "new tags will be created: " + ", ".join(new_tags)),
                severity="info",
            )
        visibility = None
        cell = self.trip_value("visibility")
        if cell is not None and not is_blank(cell.value):
            if text(cell.value).lower() == "public":
                self.trip_issue(
                    "visibility",
                    CellProblem(
                        "bad_value",
                        "public trips can't be imported yet (public pages come in phase 8)",
                        hint="private, participants or family",
                    ),
                )
            else:
                try:
                    visibility = choice(cell.value, VISIBILITIES, "visibility")
                except CellProblem as problem:
                    self.trip_issue("visibility", problem)
        notes = self.trip_text("notes") or None
        if notes and len(notes) > MAX_NOTES:
            self.trip_issue(
                "notes", CellProblem("bad_value", "Notes are longer than 20,000 characters")
            )
        return {
            "title": title or None,
            "default_title": self.raw.name[:MAX_TITLE],
            "start_date": start.isoformat() if start else None,
            "end_date": end.isoformat() if end else None,
            "date_precision": precision,
            "dates_given": self.trip_value("start") is not None
            and not is_blank(self.trip_value("start").value),
            "purpose_id": purpose.pk if purpose else None,
            "purpose": purpose.name if purpose else None,
            "people": people,
            "tags": tags,
            "new_tags": new_tags,
            "visibility": visibility,
            "notes": notes,
        }

    def trip_people_issue(self, problem: CellProblem, creates: str = "") -> None:
        found = self.layout.trip.get("people")
        self.add(
            "problem",
            problem.reason,
            problem.message,
            row=found.row if found else None,
            column="B",
            header="People",
            field="people",
            hint=problem.hint,
            creates=creates,
        )

    def people(self, cell, report) -> list[dict] | None:
        """[{name, person_id}] (person_id None for a name the preview may create); None for a
        blank cell."""
        if cell is None or is_blank(cell.value):
            return None
        result = []
        for name in split_list(cell.value):
            try:
                person = self.dir.person(name)
            except CellProblem as problem:
                creatable = problem.reason == "unknown_person" and name.casefold() != "me"
                if creatable and name not in self.unknown_people:
                    self.unknown_people.append(name[:150])
                report(problem, creates=name[:150] if creatable else "")
                result.append({"name": name[:150], "person_id": None})
                continue
            result.append({"name": person.display_name, "person_id": person.pk})
        return result

    # --- stops ------------------------------------------------------------------------------

    def parse_stops(self) -> list[_Stop]:
        block = self.layout.stops
        if block is None:
            return []
        stops: list[_Stop] = []
        labels: dict[str, int] = {}
        for row, cells in block.rows:
            get = _getter(cells)
            stop = _Stop(row=row, label="")
            try:
                stop.label = stop_label(get("label"))
            except CellProblem as problem:
                self.cell_issue(block, row, "label", problem)
            if stop.label:
                folded = fold(stop.label)
                if folded in labels:
                    self.cell_issue(
                        block,
                        row,
                        "label",
                        CellProblem(
                            "duplicate_label",
                            f"label {stop.label!r} is also used on row {labels[folded]}",
                        ),
                    )
                else:
                    labels[folded] = row
            stop.name = text(get("name"))[:200] or None
            try:
                stop.kind = choice(get("kind"), STOP_KINDS, "kind")
            except CellProblem as problem:
                self.cell_issue(block, row, "kind", problem)
            for name in ("arrive", "depart"):
                cell = cells.get(name)
                try:
                    value = local_time(cell.value, cell.number_format) if cell else None
                except CellProblem as problem:
                    self.cell_issue(block, row, name, problem)
                    value = None
                setattr(stop, name, value)
            try:
                stop.tz_given = zone_name(get("tz"))
            except CellProblem as problem:
                self.cell_issue(block, row, "tz", problem)
            notes = text(cells["notes"].value) if "notes" in cells else ""
            if len(notes) > MAX_NOTES:
                self.cell_issue(
                    block,
                    row,
                    "notes",
                    CellProblem("bad_value", "Notes are longer than 20,000 characters"),
                )
            # Notes keep their line breaks: n.text would collapse them.
            raw_notes = cells["notes"].value if "notes" in cells else None
            stop.notes = str(raw_notes).strip()[:MAX_NOTES] if not is_blank(raw_notes) else None
            if "place" not in block.columns or is_blank(get("place")):
                self.cell_issue(
                    block, row, "place", CellProblem("missing_field", "a stop needs a Place")
                )
            stops.append(stop)
        return stops

    def resolve_stops(self, stops: list[_Stop], start: dt.date | None) -> None:
        block = self.layout.stops
        for stop in stops:
            cells = dict(block.rows)[stop.row]
            place_cell = cells.get("place")
            if place_cell is None or is_blank(place_cell.value):
                continue
            when_local = stop.arrive or stop.depart
            when = (
                n.FlightDate(when_local.date, "day")
                if when_local
                else (n.FlightDate(start, "day") if start else None)
            )
            try:
                stop.place, warnings = resolve_place(place_cell.value, when)
            except CellProblem as problem:
                self.cell_issue(block, stop.row, "place", problem)
                continue
            for warning in warnings:
                self.cell_issue(
                    block, stop.row, "place", CellProblem("check", warning), severity="warning"
                )
            stop.tz = self.stop_zone(stop)
            self.stop_times(stop)

    def zone_for(self, place: Place) -> tuple[str, str] | None:
        """(zone, where it came from) for a place without a zone of its own."""
        if place.tz:
            return place.tz, ""
        key = (place.lat, place.lon, place.country_code)
        if key not in self._zone_cache:
            self._zone_cache[key] = nearest_zone(place.lat, place.lon, place.country_code)
        return self._zone_cache[key]

    def stop_zone(self, stop: _Stop) -> str:
        block = self.layout.stops
        if stop.tz_given:
            return stop.tz_given
        found = self.zone_for(stop.place)
        if found is not None:
            zone, near = found
            if near:
                self.cell_issue(
                    block,
                    stop.row,
                    "tz",
                    CellProblem("zone_from_nearest", f"time zone {zone}, from nearby {near}"),
                    severity="info",
                )
            return zone
        if stop.arrive or stop.depart:
            self.cell_issue(
                block,
                stop.row,
                "tz",
                CellProblem(
                    "unknown_zone",
                    "no time zone known for this place",
                    hint="type a Time zone, such as America/Denver",
                ),
            )
        return ""

    def stop_times(self, stop: _Stop) -> None:
        block = self.layout.stops
        if not stop.tz:
            return
        for name in ("arrive", "depart"):
            local = getattr(stop, name)
            if local is None:
                continue
            try:
                setattr(stop, f"{name}_utc", to_utc(local, stop.tz))
            except CellProblem as problem:
                self.cell_issue(block, stop.row, name, problem)
        if stop.arrive_utc and stop.depart_utc and stop.depart_utc < stop.arrive_utc:
            self.cell_issue(
                block,
                stop.row,
                "depart",
                CellProblem("end_before_start", "Depart is before Arrive"),
            )

    def stop_content(self, stop: _Stop) -> dict:
        return {
            "row": stop.row,
            "label": stop.label,
            "sheet_key": stop.key,
            "place": stop.place.as_dict() if stop.place else None,
            "name": stop.name,
            "display_name": stop.display(),
            "kind": stop.kind,
            "arrive_utc": _iso(stop.arrive_utc),
            "depart_utc": _iso(stop.depart_utc),
            "times_given": bool(stop.arrive or stop.depart),
            "tz": stop.tz,
            "tz_given": stop.tz_given,
            "time_precision": coarsest(
                [t.precision for t in (stop.arrive, stop.depart) if t is not None]
            ),
            "notes": stop.notes,
        }

    # --- legs -------------------------------------------------------------------------------

    def stop_range(self, stops: list[_Stop]) -> str:
        if not stops:
            return "this tab has no stops"
        return f"stops are rows {stops[0].row}-{stops[-1].row}"

    def find_stop(self, ref: StopRef, stops: list[_Stop]) -> _Stop:
        if ref.row is not None:
            for stop in stops:
                if stop.row == ref.row:
                    return stop
            raise CellProblem(
                "bad_reference",
                f"row {ref.row} is not a stop; {self.stop_range(stops)}",
                hint="use the stop's row number as shown on the left, or its label",
            )
        for stop in stops:
            if stop.label and fold(stop.label) == ref.label:
                return stop
        raise CellProblem(
            "bad_reference",
            f"no stop is labelled {ref.label!r}",
            hint="labels are in the Stop column of the stops table",
        )

    def parse_legs(self, stops: list[_Stop]) -> list[_Leg]:
        block = self.layout.legs
        if block is None:
            return []
        legs: list[_Leg] = []
        for row, cells in block.rows:
            get = _getter(cells)
            leg = _Leg(row=row, label=text(get("label"))[:40])
            for name, attr in (("from", "origin"), ("to", "destination")):
                try:
                    ref = stop_ref(get(name))
                    if ref is not None:
                        setattr(leg, attr, self.find_stop(ref, stops))
                except CellProblem as problem:
                    self.cell_issue(block, row, name, problem)
            try:
                leg.mode = mode(get("mode"))
            except CellProblem as problem:
                self.cell_issue(block, row, "mode", problem)
            if leg.mode is None and "mode" in block.columns and is_blank(get("mode")):
                self.cell_issue(
                    block, row, "mode", CellProblem("missing_field", "a leg needs a Mode")
                )
            for name in ("depart", "arrive"):
                cell = cells.get(name)
                try:
                    value = local_time(cell.value, cell.number_format) if cell else None
                except CellProblem as problem:
                    self.cell_issue(block, row, name, problem)
                    value = None
                setattr(leg, name, value)
            for name in ("depart_tz", "arrive_tz"):
                try:
                    leg.values[name] = zone_name(get(name))
                except CellProblem as problem:
                    self.cell_issue(block, row, name, problem)
                    leg.values[name] = None
            for name in (*FLIGHT_COLUMNS, "vehicle", "people"):
                leg.values[name] = cells.get(name)
            raw_notes = get("notes")
            notes = str(raw_notes).strip() if not is_blank(raw_notes) else None
            if notes and len(notes) > MAX_NOTES:
                self.cell_issue(
                    block,
                    row,
                    "notes",
                    CellProblem("bad_value", "Notes are longer than 20,000 characters"),
                )
                notes = notes[:MAX_NOTES]
            leg.values["notes"] = notes
            legs.append(leg)
        return legs

    def leg_value(self, leg: _Leg, name: str):
        cell = leg.values.get(name)
        return cell.value if cell is not None else None

    def resolve_legs(self, legs: list[_Leg], start: dt.date | None) -> None:
        block = self.layout.legs
        for leg in legs:
            local_day = (leg.depart or leg.arrive).date if (leg.depart or leg.arrive) else start
            when = n.FlightDate(local_day, "day") if local_day else None
            is_flight = leg.mode == "flight"
            if not is_flight:
                given = [
                    block.headers.get(name, name)
                    for name in FLIGHT_COLUMNS
                    if not is_blank(self.leg_value(leg, name))
                ]
                if given and leg.mode:
                    self.add(
                        "warning",
                        "bad_value",
                        f"flight columns ignored on a {leg.mode} leg: " + ", ".join(given),
                        row=leg.row,
                    )
            else:
                self.flight_fields(leg, when)
            self.leg_zones_and_times(leg)
            self.leg_vehicle_people(leg)
            if leg.origin is None and leg.destination is None and not is_flight and leg.mode:
                self.add(
                    "warning",
                    "bad_reference",
                    "the leg has neither From nor To",
                    row=leg.row,
                    column=block.letter("from"),
                    header=block.headers.get("from", ""),
                    field="from",
                )

    def flight_fields(self, leg: _Leg, when: n.FlightDate | None) -> None:
        block = self.layout.legs
        for name, attr, stop in (
            ("from_airport", "origin_airport", leg.origin),
            ("to_airport", "destination_airport", leg.destination),
        ):
            code = n.airport_code(self.leg_value(leg, name))
            if code:
                try:
                    airport, warnings = resolve_code(code, when)
                    setattr(leg, attr, airport)
                    for warning in warnings:
                        self.cell_issue(
                            block, leg.row, name, CellProblem("check", warning), "warning"
                        )
                except CellProblem as problem:
                    self.cell_issue(block, leg.row, name, problem)
                    setattr(leg, attr, False)  # given but unresolved: no second problem
            elif stop is not None and stop.place is not None and stop.place.airport_id:
                from travel.geo.models import Airport

                setattr(leg, attr, Airport.objects.filter(pk=stop.place.airport_id).first())
        for name, attr, end in (
            ("from_airport", "origin_airport", "From"),
            ("to_airport", "destination_airport", "To"),
        ):
            if getattr(leg, attr) is None:
                self.cell_issue(
                    block,
                    leg.row,
                    name,
                    CellProblem(
                        "missing_airport",
                        f"a flight needs an airport at its {end} end",
                        hint=f"fill {block.headers.get(name, name)}, or make the stop an airport",
                    ),
                )
            elif getattr(leg, attr) is False:
                setattr(leg, attr, None)
        prefix, number = n.split_flight_number(self.leg_value(leg, "flight"))
        airline_text = text(self.leg_value(leg, "airline")) or prefix
        leg.values["flight_number"] = (f"{prefix}{number}" if prefix else number)[:16]
        leg.values["airline_id"] = None
        if airline_text:
            airline = resolve_airline(airline_text, when, code_hint=prefix)
            if airline.problem:
                column = "airline" if text(self.leg_value(leg, "airline")) else "flight"
                self.cell_issue(
                    block, leg.row, column, CellProblem(airline.problem, airline.detail)
                )
            elif airline.obj is not None:
                leg.values["airline_id"] = airline.obj.pk
        aircraft_text = text(self.leg_value(leg, "aircraft"))
        aircraft = resolve_aircraft(aircraft_text)
        leg.values["aircraft_type_id"] = aircraft.obj.pk if aircraft.obj else None
        for warning in aircraft.warnings:
            self.cell_issue(block, leg.row, "aircraft", CellProblem("check", warning), "warning")
        leg.values["aircraft_registration"] = (
            text(self.leg_value(leg, "registration")).upper().replace(" ", "")[:16]
        )
        leg.values["seat"] = text(self.leg_value(leg, "seat")).upper().replace(" ", "")[:8]
        cabin_raw = self.leg_value(leg, "cabin")
        cabin, known = n.cabin_class(cabin_raw)
        if not known:
            self.cell_issue(
                block,
                leg.row,
                "cabin",
                CellProblem(
                    "bad_value",
                    f"cabin {text(cabin_raw)!r} is not one of: economy, premium_economy, "
                    "business, first, other",
                ),
            )
            cabin = ""
        leg.values["cabin_class"] = cabin

    def leg_zone(self, given: str | None, stop: _Stop | None, airport) -> str:
        if given:
            return given
        if stop is not None and stop.tz:
            return stop.tz
        if airport:
            found = self.zone_for(airport_place(airport))
            if found:
                return found[0]
        return ""

    def leg_zones_and_times(self, leg: _Leg) -> None:
        block = self.layout.legs
        start_tz = self.leg_zone(leg.values["depart_tz"], leg.origin, leg.origin_airport)
        end_tz = self.leg_zone(leg.values["arrive_tz"], leg.destination, leg.destination_airport)
        leg.values["start_tz"], leg.values["end_tz"] = start_tz, end_tz
        for name, local, zone, column in (
            ("start_utc", leg.depart, start_tz, "depart"),
            ("end_utc", leg.arrive, end_tz, "arrive"),
        ):
            if local is None:
                continue
            if not zone:
                self.cell_issue(
                    block,
                    leg.row,
                    f"{column}_tz",
                    CellProblem(
                        "unknown_zone",
                        f"no time zone known for the {column} time",
                        hint=f"type a {column.capitalize()} zone, such as America/Denver",
                    ),
                )
                continue
            try:
                setattr(leg, name, to_utc(local, zone))
            except CellProblem as problem:
                self.cell_issue(block, leg.row, column, problem)
        if leg.start_utc and leg.end_utc and leg.end_utc < leg.start_utc:
            self.cell_issue(
                block,
                leg.row,
                "arrive",
                CellProblem("end_before_start", "Arrive is before Depart"),
            )

    def leg_vehicle_people(self, leg: _Leg) -> None:
        block = self.layout.legs
        leg.values["vehicle_id"] = None
        if name := text(self.leg_value(leg, "vehicle")):
            try:
                leg.values["vehicle_id"] = self.dir.vehicle(name).pk
            except CellProblem as problem:
                self.cell_issue(block, leg.row, "vehicle", problem)

        def report(problem, creates=""):
            self.add(
                "problem",
                problem.reason,
                problem.message,
                row=leg.row,
                column=block.letter("people"),
                header=block.headers.get("people", "People"),
                field="people",
                hint=problem.hint,
                creates=creates,
            )

        leg.values["people_list"] = self.people(leg.values.get("people"), report)

    def check_chain(self, legs: list[_Leg]) -> None:
        """The guard against stale row numbers after inserted rows (§28.5)."""
        previous = None
        for leg in legs:
            if previous is not None:
                before = _end_identity(previous)
                here = _start_identity(leg)
                if before and here and before != here:
                    self.add(
                        "warning",
                        "broken_chain",
                        f"starts at {_start_name(leg)}, but the previous leg ended at "
                        f"{_end_name(previous)}",
                        row=leg.row,
                    )
                if previous.start_utc and leg.start_utc and leg.start_utc < previous.start_utc:
                    self.add(
                        "warning",
                        "out_of_order",
                        "departs before the previous leg",
                        row=leg.row,
                    )
            origin, destination = leg.origin, leg.destination
            if origin and origin.arrive_utc and leg.start_utc and leg.start_utc < origin.arrive_utc:
                self.add(
                    "warning",
                    "time_mismatch",
                    f"departs before arriving at {origin.display()} (row {origin.row})",
                    row=leg.row,
                )
            if (
                destination
                and destination.depart_utc
                and leg.end_utc
                and leg.end_utc > destination.depart_utc
            ):
                self.add(
                    "warning",
                    "time_mismatch",
                    f"arrives after leaving {destination.display()} (row {destination.row})",
                    row=leg.row,
                )
            if (
                leg.mode == "flight"
                and origin
                and destination
                and origin.place
                and destination.place
                and distance_km(origin.place.as_dict(), destination.place.as_dict())
                < CLOSE_FLIGHT_KM
            ):
                self.add(
                    "warning",
                    "short_flight",
                    f"a flight between stops less than {CLOSE_FLIGHT_KM} km apart",
                    row=leg.row,
                )
            previous = leg

    # --- dates and keys ---------------------------------------------------------------------

    def trip_dates(self, stops, legs) -> tuple[dt.date | None, dt.date | None, str]:
        start = self.trip_date("start")
        end = self.trip_date("end")
        days = [
            t.date
            for t in [s.arrive for s in stops]
            + [s.depart for s in stops]
            + [leg.depart for leg in legs]
            + [leg.arrive for leg in legs]
            if t is not None
        ]
        last_days = [
            t.last_date()
            for t in [s.arrive for s in stops]
            + [s.depart for s in stops]
            + [leg.depart for leg in legs]
            + [leg.arrive for leg in legs]
            if t is not None
        ]
        first = start.date if start else (min(days) if days else None)
        if end is not None:
            last = end.last_date()
        elif last_days:
            last = max(last_days)
        elif start is not None:
            last = start.last_date()
        else:
            last = None
        if first is None or last is None:
            self.add(
                "problem",
                "no_dates",
                "no dates: give Start and End, or times on the stops or legs",
                field="start",
            )
            return None, None, "day"
        if last < first:
            self.trip_issue("end", CellProblem("end_before_start", "End is before Start"))
        precision = coarsest([t.precision for t in (start, end) if t is not None] or ["day"])
        return first, last, precision

    def assign_keys(self, stops: list[_Stop], legs: list[_Leg]) -> None:
        """§28.9: a label, else place + local date + occurrence (stops) or mode + ends + local
        departure date + occurrence (legs)."""
        seen: Counter = Counter()
        for stop in stops:
            if stop.label:
                stop.key = f"label:{fold(stop.label)}"
                continue
            local = stop.arrive or stop.depart
            identity = stop.place.identity() if stop.place else f"row:{stop.row}"
            base = f"stop|{identity}|{local.date.isoformat() if local else ''}"
            seen[base] += 1
            stop.key = f"{base}#{seen[base]}"
        for leg in legs:
            if leg.label:
                leg.key = f"label:{fold(leg.label)}"
                continue
            local = leg.depart or leg.arrive
            ends = []
            for stop, airport in (
                (leg.origin, leg.origin_airport),
                (leg.destination, leg.destination_airport),
            ):
                ends.append(stop.key if stop else (f"ap:{airport.pk}" if airport else ""))
            day = local.date.isoformat() if local else ""
            base = f"leg|{leg.mode or ''}|{ends[0]}|{ends[1]}|{day}"
            seen[base] += 1
            leg.key = f"{base}#{seen[base]}"

    def leg_content(self, leg: _Leg) -> dict:
        v = leg.values
        is_flight = leg.mode == "flight"

        def end_label(stop: _Stop | None, airport) -> str:
            if stop is not None:
                return stop.display()[:200]
            if airport:
                return (airport.iata_code or airport.icao_code or airport.ident)[:200]
            return ""

        def point(stop: _Stop | None, airport) -> list[float] | None:
            if stop is not None and stop.place is not None:
                return [stop.place.lon, stop.place.lat]
            if airport:
                return [round(airport.point.x, 6), round(airport.point.y, 6)]
            return None

        return {
            "row": leg.row,
            "label": leg.label,
            "sheet_key": leg.key,
            "origin_row": leg.origin.row if leg.origin else None,
            "destination_row": leg.destination.row if leg.destination else None,
            "origin_key": leg.origin.key if leg.origin else None,
            "destination_key": leg.destination.key if leg.destination else None,
            "origin_label": end_label(leg.origin, leg.origin_airport),
            "destination_label": end_label(leg.destination, leg.destination_airport),
            "origin_point": point(leg.origin, leg.origin_airport),
            "destination_point": point(leg.destination, leg.destination_airport),
            "mode": leg.mode,
            "start_utc": _iso(leg.start_utc),
            "end_utc": _iso(leg.end_utc),
            "times_given": bool(leg.depart or leg.arrive),
            "start_tz": v.get("start_tz") or "",
            "end_tz": v.get("end_tz") or "",
            "time_precision": coarsest(
                [t.precision for t in (leg.depart, leg.arrive) if t is not None]
            ),
            "origin_airport_id": leg.origin_airport.pk
            if is_flight and leg.origin_airport
            else None,
            "destination_airport_id": (
                leg.destination_airport.pk if is_flight and leg.destination_airport else None
            ),
            "airline_id": v.get("airline_id") if is_flight else None,
            "flight_number": (v.get("flight_number") or None) if is_flight else None,
            "aircraft_type_id": v.get("aircraft_type_id") if is_flight else None,
            "aircraft_registration": (v.get("aircraft_registration") or None)
            if is_flight
            else None,
            "seat": (v.get("seat") or None) if is_flight else None,
            "cabin_class": (v.get("cabin_class") or None) if is_flight else None,
            "vehicle_id": v.get("vehicle_id"),
            "people": v.get("people_list"),
            "notes": v.get("notes"),
        }


def _getter(cells: dict):
    def get(name: str):
        cell = cells.get(name)
        return cell.value if cell is not None else None

    return get


def _start_identity(leg: _Leg) -> str:
    if leg.origin is not None:
        return f"stop:{leg.origin.row}"
    return f"ap:{leg.origin_airport.pk}" if leg.origin_airport else ""


def _end_identity(leg: _Leg) -> str:
    if leg.destination is not None:
        return f"stop:{leg.destination.row}"
    return f"ap:{leg.destination_airport.pk}" if leg.destination_airport else ""


def _start_name(leg: _Leg) -> str:
    if leg.origin is not None:
        return f"{leg.origin.display()} (row {leg.origin.row})"
    return leg.origin_airport.iata_code or leg.origin_airport.ident


def _end_name(leg: _Leg) -> str:
    if leg.destination is not None:
        return f"{leg.destination.display()} (row {leg.destination.row})"
    return leg.destination_airport.iata_code or leg.destination_airport.ident


# --- Workbook ---------------------------------------------------------------------------------


@dataclass
class ParsedWorkbook:
    tabs: list[ParsedTab]
    issues: list[dict]  # workbook-level (tabs left unread)


def parse_workbook(data: bytes, user) -> ParsedWorkbook:
    """Every trip tab of the workbook, as `user` (under the caller's RLS context). Raises
    SheetFileError for a file that can't be read at all."""
    raw_tabs, extra = read_tabs(data)
    directory = Directory(user)
    tabs = [TabParser(raw, directory).parse() for raw in raw_tabs]
    by_key: dict[str, list[ParsedTab]] = {}
    for tab in tabs:
        by_key.setdefault(tab.key, []).append(tab)
    for key, same in by_key.items():
        if len(same) < 2:
            continue
        names = ", ".join(repr(t.name) for t in same)
        for tab in same:
            tab.issues.append(
                Issue(
                    tab=tab.name,
                    row=tab.key_row,
                    column="B" if tab.key_row else "",
                    header="Key",
                    field="key",
                    severity="problem",
                    reason="duplicate_key",
                    message=f"tabs {names} have the same key {key!r}",
                    hint="give each trip its own Key",
                )
            )
    issues = []
    if extra:
        issues.append(
            {
                "severity": "problem",
                "reason": "too_large",
                "message": f"only the first 500 trip tabs are read; {extra} more were skipped",
            }
        )
    return ParsedWorkbook(tabs, issues)


__all__ = [
    "STOP_COLUMNS",
    "ParsedTab",
    "ParsedWorkbook",
    "SheetFileError",
    "content_hash",
    "parse_workbook",
]
