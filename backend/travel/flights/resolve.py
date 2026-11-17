"""Date-aware resolution of airport, airline and aircraft codes (PLAN.md §12.2, D-39, D-88).

Airports, in order:
  1. An override (`manual`, else `bundled`) for the code whose validity covers the flight date.
  2. An active airport with the code (IATA for 3 letters; ICAO, then ident, then GPS code for 4),
     unless an override for that airport and code says the date is outside its period.
  3. A closed airport listing the code (OurAirports keywords, or its ident for 4 letters) whose
     closure is on or after the flight date, or unknown.
  A closed airport whose known closure covers the date beats an active one only through an
  override; if both are possible the row is ambiguous. A known closure before the date is an
  error. Partial dates (month, year) must fit wholly inside a period, otherwise ambiguous.
  Text without a code may match one scheduled-service airport by city name (with a warning).

Airlines: overrides by date, then ICAO (3 letters), then IATA (2 characters) preferring
airlines with an ICAO code and, for flights after the OpenFlights snapshot, active ones; then
the name or alias. More than one candidate left is ambiguous. Aircraft types never block a row.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from django.db.models import Q

from travel.geo.models import (
    AircraftType,
    Airline,
    AirlineCodeHistory,
    Airport,
    AirportCodeHistory,
)

from .normalize import FlightDate

# OpenFlights airlines were last updated on this date; its `active` flag means "active then".
OPENFLIGHTS_SNAPSHOT = dt.date(2017, 2, 2)
CLOSED = "closed"


@dataclass
class Resolution:
    obj: object | None = None
    problem: str = ""  # unknown_*, ambiguous_*, airport_closed, bad_code
    detail: str = ""
    warnings: list[str] = field(default_factory=list)
    rule: str = ""


def _covers(valid_from, valid_to, when: FlightDate) -> bool:
    return (valid_from is None or valid_from <= when.start) and (
        valid_to is None or when.end <= valid_to
    )


def _overlaps(valid_from, valid_to, when: FlightDate) -> bool:
    return (valid_from is None or valid_from <= when.end) and (
        valid_to is None or when.start <= valid_to
    )


def _label(airport: Airport) -> str:
    return f"{airport.ident} {airport.name}"


def _names(objs) -> str:
    return "; ".join(_label(o) if isinstance(o, Airport) else str(o) for o in objs)


def resolve_airport(raw: str, when: FlightDate | None) -> Resolution:
    code = (raw or "").strip().upper()
    if not code:
        return Resolution(problem="missing_airport", detail="no airport given")
    if not re.fullmatch(r"[A-Z0-9]{3,4}", code):
        return _by_city(raw)
    if when is None:
        return Resolution(problem="bad_date", detail="no usable date to resolve the code by")

    overrides = list(
        AirportCodeHistory.objects.filter(
            code=code,
            source__in=[AirportCodeHistory.Source.MANUAL, AirportCodeHistory.Source.BUNDLED],
        ).select_related("airport")
    )
    for source in (AirportCodeHistory.Source.MANUAL, AirportCodeHistory.Source.BUNDLED):
        rows = [row for row in overrides if row.source == source]
        covering = {row.airport for row in rows if _covers(row.valid_from, row.valid_to, when)}
        if len(covering) == 1:
            return Resolution(obj=covering.pop(), rule=f"override ({source})")
        if len(covering) > 1:
            return Resolution(
                problem="ambiguous_airport",
                detail=f"{code}: several overrides cover the date: {_names(covering)}",
            )
        overlapping = {row.airport for row in rows if _overlaps(row.valid_from, row.valid_to, when)}
        if len(overlapping) == 1:
            airport = overlapping.pop()
            return Resolution(
                obj=airport,
                rule=f"override ({source})",
                warnings=[f"{code} at {when.iso()} only partly within {_label(airport)}'s period"],
            )
        if overlapping:
            return Resolution(
                problem="ambiguous_airport",
                detail=f"{code} changed airports during {when.iso()}; give the exact date",
            )
    # Airports whose overrides for this code don't cover the date are out of the running.
    excluded = {row.airport_id for row in overrides}

    if len(code) == 3:
        active = list(Airport.objects.filter(iata_code=code).exclude(type=CLOSED))
    else:
        active = []
        for column in ("icao_code", "ident", "gps_code"):
            active = list(Airport.objects.filter(**{column: code}).exclude(type=CLOSED))
            if active:
                break
    active = [airport for airport in active if airport.pk not in excluded]
    if len(active) > 1:
        scheduled = [airport for airport in active if airport.scheduled_service]
        active = scheduled or active

    closed_rows = AirportCodeHistory.objects.filter(
        code=code, source=AirportCodeHistory.Source.KEYWORDS
    ).select_related("airport")
    closed = {row.airport for row in closed_rows if row.airport_id not in excluded}
    if len(code) == 4:
        closed |= {
            airport
            for airport in Airport.objects.filter(type=CLOSED, ident=code)
            if airport.pk not in excluded
        }
    in_service = [a for a in closed if a.closed_on is not None and when.end <= a.closed_on]
    unknown = [a for a in closed if a.closed_on is None]
    gone = [a for a in closed if a.closed_on is not None and when.end > a.closed_on]

    if len(active) == 1:
        if in_service:
            return Resolution(
                problem="ambiguous_airport",
                detail=f"{code} at {when.iso()}: {_names(active + in_service)}",
            )
        result = Resolution(obj=active[0], rule="active airport")
        if unknown:
            result.warnings.append(
                f"{code} is also listed for closed airport(s) with unknown closure date: "
                f"{_names(unknown)}"
            )
        return result
    if len(active) > 1:
        return Resolution(problem="ambiguous_airport", detail=f"{code}: {_names(active)}")
    candidates = in_service + unknown
    if len(candidates) == 1:
        result = Resolution(obj=candidates[0], rule="closed airport")
        if unknown:
            result.warnings.append(
                f"{code} resolved to closed airport {_label(candidates[0])}; its closure date "
                "is unknown"
            )
        return result
    if len(candidates) > 1:
        return Resolution(
            problem="ambiguous_airport", detail=f"{code} at {when.iso()}: {_names(candidates)}"
        )
    gone += [
        row.airport
        for row in overrides
        if row.valid_to is not None and row.valid_to < when.start and row.airport not in gone
    ]
    if gone:
        return Resolution(
            problem="airport_closed",
            detail=f"{code} belonged to {_names(dict.fromkeys(gone))}, closed before {when.iso()}",
        )
    return Resolution(problem="unknown_airport", detail=f"no airport with code {code}")


def _by_city(raw: str) -> Resolution:
    name = re.sub(r"\s+", " ", raw).strip()
    matches = list(
        Airport.objects.filter(scheduled_service=True)
        .exclude(type=CLOSED)
        .exclude(iata_code="")
        .filter(Q(municipality__iexact=name) | Q(name__iexact=name))
    )
    if len(matches) == 1:
        return Resolution(
            obj=matches[0],
            rule="city name",
            warnings=[f"{name!r} has no airport code; matched {_label(matches[0])} by name"],
        )
    if len(matches) > 1:
        return Resolution(
            problem="ambiguous_airport", detail=f"{name!r} matches {_names(matches[:5])}"
        )
    return Resolution(problem="unknown_airport", detail=f"no airport code in {name!r}")


# --- Airlines -------------------------------------------------------------------------------


def _airline_names(airlines) -> str:
    return "; ".join(
        f"{a.name} ({a.iata or '-'}/{a.icao or '-'}{'' if a.active else ', inactive'})"
        for a in airlines
    )


def _narrow(candidates: list[Airline], when: FlightDate | None) -> list[Airline]:
    # OpenFlights has many half-filled duplicates; an airline with real codes is the likely one.
    candidates = [a for a in candidates if a.icao] or candidates
    if len(candidates) > 1:
        candidates = [a for a in candidates if a.iata] or candidates
    if len(candidates) > 1 and when is not None and when.start >= OPENFLIGHTS_SNAPSHOT:
        candidates = [a for a in candidates if a.active] or candidates
    return candidates


def _by_iata(code: str, when: FlightDate | None) -> tuple[list[Airline], str]:
    overrides = list(AirlineCodeHistory.objects.filter(code=code).select_related("airline"))
    if when is not None:
        covering = {r.airline for r in overrides if _covers(r.valid_from, r.valid_to, when)}
        if not covering:
            covering = {r.airline for r in overrides if _overlaps(r.valid_from, r.valid_to, when)}
            if len(covering) > 1:
                return list(covering), "changed during period"
        if len(covering) == 1:
            return list(covering), "override"
    excluded = {r.airline_id for r in overrides}
    candidates = [a for a in Airline.objects.filter(iata=code) if a.pk not in excluded]
    return _narrow(candidates, when), "iata"


def _normal_name(name: str) -> str:
    name = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    name = re.sub(r"\b(airlines?|airways|air lines|aviation|inc|ltd|co)\b", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _by_name(name: str, when: FlightDate | None) -> list[Airline]:
    exact = list(Airline.objects.filter(Q(name__iexact=name) | Q(alias__iexact=name)))
    if exact:
        return _narrow(exact, when)
    wanted = _normal_name(name)
    if not wanted:
        return []
    first = wanted.split()[0]
    loose = [
        a
        for a in Airline.objects.filter(Q(name__icontains=first) | Q(alias__icontains=first))
        if wanted in (_normal_name(a.name), _normal_name(a.alias))
    ]
    return _narrow(loose, when)


def resolve_airline(raw: str, when: FlightDate | None, code_hint: str = "") -> Resolution:
    """`code_hint` is the prefix of the flight number ('UA' in 'UA 123'), used to pick among
    airlines that match a name."""
    value = re.sub(r"\s+", " ", raw or "").strip()
    if not value:
        return Resolution()
    upper = value.upper()
    candidates: list[Airline] = []
    rule = ""
    if re.fullmatch(r"[A-Z]{3}", upper):
        candidates, rule = _narrow(list(Airline.objects.filter(icao=upper)), when), "icao"
    if not candidates and re.fullmatch(r"[A-Z0-9]{2}", upper) and re.search(r"[A-Z]", upper):
        candidates, rule = _by_iata(upper, when)
    if not candidates:
        candidates, rule = _by_name(value, when), "name"
    hint = code_hint.upper()
    if len(candidates) > 1 and hint:
        hinted = [a for a in candidates if hint in (a.iata, a.icao)]
        candidates = hinted or candidates
    if len(candidates) == 1:
        return Resolution(obj=candidates[0], rule=rule)
    if candidates:
        detail = f"{value!r}: {_airline_names(candidates[:6])}"
        if rule == "changed during period" and when is not None:
            detail = f"{value!r} changed airlines during {when.iso()}; give the exact date"
        return Resolution(problem="ambiguous_airline", detail=detail)
    return Resolution(problem="unknown_airline", detail=f"no airline matches {value!r}")


# --- Aircraft -------------------------------------------------------------------------------


def resolve_aircraft(raw: str) -> Resolution:
    value = re.sub(r"\s+", " ", raw or "").strip()
    if not value:
        return Resolution()
    upper = value.upper()
    for column in ("icao", "iata"):
        found = list(AircraftType.objects.filter(**{column: upper})[:2])
        if len(found) == 1:
            return Resolution(obj=found[0], rule=column)
    found = list(AircraftType.objects.filter(name__iexact=value)[:2])
    if len(found) != 1:
        found = list(AircraftType.objects.filter(name__icontains=value)[:20])
        if len(found) > 1:  # "747-400" → "Boeing 747-400", not "Boeing 747-400F"
            found = [a for a in found if a.name.lower().endswith(" " + value.lower())]
    if len(found) == 1:
        return Resolution(obj=found[0], rule="name")
    return Resolution(warnings=[f"aircraft {value!r} not matched; kept as text"], rule="unmatched")
