"""Build docs/trips/trip-template.xlsx, the trip spreadsheet template (docs/design/trip-sheet.md,
§28). SYNTHETIC: the example trip is invented; it uses public city and airport names only.

Run in a throwaway container of the pinned Python image from backend/Dockerfile (nothing is
installed on the host):

    IMAGE=python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/repo" -w /repo "$IMAGE" \
        sh -c 'pip install -q --target /tmp/py openpyxl==3.1.5 &&
               PYTHONPATH=/tmp/py python scripts/make_trip_template.py'
"""

import datetime as dt
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

OUT = Path("docs/trips/trip-template.xlsx")
FIXED_TIME = dt.datetime(2026, 11, 18)  # stable document properties between rebuilds

BOLD = Font(bold=True)
TITLE = Font(bold=True, size=14)
HEADER_FILL = PatternFill("solid", fgColor="DCE6F1")
LEGS_FILL = PatternFill("solid", fgColor="E2EFDA")
TRIP_FILL = PatternFill("solid", fgColor="F2F2F2")
WRAP = Alignment(wrap_text=True, vertical="top")

TRIP_FIELDS = [
    ("Title", "Example: Colorado and New Mexico loop"),
    ("Key", "example-southwest-2015"),
    ("Start", "2015-06-12"),
    ("End", "2015-06-20"),
    ("Purpose", "Vacation"),
    ("People", "me; Pat Example"),
    ("Tags", "road trip; mountains"),
    ("Visibility", ""),
    ("Notes", "SYNTHETIC example data, not a real trip."),
]

STOP_HEADERS = ["Stop", "Place", "Name", "Kind", "Arrive", "Depart", "Time zone"]
# Rows 12-19 of the example tab (19 is a spare row). Labels are optional; legs may use the row
# number or the label.
STOPS = [
    ["home", "Kansas City, MO, US", "", "waypoint", "", "2015-06-12 06:30", "America/Chicago"],
    ["", "DEN", "", "waypoint", "2015-06-12 09:10", "2015-06-12 10:45", ""],
    [
        "springs",
        "Colorado Springs, CO, US",
        "",
        "lodging",
        "2015-06-12 12:15",
        "2015-06-14 09:00",
        "",
    ],
    ["", "Taos, NM, US", "", "visit", "2015-06-14 14:00", "2015-06-15 10:00", ""],
    ["", "Santa Fe, NM, US", "", "lodging", "2015-06-15 11:30", "2015-06-19 09:00", ""],
    [
        "",
        "35.0961, -106.6699",
        "Old Town Albuquerque",
        "visit",
        "2015-06-19 10:15",
        "2015-06-19 15:00",
        "",
    ],
    ["", "ABQ", "", "waypoint", "2015-06-19 15:30", "2015-06-20 08:00", ""],
    ["", "", "", "", "", "", ""],
]

LEG_HEADERS = [
    "Leg", "From", "To", "Mode", "Depart", "Arrive", "Depart zone", "Arrive zone",
    "From airport", "To airport", "Airline", "Flight", "Aircraft", "Registration", "Seat",
    "Cabin", "Vehicle", "People",
]  # fmt: skip
# Rows 23-29. From/To: a stop's row number (12-19) or its label. A flight may leave From or To
# empty when its airport column is filled (a connection airport needn't be a stop).
LEGS = [
    ["out", 12, 13, "flight", "2015-06-12 08:05", "2015-06-12 09:10", "", "",
     "MCI", "", "WN", "WN 1234", "B737", "", "14C", "economy", "", ""],
    ["", 13, "springs", "drive", "2015-06-12 10:45", "2015-06-12 12:15", "", "",
     "", "", "", "", "", "", "", "", "", ""],
    ["", "springs", 15, "drive", "2015-06-14 09:00", "2015-06-14 14:00", "", "",
     "", "", "", "", "", "", "", "", "", ""],
    ["", 15, 16, "drive", "2015-06-15 10:00", "2015-06-15 11:30", "", "",
     "", "", "", "", "", "", "", "", "", ""],
    ["", 16, 17, "drive", "2015-06-19 09:00", "2015-06-19 10:15", "", "",
     "", "", "", "", "", "", "", "", "", ""],
    ["", 17, 18, "drive", "2015-06-19 15:00", "2015-06-19 15:30", "", "",
     "", "", "", "", "", "", "", "", "", ""],
    ["back", 18, 12, "flight", "2015-06-20 08:00", "2015-06-20 11:05", "", "",
     "", "MCI", "WN", "WN 5678", "", "", "", "economy", "", "me"],
]  # fmt: skip

INSTRUCTIONS = [
    ("Trip spreadsheet template", None),
    ("SYNTHETIC template: the example tab is invented and uses public place names only.", None),
    ("", None),
    ("How it works", "h"),
    (
        "One tab = one trip. Tabs named Instructions, or starting with _ (like _Example), are "
        "skipped. Copy _Example, rename the copy (for example 2015 Colorado), and replace its "
        "contents.",
        None,
    ),
    (
        "Each trip tab has three blocks, top to bottom: the trip fields (a label in column A, its "
        "value in column B), the stops table, then the legs table. The importer finds the stops "
        "table by its header row (the row with a Place column) and the legs table by the second "
        "header row (the row with From, To and Mode). Any number of stop rows can sit between "
        "them; blank rows are fine.",
        None,
    ),
    (
        "Upload the file in the app (Import, Trip spreadsheet). Nothing is saved until you have "
        "seen the preview and pressed Import. Problems are listed by tab, row and column.",
        None,
    ),
    ("", None),
    ("Trip fields (column A label, column B value)", "h"),
    (
        "Title: required. Key: a short stable name for the trip; re-importing a tab with the same "
        "key updates that trip. If blank, the tab name is the key, so renaming the tab later makes "
        "a new trip. Start / End: YYYY-MM-DD (or YYYY-MM, YYYY); blank = from the stops and legs. "
        "Purpose: one of your purposes. People: names of people in the app, separated by ; (me = "
        "you). Tags: separated by ; (new tags are created). Visibility: private, participants or "
        "family; blank = the purpose's default. Notes: free text.",
        None,
    ),
    ("", None),
    ("Stops", "h"),
    (
        "Stop: optional label (must contain a letter), so legs can say springs instead of a row "
        "number. Place: a city (Santa Fe, NM, US; add region and country when a name is common), "
        "an airport code in capitals (DEN, KDEN), coordinates as lat, lon (35.0961, -106.6699), or "
        "geonames:<id>. A name that fits more than one place is reported with the choices; the "
        "importer never guesses. Name: optional display name. Kind: lodging, destination, visit or "
        "waypoint (blank = destination). Arrive / Depart: local time YYYY-MM-DD HH:MM, or a date "
        "only. Time zone: IANA name (America/Denver); blank = the place's own zone.",
        None,
    ),
    ("", None),
    ("Legs", "h"),
    (
        "From / To: the stop's row number as you see it on the left edge, or the stop's label. "
        "Inserting rows above a stop shifts its number, and typed numbers do not follow; use "
        "labels, or a formula such as =ROW(B14), which the spreadsheet updates for you. The "
        "preview shows every leg by stop names, so a stale number is easy to spot. Mode: drive, "
        "flight, train, bus, boat, walk, other. Depart / Arrive: local times as for stops; Depart "
        "zone / Arrive zone default to the stops' zones. Flights: From airport / To airport "
        "(needed when the stop is a city, optional when it is an airport; From or To may then be "
        "blank), Airline (code or name), Flight (WN 1234), Aircraft, Registration, Seat, Cabin "
        "(economy, premium_economy, business, first, other). Vehicle: a vehicle's nickname in the "
        "app. People: only when the leg's people differ from the trip's (names separated by ;).",
        None,
    ),
    ("", None),
    ("Importing again", "h"),
    (
        "Re-importing updates trips you have not changed in the app since the last import. A trip "
        "you edited in the app is never overwritten: the sheet's changes go to the review queue. "
        "A stop or leg missing from the sheet is never deleted just because it is missing. Your "
        "file is kept read-only on the server as the import's original.",
        None,
    ),
]


def instructions(ws) -> None:
    ws.title = "Instructions"
    ws.column_dimensions["A"].width = 110
    for row, (text, style) in enumerate(INSTRUCTIONS, start=1):
        cell = ws.cell(row=row, column=1, value=text or None)
        cell.alignment = WRAP
        if row == 1:
            cell.font = TITLE
        elif style == "h":
            cell.font = BOLD


def header(ws, row: int, names: list[str], fill: PatternFill) -> None:
    for col, name in enumerate(names, start=1):
        cell = ws.cell(row=row, column=col, value=name)
        cell.font = BOLD
        cell.fill = fill


def example(ws) -> None:
    ws.title = "_Example"
    for row, (label, value) in enumerate(TRIP_FIELDS, start=1):
        ws.cell(row=row, column=1, value=label).font = BOLD
        ws.cell(row=row, column=1).fill = TRIP_FILL
        ws.cell(row=row, column=2, value=value or None)

    stops_header = len(TRIP_FIELDS) + 2  # row 11
    header(ws, stops_header, STOP_HEADERS, HEADER_FILL)
    for offset, values in enumerate(STOPS, start=1):
        for col, value in enumerate(values, start=1):
            if value != "":
                ws.cell(row=stops_header + offset, column=col, value=value)

    legs_header = stops_header + len(STOPS) + 3  # row 22: two spare rows above it
    header(ws, legs_header, LEG_HEADERS, LEGS_FILL)
    for offset, values in enumerate(LEGS, start=1):
        for col, value in enumerate(values, start=1):
            if value != "":
                ws.cell(row=legs_header + offset, column=col, value=value)

    # Drop-downs; the spreadsheet stretches the ranges when rows are inserted inside them.
    first_stop, last_stop = stops_header + 1, legs_header - 1
    first_leg, last_leg = legs_header + 1, legs_header + 200
    for formula, col, lo, hi in [
        ('"lodging,destination,visit,waypoint"', "D", first_stop, last_stop),
        ('"drive,flight,train,bus,boat,walk,other"', "D", first_leg, last_leg),
        ('"economy,premium_economy,business,first,other"', "P", first_leg, last_leg),
    ]:
        dv = DataValidation(type="list", formula1=formula, allow_blank=True)
        dv.add(f"{col}{lo}:{col}{hi}")
        ws.add_data_validation(dv)
    dv = DataValidation(type="list", formula1='"private,participants,family"', allow_blank=True)
    dv.add("B8")
    ws.add_data_validation(dv)

    widths = [12, 26, 22, 12, 17, 17, 16, 14, 12, 10, 8, 10, 9, 12, 6, 16, 10, 16]
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.column_dimensions["B"].width = 38  # trip field values share column B with Place


def main() -> None:
    wb = Workbook()
    instructions(wb.active)
    example(wb.create_sheet())
    wb.properties.title = "Trip spreadsheet template (SYNTHETIC example)"
    wb.properties.creator = "travel-history"
    wb.properties.lastModifiedBy = "travel-history"
    wb.properties.created = FIXED_TIME
    wb.properties.modified = FIXED_TIME
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
