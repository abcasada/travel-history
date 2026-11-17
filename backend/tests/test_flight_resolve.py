"""Date-aware code resolution (PLAN.md §12.2, D-39, D-88) against the reference subsets."""

import pytest

from tests.flight_data import load_reference
from tests.helpers import as_owner
from travel.flights.normalize import parse_date
from travel.flights.resolve import resolve_aircraft, resolve_airline, resolve_airport
from travel.geo.models import Airport, AirportCodeHistory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def reference():
    load_reference()


def airport(code, when):
    result = resolve_airport(code, parse_date(when))
    return (result.obj.ident if result.obj else None), result.problem


@pytest.mark.parametrize(
    ("code", "when", "ident", "problem"),
    [
        ("DEN", "1990-05-01", "US-12484", ""),  # Stapleton before 1995-02-28
        ("DEN", "1995-02-27", "US-12484", ""),
        ("DEN", "1995-02-28", "KDEN", ""),
        ("DEN", "1994-06", "US-12484", ""),  # a month wholly inside the old period
        ("DEN", "1995", None, "ambiguous_airport"),  # the year spans the change
        ("HKG", "1997", "HK-0099", ""),
        ("HKG", "2005-01-01", "VHHH", ""),
        ("MUC", "1990-01-01", "DE-0901", ""),
        ("TXL", "2019-03-14", "DE-0876", ""),  # closed airport, known period
        ("TXL", "2021-05-05", None, "airport_closed"),
        ("BER", "2021-01-01", "EDDB", ""),
        ("BER", "2015-08-02", None, "ambiguous_airport"),  # Tempelhof or Schönefeld
        ("MCI", "1975-01-01", "KMCI", ""),
        ("KMCI", "2000-01-01", "KMCI", ""),  # ICAO code
        ("QQQ", "2000-01-01", None, "unknown_airport"),
        ("", "2000-01-01", None, "missing_airport"),
    ],
)
def test_airports_by_date(code, when, ident, problem):
    assert airport(code, when) == (ident, problem)


def test_manual_override_beats_bundled_and_active():
    with as_owner():
        AirportCodeHistory.objects.create(
            code="MCI", airport=Airport.objects.get(ident="KSTL"), source="manual"
        )
    assert airport("MCI", "2000-01-01") == ("KSTL", "")


def test_closed_airport_with_unknown_closure_warns():
    with as_owner():
        Airport.objects.filter(ident="US-12484").update(closed_on=None)
        AirportCodeHistory.objects.filter(source="bundled").delete()
        AirportCodeHistory.objects.filter(code="DEN").update(valid_to=None)
    result = resolve_airport("DEN", parse_date("1990"))
    assert result.obj.ident == "KDEN"  # the active airport, with a warning to check
    assert "unknown closure" in result.warnings[0]


def test_city_names():
    result = resolve_airport("Kansas City", parse_date("2000"))
    assert result.obj.ident == "KMCI" and result.warnings
    assert resolve_airport("Chicago", parse_date("2000")).problem == "ambiguous_airport"


def airline(value, when, hint=""):
    result = resolve_airline(value, parse_date(when), code_hint=hint)
    return (result.obj.name if result.obj else None), result.problem


@pytest.mark.parametrize(
    ("value", "when", "hint", "name", "problem"),
    [
        ("PA", "1985-07-04", "", "Pan American World Airways", ""),  # override by date
        ("PA", "1995-07-04", "", None, "ambiguous_airline"),
        ("TW", "1990-01-01", "", "Trans World Airlines", ""),
        ("TW", "2015-01-01", "", "Tway Airlines", ""),
        ("TWA", "1994-06", "", "Trans World Airlines", ""),  # ICAO
        ("UA", "2000-01-01", "", "United Airlines", ""),
        ("Southwest", "2000-01-01", "", "Southwest Airlines", ""),
        ("united airlines", "2000-01-01", "", "United Airlines", ""),
        ("Nowhere Air", "2000-01-01", "", None, "unknown_airline"),
        ("", "2000-01-01", "", None, ""),
    ],
)
def test_airlines_by_date(value, when, hint, name, problem):
    assert airline(value, when, hint) == (name, problem)


def test_flight_number_prefix_disambiguates_names():
    with as_owner():
        from travel.geo.models import Airline

        Airline.objects.create(name="United Airways", iata="4H", icao="UBD", active=True)
    assert airline("United", "2000-01-01")[1] == "ambiguous_airline"
    assert airline("United", "2000-01-01", hint="UA") == ("United Airlines", "")


def test_aircraft():
    assert resolve_aircraft("B738").obj.name == "Boeing 737-800"
    assert resolve_aircraft("738").obj.name == "Boeing 737-800"
    assert resolve_aircraft("747-400").obj.name == "Boeing 747-400"
    unknown = resolve_aircraft("Zeppelin")
    assert unknown.obj is None and unknown.warnings and not unknown.problem
