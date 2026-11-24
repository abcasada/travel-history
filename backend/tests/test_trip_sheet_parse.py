"""Trip spreadsheet parsing (item 14c-1, docs/design/trip-sheet.md §28.1-§28.7) on SYNTHETIC
workbooks: limits and safe XML, finding the blocks, cell values, places (never guessed), zones,
stop references and the issue report. Parsing never writes trips."""

import datetime as dt
import io
import zipfile

import pytest

from tests.factories import PersonFactory, UserFactory, user_with_person
from tests.helpers import as_owner
from tests.tripsheet_data import LEGS, STOPS, example, leg, load_places, trip_tab, workbook
from travel.core.rls import rls_context
from travel.trips.models import Purpose, Trip
from travel.trips.sheet import reader
from travel.trips.sheet import values as v
from travel.trips.sheet.parse import parse_workbook
from travel.trips.sheet.reader import SheetFileError

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def places():
    load_places()


@pytest.fixture
def alice():
    with as_owner():
        user = user_with_person(display_name="Alice Synth")
        Purpose.objects.create(owner=user, name="Vacation")
        PersonFactory(created_by=user, display_name="Pat Example")
    return user


def parse(user, tabs, **kwargs):
    with rls_context(user.pk):
        return parse_workbook(workbook(tabs, **kwargs), user)


def one(user, rows):
    tabs = parse(user, {"2015 Loop": rows}).tabs
    assert len(tabs) == 1
    return tabs[0]


def issues(tab, severity=None):
    return [
        (i.row, i.column, i.reason)
        for i in tab.issues
        if severity is None or i.severity == severity
    ]


# --- values ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cell", "fmt", "expected"),
    [
        ("2015-06-12 08:05", "", (dt.datetime(2015, 6, 12, 8, 5), "exact")),
        ("2015-06-12T08:05:30", "", (dt.datetime(2015, 6, 12, 8, 5, 30), "exact")),
        ("2015-06-12", "", (dt.datetime(2015, 6, 12), "day")),
        ("2015-06", "", (dt.datetime(2015, 6, 1), "month")),
        ("2015", "", (dt.datetime(2015, 1, 1), "year")),
        ("14 Mar 2015 7:05 PM", "", (dt.datetime(2015, 3, 14, 19, 5), "exact")),
        ("3/14/2015", "", (dt.datetime(2015, 3, 14), "day")),
        (dt.datetime(2015, 6, 12, 8, 5), "yyyy-mm-dd h:mm", (dt.datetime(2015, 6, 12, 8, 5), "exact")),
        (dt.datetime(2015, 6, 12), "yyyy-mm-dd", (dt.datetime(2015, 6, 12), "day")),
        (dt.date(2015, 6, 12), "", (dt.datetime(2015, 6, 12), "day")),
    ],
)  # fmt: skip
def test_local_times(cell, fmt, expected):
    value = v.local_time(cell, fmt)
    assert (value.value, value.precision) == expected


@pytest.mark.parametrize(
    ("cell", "reason"),
    [("3/4/2015", "ambiguous_date"), ("2015-13-01", "bad_date"), ("next week", "bad_date"),
     (dt.time(7, 5), "bad_time"), ("2015-06 07:00", "bad_time")],
)  # fmt: skip
def test_unreadable_times(cell, reason):
    with pytest.raises(v.CellProblem) as raised:
        v.local_time(cell)
    assert raised.value.reason == reason


def test_times_are_never_guessed_across_dst():
    gap = v.local_time("2015-03-08 02:30")
    with pytest.raises(v.CellProblem) as raised:
        v.to_utc(gap, "America/Chicago")
    assert raised.value.reason == "nonexistent_time"
    repeated = v.local_time("2015-11-01 01:30")
    with pytest.raises(v.CellProblem) as raised:
        v.to_utc(repeated, "America/Chicago")
    assert raised.value.reason == "ambiguous_time"
    assert raised.value.candidates == ["2015-11-01 01:30 -05:00", "2015-11-01 01:30 -06:00"]
    settled = v.local_time("2015-11-01 01:30 -06:00")
    assert v.to_utc(settled, "America/Chicago") == dt.datetime(2015, 11, 1, 7, 30, tzinfo=dt.UTC)
    day = v.local_time("2015-06-12")
    assert v.to_utc(day, "America/Denver") == dt.datetime(2015, 6, 12, 6, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("cell", "expected"),
    [(14, v.StopRef(row=14)), (14.0, v.StopRef(row=14)), ("14", v.StopRef(row=14)),
     ("=ROW(B14)", v.StopRef(row=14)), ("=B14", v.StopRef(row=14)), ("=$A$14", v.StopRef(row=14)),
     ("Springs", v.StopRef(label="springs")), ("", None)],
)  # fmt: skip
def test_stop_references(cell, expected):
    assert v.stop_ref(cell) == expected


def test_labels_need_a_letter():
    with pytest.raises(v.CellProblem):
        v.stop_label("12")
    assert v.stop_label("stop 2") == "stop 2"


# --- the file ----------------------------------------------------------------------------------


def test_openpyxl_parses_xml_through_defusedxml():
    assert reader.defused_xml_active()


def test_not_an_xlsx_file():
    with pytest.raises(SheetFileError) as raised:
        reader.read_tabs(b"SYNTHETIC,csv\n1,2\n")
    assert raised.value.reason == "bad_file"


def test_size_and_archive_limits(monkeypatch):
    data = workbook({"Trip": example()})
    monkeypatch.setattr(reader, "MAX_FILE_BYTES", len(data) - 1)
    with pytest.raises(SheetFileError) as raised:
        reader.read_tabs(data)
    assert raised.value.reason == "too_large"
    monkeypatch.undo()
    # A small archive that unpacks to more than the limit (a zip bomb) is refused before
    # openpyxl reads it.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/bomb.xml", b"\0" * (2 * 1024 * 1024))
    monkeypatch.setattr(reader, "MAX_UNCOMPRESSED_BYTES", 1024 * 1024)
    with pytest.raises(SheetFileError) as raised:
        reader.read_tabs(buffer.getvalue())
    assert raised.value.reason == "too_large"


def test_skipped_and_hidden_tabs(alice):
    tabs = parse(
        alice,
        {"_Example": example(), "instructions ": example(), "Hidden trip": example()},
        hidden=("Hidden trip",),
    ).tabs
    assert [t.name for t in tabs] == ["Hidden trip"]  # hiding is a view setting


def test_trip_tab_limit(alice, monkeypatch):
    monkeypatch.setattr(reader, "MAX_TRIP_TABS", 1)
    rows = example(fields={"Title": "x"})
    parsed = parse(alice, {"One": rows, "Two": rows})
    assert [t.name for t in parsed.tabs] == ["One"]
    assert parsed.issues[0]["reason"] == "too_large"


def test_rows_beyond_the_limit_block_the_tab(alice, monkeypatch):
    monkeypatch.setattr(reader, "MAX_ROWS", 12)
    tab = one(alice, example())
    assert ("problem", "too_large") in [(i.severity, i.reason) for i in tab.issues]


# --- blocks and values -------------------------------------------------------------------------


def test_example_tab(alice):
    tab = one(alice, example())
    assert issues(tab, "problem") == []
    assert tab.key == "synth-loop" and tab.title == "Synthetic loop"
    trip = tab.content["trip"]
    assert (trip["start_date"], trip["end_date"]) == ("2015-06-12", "2015-06-19")
    assert trip["people"] == [{"name": "Alice Synth", "person_id": alice.person_id}]
    assert trip["new_tags"] == ["road trip"]
    home, den, springs, old_town = tab.content["stops"]
    assert home["sheet_key"] == "label:home" and home["tz"] == "America/Chicago"
    assert home["place"]["geonames_id"] == 9100101
    assert den["place"]["kind"] == "airport" and den["place"]["airport_code"] == "DEN"
    assert den["tz"] == "America/Denver"  # from the nearest gazetteer place
    assert den["arrive_utc"] == "2015-06-12T15:10:00+00:00"
    assert springs["notes"] == "SYNTHETIC note: cabin by the creek"
    assert old_town["name"] == "Old Town Synth" and old_town["tz"] == "America/Denver"
    out, drive, _ = tab.content["legs"]
    assert out["sheet_key"] == "label:out"
    assert out["origin_airport_id"] is not None and out["destination_airport_id"] is not None
    assert (out["flight_number"], out["seat"], out["cabin_class"]) == ("WN1234", "14C", "economy")
    assert out["airline_id"] is not None
    assert out["start_utc"] == "2015-06-12T13:05:00+00:00"  # 08:05 in Kansas City
    assert drive["origin_key"] == den["sheet_key"] and drive["destination_key"] == "label:springs"
    assert drive["notes"] == "SYNTHETIC leg note"
    assert ("info", "zone_from_nearest") in [(i.severity, i.reason) for i in tab.issues]


def test_headers_in_any_order_without_a_trip_block(alice):
    rows = [
        ["notes:", "PLACE*", "  Kind ", "Cost"],
        ["", "Synthville, KS", "", "12"],
        [],
        ["Mode", "To", "From"],
        ["walk", 2, 2],
    ]
    tab = one(alice, rows)
    assert tab.key == "2015 loop" and tab.title == "2015 Loop"
    assert tab.content["stops"][0]["place"]["geonames_id"] == 9000001
    assert ("info", "ignored_columns") in [(i.severity, i.reason) for i in tab.issues]
    assert ("problem", "no_dates") in [(i.severity, i.reason) for i in tab.issues]


def test_dates_from_fields(alice):
    tab = one(alice, example(fields={"Title": "x", "Start": "2015-06", "End": "2015-07"}))
    trip = tab.content["trip"]
    assert (trip["start_date"], trip["end_date"], trip["date_precision"]) == (
        "2015-06-01", "2015-07-31", "month",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("place", "reason"),
    [("Paristown", "ambiguous_place"), ("Nowhere Synth", "unknown_place"),
     ("91, 10", "bad_value"), ("geonames:1", "unknown_place"), ("ZZZ", "unknown_airport")],
)  # fmt: skip
def test_places_are_never_guessed(alice, place, reason):
    stops = [["", place, "", "", "2015-06-12", "", "", ""]]
    tab = one(alice, trip_tab({"Title": "x"}, stops, []))
    assert (4, "B", reason) in issues(tab, "problem")


def test_ambiguous_place_lists_text_that_picks_each(alice):
    stops = [["", "Paristown", "", "", "2015-06-12", "", "", ""]]
    tab = one(alice, trip_tab({"Title": "x"}, stops, []))
    problem = next(i for i in tab.issues if i.reason == "ambiguous_place")
    assert problem.candidates == ["Paristown, 02, XS", "Paristown, TX, US"]
    # Each candidate text resolves to exactly one place.
    for text in problem.candidates:
        picked = one(alice, trip_tab({"Title": "x"}, [["", text, "", "", "2015-06-12"]], []))
        assert issues(picked, "problem") == []


def test_place_forms(alice):
    stops = [
        ["", "zurichsee synth", "", "", "2015-06-12"],
        ["", "Twin Synth, NE", "", "", "2015-06-12"],
        ["", "geonames:9000004", "", "", "2015-06-12"],
        ["", "airport:mci", "", "", "2015-06-12"],
        ["", "39.1; -104.85", "", "", "2015-06-12"],
    ]
    tab = one(alice, trip_tab({"Title": "x"}, stops, []))
    assert issues(tab, "problem") == []
    places = [s["place"] for s in tab.content["stops"]]
    assert places[0]["geonames_id"] == 9000005 and places[0]["tz"] == "Europe/Zurich"
    assert places[1]["geonames_id"] == 9100105
    assert places[2]["geonames_id"] == 9000004
    assert places[3]["airport_code"] == "MCI"
    assert places[4]["kind"] == "coordinates"
    assert tab.content["stops"][4]["tz"] == "America/Denver"


def test_unknown_zone_needs_a_time_zone(alice):
    stops = [["", "10.5, 10.5", "Sea Synth", "", "2015-06-12 10:00", "", "", ""]]
    tab = one(alice, trip_tab({"Title": "x"}, stops, []))
    assert (4, "G", "unknown_zone") in issues(tab, "problem")
    stops[0][6] = "Africa/Lagos"
    tab = one(alice, trip_tab({"Title": "x"}, stops, []))
    assert issues(tab, "problem") == []


def test_stop_and_leg_problems(alice):
    stops = [
        ["a", "Synthville, KS", "", "hotel", "2015-06-12", "", "", ""],
        ["A", "Fakeburg", "", "", "2015-06-12 10:00", "2015-06-12 09:00", "", ""],
    ]
    legs = [
        leg("", 4, 31, "drive", "2015-06-12 08:00"),
        leg("", "nowhere", 4, "spaceship"),
        leg("", 4, 5, "flight", "2015-06-12 08:00"),
        leg("", 4, 5, "drive", "2015-06-12 09:00", "2015-06-12 08:00"),
    ]
    tab = one(alice, trip_tab({"Title": "x"}, stops, legs))
    problems = issues(tab, "problem")
    assert (4, "D", "bad_value") in problems  # kind "hotel"
    assert (5, "A", "duplicate_label") in problems
    assert (5, "F", "end_before_start") in problems
    assert (8, "C", "bad_reference") in problems
    message = next(i.message for i in tab.issues if i.row == 8 and i.reason == "bad_reference")
    assert message == "row 31 is not a stop; stops are rows 4-5"
    assert (9, "B", "bad_reference") in problems and (9, "D", "bad_value") in problems
    assert (10, "I", "missing_airport") in problems and (10, "J", "missing_airport") in problems
    assert (11, "F", "end_before_start") in problems


def test_chain_warnings(alice):
    legs = [
        leg("", 7, 8, "drive", "2015-06-12 07:00", "2015-06-12 09:00"),
        leg("", 9, 10, "drive", "2015-06-12 05:00", "2015-06-12 20:00"),
        leg("", 9, 9, "flight", "2015-06-13 06:00", "2015-06-13 07:00"),
    ]
    tab = one(alice, example(legs=legs))
    warnings = [(i.row, i.reason) for i in tab.issues if i.severity == "warning"]
    assert (14, "broken_chain") in warnings
    assert (14, "out_of_order") in warnings
    assert (14, "time_mismatch") in warnings  # departs before arriving at row 9
    assert (15, "short_flight") in warnings


def test_trip_fields(alice):
    fields = {
        "Title": "x",
        "Purpose": "vacation",
        "People": "me; Pat Example; Nobody Synth",
        "Visibility": "public",
    }
    tab = one(alice, example(fields=fields))
    problems = {(i.reason, i.field) for i in tab.issues if i.severity == "problem"}
    assert problems == {("unknown_person", "people"), ("bad_value", "visibility")}
    assert tab.content["unknown_people"] == ["Nobody Synth"]
    unknown = next(i for i in tab.issues if i.reason == "unknown_person")
    assert unknown.candidates == ["Nobody Synth"]  # the name 'create these people' would add
    assert tab.content["trip"]["purpose"] == "Vacation"
    tab = one(alice, example(fields={"Title": "x", "Colour": "blue", "People": "me", "Tags": ""}))
    assert [(i.row, i.severity, i.reason) for i in tab.issues if i.column == "A"] == [
        (2, "warning", "bad_value")
    ]
    tab = one(alice, example(fields={"Title": "x", "Purpose": "Work"}))
    assert ("unknown_purpose", "purpose") in {(i.reason, i.field) for i in tab.issues}


def test_me_without_a_person(alice):
    with as_owner():
        user = UserFactory()
    tab = one(user, example(fields={"Title": "x", "People": "me"}))
    problem = next(i for i in tab.issues if i.reason == "unknown_person")
    assert problem.candidates == []  # can't be created: "Add me" first
    assert tab.content["unknown_people"] == []


def test_duplicate_keys_block_both_tabs(alice):
    rows = example(fields={"Title": "x", "Key": "Same  KEY"})
    parsed = parse(alice, {"One": rows, "Two": example(fields={"Key": "same key"})})
    for tab in parsed.tabs:
        assert ("duplicate_key", "problem") in [(i.reason, i.severity) for i in tab.issues]


def test_sheet_keys_without_labels_count_occurrences(alice):
    stops = [
        ["", "Synthville, KS", "", "", "2015-06-12"],
        ["", "Synthville, KS", "", "", "2015-06-12"],
    ]
    legs = [leg("", 4, 5, "drive", "2015-06-12 10:00"), leg("", 4, 5, "drive", "2015-06-12 11:00")]
    tab = one(alice, trip_tab({"Title": "x"}, stops, legs))
    keys = [s["sheet_key"] for s in tab.content["stops"]] + [
        leg["sheet_key"] for leg in tab.content["legs"]
    ]
    assert len(set(keys)) == 4
    assert keys[0].endswith("#1") and keys[1].endswith("#2")


def test_hash_ignores_row_numbers(alice):
    stops = [["a", "Synthville, KS", "", "", "2015-06-12"], ["b", "Fakeburg", "", "", "2015-06-13"]]
    legs = [leg("", "a", "b", "drive", "2015-06-13 10:00")]
    first = one(alice, trip_tab({"Title": "x"}, stops, legs))
    shifted = one(alice, trip_tab({"Title": "x", "Notes": ""}, stops, legs))
    assert first.content["stops"][0]["row"] != shifted.content["stops"][0]["row"]
    assert first.content_hash == shifted.content_hash
    changed = one(alice, trip_tab({"Title": "Other"}, stops, legs))
    assert changed.content_hash != first.content_hash


def test_parsing_writes_no_trips(alice):
    parse(alice, {"Trip": example()})
    with as_owner():
        assert not Trip.objects.exists()


def test_formula_references(alice):
    legs = [leg("", "=ROW(B7)", "=B8", "drive", "2015-06-12 06:30", "2015-06-12 09:00")]
    tab = one(alice, example(legs=legs))
    assert tab.content["legs"][0]["origin_key"] == "label:home"
    assert tab.content["legs"][0]["destination_row"] == 8
    assert len(STOPS) == 4 and len(LEGS) == 3
