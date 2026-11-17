"""Cell parsers for hand-kept flight spreadsheets (travel/flights/normalize.py). No database."""

import datetime as dt

import pytest

from travel.flights import normalize as n


@pytest.mark.parametrize(
    ("value", "iso", "precision"),
    [
        ("1998-03-14", "1998-03-14", "day"),
        ("1998-03-14T10:00:00Z", "1998-03-14", "day"),
        ("3/14/1998", "1998-03-14", "day"),
        ("03/04/1998", "1998-03-04", "day"),  # month first by default
        ("14.03.1998", "1998-03-14", "day"),  # dots are day first
        ("14/03/98", "1998-03-14", "day"),  # only one reading possible
        ("14 Mar 1998", "1998-03-14", "day"),
        ("March 14, 1998", "1998-03-14", "day"),
        ("14-Mar-98", "1998-03-14", "day"),
        ("19980314", "1998-03-14", "day"),
        ("1998-03", "1998-03", "month"),
        ("03/1998", "1998-03", "month"),
        ("March 1998", "1998-03", "month"),
        ("1998", "1998", "year"),
        (1998, "1998", "year"),
        (35868, "1998-03-14", "day"),  # Excel serial
        (dt.datetime(1998, 3, 14, 7, 5), "1998-03-14", "day"),
        (dt.date(1998, 3, 14), "1998-03-14", "day"),
    ],
)
def test_parse_date(value, iso, precision):
    parsed = n.parse_date(value)
    assert (parsed.iso(), parsed.precision) == (iso, precision)


def test_parse_date_dayfirst_and_ranges():
    assert n.parse_date("03/04/1998", dayfirst=True).iso() == "1998-04-03"
    assert n.parse_date("1998-02").end == dt.date(1998, 2, 28)
    assert n.parse_date("1998").end == dt.date(1998, 12, 31)
    assert n.parse_date("") is None and n.parse_date(None) is None


@pytest.mark.parametrize("value", ["31/31/2001", "yesterday", "1850-01-01", "2001-02-30"])
def test_parse_date_rejects(value):
    with pytest.raises(n.ValueProblem):
        n.parse_date(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("7:05 PM", dt.time(19, 5)),
        ("12:10 am", dt.time(0, 10)),
        ("19:05", dt.time(19, 5)),
        ("0705", dt.time(7, 5)),
        ("19:05:00", dt.time(19, 5)),
        (0.75, dt.time(18, 0)),
        (dt.time(6, 30), dt.time(6, 30)),
    ],
)
def test_parse_time(value, expected):
    assert n.parse_time(value) == expected


def test_parse_time_rejects():
    with pytest.raises(n.ValueProblem):
        n.parse_time("25:00")
    with pytest.raises(n.ValueProblem):
        n.parse_time("noon")


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("DEN", "DEN"),
        ("den", "DEN"),
        ("Denver (DEN)", "DEN"),
        ("DEN - Denver", "DEN"),
        ("DEN – Denver", "DEN"),
        ("KDEN", "KDEN"),
        ("Chicago", "Chicago"),
    ],
)
def test_airport_code(value, code):
    assert n.airport_code(value) == code


def test_split_route_and_flight_numbers():
    assert n.split_route("MCI-DEN") == ("MCI", "DEN")
    assert n.split_route("mci → den") == ("MCI", "DEN")
    assert n.split_route("MCI to DEN") == ("MCI", "DEN")
    assert n.split_route("Kansas City") is None
    assert n.split_flight_number("UA 123") == ("UA", "123")
    assert n.split_flight_number("baw12") == ("BAW", "12")
    assert n.split_flight_number("123") == ("", "123")
    assert n.split_flight_number("") == ("", "")


def test_cabin_seat_participants():
    assert n.cabin_class("Coach") == ("economy", True)
    assert n.cabin_class("First Class") == ("first", True)
    assert n.cabin_class("J") == ("business", True)
    assert n.cabin_class("Premium") == ("premium_economy", True)
    assert n.cabin_class("bunk") == ("other", False)
    assert n.seat_type("W") == "window"
    assert n.seat_type("Aisle seat") == "aisle"
    assert n.seat_type("") == ""
    assert n.participants("Pat Example & Sam Example; Lee") == [
        "Pat Example",
        "Sam Example",
        "Lee",
    ]
