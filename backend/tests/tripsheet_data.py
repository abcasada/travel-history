"""SYNTHETIC trip spreadsheets for the importer tests (docs/design/trip-sheet.md §28): invented
trips over fake gazetteer places (tests/fixtures/tripsheet/, tests/fixtures/geonames/) and the
public airport codes of tests/fixtures/flights/. Workbooks are built in memory; each carries the
SYNTHETIC marker on its Instructions tab."""

from __future__ import annotations

import io
from pathlib import Path

from openpyxl import Workbook

from tests.flight_data import load_reference
from tests.helpers import as_owner
from travel.geo import gazetteer as gaz

MARKER = "SYNTHETIC test workbook: invented trips, fake places, public airport codes"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

STOP_HEADER = ["Stop", "Place", "Name", "Kind", "Arrive", "Depart", "Time zone", "Notes"]
LEG_HEADER = [
    "Leg", "From", "To", "Mode", "Depart", "Arrive", "Depart zone", "Arrive zone",
    "From airport", "To airport", "Airline", "Flight", "Aircraft", "Registration", "Seat",
    "Cabin", "Vehicle", "People", "Notes",
]  # fmt: skip


def load_places() -> None:
    """Airports, airlines and aircraft (flight fixtures) plus the gazetteer subsets."""
    load_reference()
    with as_owner():
        gaz.load_countries(
            gaz.from_local_file(gaz.COUNTRIES, FIXTURES / "geonames" / "countryInfo.txt")
        )
        gaz.load_admin1(
            gaz.from_local_file(gaz.ADMIN1, FIXTURES / "geonames" / "admin1CodesASCII.txt")
        )
        gaz.load_cities(gaz.from_local_file(gaz.CITIES, FIXTURES / "geonames" / "cities500.txt"))
        gaz.load_cities(gaz.from_local_file(gaz.CITIES, FIXTURES / "tripsheet" / "cities500.txt"))
        gaz.copy_names()


def workbook(tabs: dict[str, list[list]], *, hidden: tuple[str, ...] = ()) -> bytes:
    wb = Workbook()
    wb.active.title = "Instructions"
    wb.active["A1"] = MARKER
    for name, rows in tabs.items():
        sheet = wb.create_sheet(name)
        if name in hidden:
            sheet.sheet_state = "hidden"
        for r, row in enumerate(rows, start=1):
            for c, value in enumerate(row, start=1):
                if value is not None and value != "":
                    sheet.cell(row=r, column=c, value=value)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def trip_tab(fields: dict, stops: list[list], legs: list[list]) -> list[list]:
    """Trip block, a blank row, the stops table, a blank row, the legs table. With F fields the
    stops header is row F+2 and the first stop row F+3."""
    rows: list[list] = [[label, value] for label, value in fields.items()]
    rows.append([])
    rows.append(STOP_HEADER)
    rows += stops
    rows.append([])
    rows.append(LEG_HEADER)
    rows += legs
    return rows


def leg(label="", origin=None, dest=None, mode="drive", depart="", arrive="", **extra) -> list:
    """A legs-table row; `extra` fills named columns (from_airport, flight, people, notes, ...)."""
    values = dict.fromkeys(LEG_HEADER, "")
    values.update({"Leg": label, "From": origin, "To": dest, "Mode": mode})
    values.update({"Depart": depart, "Arrive": arrive})
    names = {h.lower().replace(" ", "_"): h for h in LEG_HEADER}
    for key, value in extra.items():
        values[names[key]] = value
    return [values[h] for h in LEG_HEADER]


FIELDS = {
    "Title": "Synthetic loop",
    "Key": "synth-loop",
    "People": "me",
    "Tags": "road trip",
}
# With the four fields above: stops header row 6, stops rows 7-10, legs header row 12.
STOPS = [
    ["home", "Synthport, MO, US", "", "waypoint", "", "2015-06-12 06:30", "", ""],
    ["", "DEN", "", "waypoint", "2015-06-12 09:10", "2015-06-12 10:45", "", ""],
    [
        "springs", "Fernhill Synth, CO, US", "", "lodging", "2015-06-12 12:15",
        "2015-06-14 09:00", "", "SYNTHETIC note: cabin by the creek",
    ],
    ["", "35.0961, -106.6699", "Old Town Synth", "visit", "2015-06-19 10:15", "2015-06-19 15:00",
     "", ""],
]  # fmt: skip
LEGS = [
    leg("out", 7, 8, "flight", "2015-06-12 08:05", "2015-06-12 09:10",
        from_airport="MCI", flight="WN 1234", cabin="economy", seat="14c"),
    leg("", 8, "springs", "drive", "2015-06-12 10:45", "2015-06-12 12:15",
        notes="SYNTHETIC leg note"),
    leg("", "springs", 10, "drive", "2015-06-14 09:00", "2015-06-14 16:00"),
]  # fmt: skip


def example(fields=None, stops=None, legs=None) -> list[list]:
    return trip_tab(
        FIELDS if fields is None else fields,
        STOPS if stops is None else stops,
        LEGS if legs is None else legs,
    )
