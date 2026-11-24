"""Resolving what a trip spreadsheet names (§28.3-§28.6): places (GeoNames id, coordinates,
airport code by date, or a city matched exactly in the gazetteer: several matches are a problem
listing candidates, never ranked into a choice), default time zones, and the caller's people,
purposes, tags and vehicles. Every lookup of user data runs under the caller's RLS and asks
travel.core.policy as well."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

from django.contrib.gis.geos import Point

from travel.accounts.models import Person
from travel.core import policy
from travel.flights import normalize as n
from travel.flights.resolve import resolve_airport
from travel.geo import gazetteer
from travel.geo.models import Airport, GeoNamesPlace
from travel.vehicles.models import Vehicle

from ..models import Purpose, Tag
from .values import CellProblem, text

NEAREST_ZONE_KM = 50
COORDINATES = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[,; ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
AIRPORT_CODE = re.compile(r"^(?:[A-Z]{3}|[A-Z]{4})$")
AIRPORT_PREFIX = re.compile(r"^airport:\s*([A-Za-z0-9]{3,4})$", re.I)
GEONAMES = re.compile(r"^geonames:\s*(\d+)$", re.I)


@dataclass
class Place:
    """A resolved stop place, stored in the record's content (JSON)."""

    kind: str  # geonames, coordinates, airport
    lat: float
    lon: float
    name: str  # default display name
    geonames_id: int | None = None
    airport_id: int | None = None
    airport_code: str = ""
    country_code: str = ""
    admin1_code: str = ""
    tz: str = ""  # the place's own zone ("" if it has none)

    def identity(self) -> str:
        if self.geonames_id:
            return f"gn:{self.geonames_id}"
        if self.airport_id:
            return f"ap:{self.airport_id}"
        return f"ll:{self.lat:.5f},{self.lon:.5f}"

    def as_dict(self) -> dict:
        return asdict(self)


def _round(value: float) -> float:
    return round(value, 6)


def _geonames_place(row: GeoNamesPlace) -> Place:
    return Place(
        kind="geonames",
        lat=_round(row.point.y),
        lon=_round(row.point.x),
        name=row.name,
        geonames_id=row.geonameid,
        country_code=row.country_code,
        admin1_code=row.admin1_code[:16],
        tz=row.timezone,
    )


def airport_place(airport: Airport) -> Place:
    region = airport.iso_region.split("-", 1)[1] if "-" in airport.iso_region else ""
    return Place(
        kind="airport",
        lat=_round(airport.point.y),
        lon=_round(airport.point.x),
        name=airport.name,
        airport_id=airport.pk,
        airport_code=airport.iata_code or airport.icao_code or airport.ident,
        country_code=airport.iso_country,
        admin1_code=region[:16],
    )


def airport_code(value: str) -> str | None:
    """`DEN`, `KDEN` (capitals only, so a short city isn't read as a code) or `airport:den`."""
    raw = value.strip()
    if AIRPORT_CODE.match(raw):
        return raw
    if m := AIRPORT_PREFIX.match(raw):
        return m[1].upper()
    return None


def resolve_code(code: str, when: n.FlightDate | None) -> tuple[Airport, list[str]]:
    result = resolve_airport(code, when)
    if result.problem:
        hint = "give the stop an Arrive or Depart date" if result.problem == "bad_date" else ""
        raise CellProblem(result.problem, result.detail, hint=hint)
    return result.obj, result.warnings


def place_text(value) -> str:
    return text(value)


def resolve_place(value, when: n.FlightDate | None) -> tuple[Place, list[str]]:
    """The place and any warnings; CellProblem when it can't be resolved without guessing."""
    raw = place_text(value)
    if not raw:
        raise CellProblem("missing_field", "a stop needs a Place")
    if m := GEONAMES.match(raw):
        row = GeoNamesPlace.objects.filter(geonameid=int(m[1])).first()
        if row is None:
            raise CellProblem("unknown_place", f"no gazetteer place geonames:{m[1]}")
        return _geonames_place(row), []
    if m := COORDINATES.match(raw):
        lat, lon = float(m[1]), float(m[2])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise CellProblem(
                "bad_value",
                f"coordinates {raw!r} are out of range",
                hint="latitude first: lat, lon in decimal degrees",
            )
        return Place(kind="coordinates", lat=_round(lat), lon=_round(lon), name=""), []
    if code := airport_code(raw):
        airport, warnings = resolve_code(code, when)
        return airport_place(airport), warnings
    return resolve_city(raw), []


def _matches(row: GeoNamesPlace, qualifier: str) -> tuple[bool, bool]:
    """(matches as region, matches as country)."""
    folded = gazetteer.fold(qualifier)
    region = qualifier.upper() == row.admin1_code.upper() or (
        bool(row.admin1_name) and folded == gazetteer.fold(row.admin1_name)
    )
    country = qualifier.upper() == row.country_code.upper() or (
        bool(row.country_name) and folded == gazetteer.fold(row.country_name)
    )
    return region, country


def _filtered(rows: list[GeoNamesPlace], qualifiers: list[str]) -> list[GeoNamesPlace]:
    if len(qualifiers) == 1:
        return [r for r in rows if any(_matches(r, qualifiers[0]))]
    region, country = qualifiers[-2], qualifiers[-1]
    return [r for r in rows if _matches(r, region)[0] and _matches(r, country)[1]]


def _picker_text(row: GeoNamesPlace, rows: list[GeoNamesPlace]) -> str:
    """The exact text that picks this candidate: `Name, region, CC` if that is unique among the
    candidates, else its GeoNames id."""
    label = f"{row.name}, {row.admin1_code or row.admin1_name}, {row.country_code}"
    same = [
        r for r in rows if (r.admin1_code, r.country_code) == (row.admin1_code, row.country_code)
    ]
    return label if len(same) == 1 and row.admin1_code else f"geonames:{row.geonameid}"


def resolve_city(raw: str) -> Place:
    """`Name[, region][, country]`, matched exactly on the gazetteer's names (accents and case
    folded). Population never chooses (D-95)."""
    parts = [part.strip() for part in raw.split(",")]
    name, qualifiers = parts[0], [p for p in parts[1:] if p]
    if not name or len(qualifiers) > 2:
        raise CellProblem(
            "unknown_place",
            f"can't read place {raw!r}",
            hint="write City, region, country (Santa Fe, NM, US), an airport code, "
            "lat, lon or geonames:<id>",
        )
    folded = gazetteer.fold(name)
    rows = list(GeoNamesPlace.objects.filter(name_folded=folded).order_by("geonameid")) or list(
        GeoNamesPlace.objects.filter(asciiname__iexact=name).order_by("geonameid")
    )
    if qualifiers:
        rows = _filtered(rows, qualifiers)
    if len(rows) == 1:
        return _geonames_place(rows[0])
    if rows:
        shown = sorted(rows, key=lambda r: (-r.population, r.geonameid))[:5]
        candidates = [_picker_text(r, rows) for r in shown]
        described = "; ".join(
            f"{r.name}, {r.admin1_name or r.admin1_code}, {r.country_name or r.country_code}"
            for r in shown
        )
        raise CellProblem(
            "ambiguous_place",
            f"{raw!r} matches {len(rows)} places: {described}",
            hint="type one of the candidates exactly",
            candidates=candidates,
        )
    near = [f"{p.name}, {p.admin1_code}, {p.country_code}" for p in gazetteer.search(name, 5)]
    raise CellProblem(
        "unknown_place",
        f"no gazetteer place is called {raw!r}",
        hint="check the spelling, or use lat, lon or geonames:<id>",
        candidates=near,
    )


def nearest_zone(lat: float, lon: float, country: str = "") -> tuple[str, str] | None:
    """The zone of the nearest gazetteer place within 50 km (in the same country when known),
    and that place's name. Zone borders can make it wrong (§28.6)."""
    point = Point(lon, lat, srid=4326)
    # A degree box first, so the spatial index of the reference table does the narrowing.
    degrees = min(10.0, NEAREST_ZONE_KM / (111.0 * max(0.05, math.cos(math.radians(lat)))))
    rows = GeoNamesPlace.objects.filter(point__dwithin=(point, degrees)).exclude(timezone="")
    if country:
        rows = rows.filter(country_code=country)
    best = None
    for row in rows[:2000]:
        distance = _km(lat, lon, row.point.y, row.point.x)
        if distance > NEAREST_ZONE_KM:
            continue
        if best is None or distance < best[0]:
            best = (distance, row)
    if best is None:
        return None
    return best[1].timezone, best[1].name


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def distance_km(a: dict, b: dict) -> float:
    return _km(a["lat"], a["lon"], b["lat"], b["lon"])


# --- The caller's own data ---------------------------------------------------------------------


class Directory:
    """The caller's lookups, loaded once per workbook under RLS (and checked with the policy)."""

    def __init__(self, user):
        self.user = user
        self._persons: list[Person] | None = None
        self.purposes = list(Purpose.objects.filter(owner_id=user.pk).order_by("sort", "name"))
        self.tags = {t.name.casefold(): t for t in Tag.objects.filter(owner_id=user.pk)}
        self._vehicles: list[Vehicle] | None = None

    @property
    def persons(self) -> list[Person]:
        if self._persons is None:
            self._persons = [
                p for p in Person.objects.order_by("pk") if policy.can_view_person(self.user, p)
            ]
        return self._persons

    @property
    def vehicles(self) -> list[Vehicle]:
        if self._vehicles is None:
            self._vehicles = [
                v for v in Vehicle.objects.order_by("pk") if policy.can_use_vehicle(self.user, v)
            ]
        return self._vehicles

    def person(self, name: str) -> Person:
        """`me` is the caller's own person; otherwise a display name (case-insensitive) among
        the people the caller can see. Unknown and several matches are problems (Q-20)."""
        if name.casefold() == "me":
            if self.user.person_id is None:
                raise CellProblem(
                    "unknown_person",
                    "'me' needs your own person in the app",
                    hint="use Add me in the app first",
                )
            mine = next((p for p in self.persons if p.pk == self.user.person_id), None)
            if mine is None:
                raise CellProblem("unknown_person", "'me' needs your own person in the app")
            return mine
        found = [p for p in self.persons if p.display_name.casefold() == name.casefold()]
        if len(found) > 1:
            raise CellProblem(
                "ambiguous_person",
                f"{len(found)} people are called {name!r}",
                hint="rename one of them in the app",
            )
        if not found:
            raise CellProblem(
                "unknown_person",
                f"nobody called {name!r} in the app",
                hint="add the person in the app, or tick 'create these people' in the preview",
            )
        return found[0]

    def purpose(self, name: str) -> Purpose:
        for purpose in self.purposes:
            if purpose.name.casefold() == name.casefold():
                return purpose
        known = ", ".join(p.name for p in self.purposes) or "none yet"
        raise CellProblem(
            "unknown_purpose", f"no purpose called {name!r}", hint=f"your purposes: {known}"
        )

    def vehicle(self, name: str) -> Vehicle:
        found = [v for v in self.vehicles if v.nickname.casefold() == name.casefold()]
        if len(found) > 1:
            raise CellProblem("ambiguous_vehicle", f"{len(found)} vehicles are called {name!r}")
        if not found:
            raise CellProblem(
                "unknown_vehicle",
                f"no vehicle you may use is called {name!r}",
                hint="the vehicle's nickname in the app",
            )
        return found[0]
