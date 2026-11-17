"""The flight import template (PLAN.md §12.3, docs/flights/README.md) and the row processing
shared by the converter and the importer: normalise every cell, resolve codes by the flight
date, and collect what blocks a row (problems) and what only deserves a look (warnings)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from . import normalize as n
from .resolve import resolve_aircraft, resolve_airline, resolve_airport

COLUMNS = [
    "trip_key",
    "date",
    "dep_time",
    "arr_time",
    "arr_date",
    "from",
    "to",
    "airline",
    "flight_number",
    "aircraft",
    "registration",
    "seat",
    "cabin_class",
    "seat_type",
    "purpose",
    "notes",
    "participants",
]
REQUIRED = ("date", "from", "to")

# Why a row can't be imported as it is (shown in the unmatched report).
REASONS = {
    "missing_field": "a required value is empty",
    "bad_date": "the date can't be read",
    "missing_airport": "no airport given",
    "unknown_airport": "no airport has this code",
    "ambiguous_airport": "the code fits more than one airport at that date",
    "airport_closed": "the airport with this code had closed by that date",
    "unknown_airline": "no airline matches",
    "ambiguous_airline": "the code fits more than one airline at that date",
}


@dataclass
class Issue:
    field: str
    reason: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"field": self.field, "reason": self.reason, "detail": self.detail}


@dataclass
class ProcessedRow:
    row_number: int
    values: dict[str, str]  # normalised template values, as written to a converted file
    fields: dict[str, Any]  # FlightRecord field values
    problems: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def identity(self) -> str:
        v = self.values
        return "|".join(
            [v["date"], v["from"], v["to"], v["airline"].upper(), v["flight_number"], v["dep_time"]]
        )

    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.values, sort_keys=True).encode()).hexdigest()


def _time_text(value) -> str:
    return value.strftime("%H:%M") if value else ""


def process_row(raw: dict[str, Any], row_number: int, *, dayfirst: bool = False) -> ProcessedRow:
    """`raw` maps template column names to cell values (strings, numbers, dates...)."""
    problems: list[Issue] = []
    warnings: list[Issue] = []
    get = lambda key: raw.get(key)  # noqa: E731

    when = None
    if n.text(get("date")) == "" and not hasattr(get("date"), "year"):
        problems.append(Issue("date", "missing_field", "date is required"))
    else:
        try:
            when = n.parse_date(get("date"), dayfirst=dayfirst)
        except n.ValueProblem as exc:
            problems.append(Issue("date", "bad_date", str(exc)))

    times = {}
    for key in ("dep_time", "arr_time"):
        try:
            times[key] = n.parse_time(get(key))
        except n.ValueProblem as exc:
            times[key] = None
            warnings.append(Issue(key, "bad_time", str(exc)))
    arr_date = None
    try:
        parsed = n.parse_date(get("arr_date"), dayfirst=dayfirst)
        if parsed is not None and parsed.precision != "day":
            warnings.append(Issue("arr_date", "bad_date", "arrival date needs a full date"))
        elif parsed is not None:
            arr_date = parsed.date
    except n.ValueProblem as exc:
        warnings.append(Issue("arr_date", "bad_date", str(exc)))

    origin = n.airport_code(get("from"))
    destination = n.airport_code(get("to"))
    if not origin and not destination and (route := n.split_route(get("route"))):
        origin, destination = route
    resolved = {}
    for key, code in (("from", origin), ("to", destination)):
        result = resolve_airport(code, when) if code else None
        if result is None:
            problems.append(Issue(key, "missing_field", f"{key} airport is required"))
            resolved[key] = None
            continue
        if result.problem and not (result.problem == "bad_date" and when is None):
            problems.append(Issue(key, result.problem, result.detail))
        warnings += [Issue(key, "check", text) for text in result.warnings]
        resolved[key] = result.obj
    if origin and origin == destination:
        warnings.append(Issue("to", "check", "origin and destination are the same"))

    prefix, number = n.split_flight_number(get("flight_number"))
    airline_text = n.text(get("airline")) or prefix
    flight_number = f"{prefix}{number}" if prefix else number
    airline = resolve_airline(airline_text, when, code_hint=prefix)
    if airline.problem:
        problems.append(Issue("airline", airline.problem, airline.detail))

    aircraft_text = n.text(get("aircraft"))
    aircraft = resolve_aircraft(aircraft_text)
    warnings += [Issue("aircraft", "check", text) for text in aircraft.warnings]

    cabin, known = n.cabin_class(get("cabin_class"))
    if not known:
        warnings.append(Issue("cabin_class", "check", f"cabin {n.text(get('cabin_class'))!r}"))
    seat_type = n.seat_type(get("seat_type"))
    people = n.participants(get("participants"))
    values = {
        "trip_key": n.text(get("trip_key"))[:100],
        "date": when.iso() if when else n.text(get("date")),
        "dep_time": _time_text(times["dep_time"]) or n.text(get("dep_time")),
        "arr_time": _time_text(times["arr_time"]) or n.text(get("arr_time")),
        "arr_date": arr_date.isoformat() if arr_date else n.text(get("arr_date")),
        "from": origin,
        "to": destination,
        "airline": airline_text[:200],
        "flight_number": flight_number[:16],
        "aircraft": aircraft_text[:200],
        "registration": n.text(get("registration")).upper().replace(" ", "")[:16],
        "seat": n.text(get("seat")).upper().replace(" ", "")[:8],
        "cabin_class": cabin,
        "seat_type": seat_type,
        "purpose": n.text(get("purpose"))[:100],
        "notes": n.text(get("notes")),
        "participants": "; ".join(people),
    }
    fields = {
        "trip_key": values["trip_key"],
        "date": when.date if when else None,
        "date_precision": when.precision if when else "",
        "dep_time": times["dep_time"],
        "arr_time": times["arr_time"],
        "arr_date": arr_date,
        "from_code": origin[:100],
        "to_code": destination[:100],
        "origin_airport": resolved["from"],
        "destination_airport": resolved["to"],
        "airline_text": values["airline"],
        "airline": airline.obj,
        "flight_number": values["flight_number"],
        "aircraft_text": values["aircraft"],
        "aircraft_type": aircraft.obj,
        "registration": values["registration"],
        "seat": values["seat"],
        "cabin_class": cabin,
        "seat_type": seat_type,
        "purpose": values["purpose"],
        "notes": values["notes"],
        "participants": people,
    }
    return ProcessedRow(row_number, values, fields, problems, warnings)


def row_keys(rows: list[ProcessedRow]) -> list[str]:
    """Stable per-row keys: identical flights in one file stay distinct by occurrence."""
    seen: Counter = Counter()
    keys = []
    for row in rows:
        identity = row.identity()
        seen[identity] += 1
        keys.append(hashlib.sha256(f"{identity}#{seen[identity]}".encode()).hexdigest())
    return keys
