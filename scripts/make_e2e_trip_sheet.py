"""Build e2e/fixtures/trip-sheet-synthetic.xlsx, the trip spreadsheet `./dev e2e` uploads and
commits (work-order item 14c-2). SYNTHETIC: an invented two-stop trip at typed coordinates in
Kansas (public city-centre points), one known person (`me`, made by the catalog step's Add me)
and one unknown person, so the preview offers "create these people".

Run in a throwaway container of the pinned Python image from backend/Dockerfile (nothing is
installed on the host):

    IMAGE=python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/repo" -w /repo "$IMAGE" \
        sh -c 'pip install -q --target /tmp/py openpyxl==3.1.5 &&
               PYTHONPATH=/tmp/py python scripts/make_e2e_trip_sheet.py'
"""

import datetime as dt
from pathlib import Path

from openpyxl import Workbook

OUT = Path("e2e/fixtures/trip-sheet-synthetic.xlsx")
FIXED_TIME = dt.datetime(2026, 11, 24)  # stable document properties between rebuilds
TAB = "E2E sheet trip"

TRIP = [
    ("Title", "E2E sheet trip"),
    ("Key", "e2e-sheet-trip"),
    ("Start", "2023-04-10"),
    ("End", "2023-04-12"),
    ("People", "me; E2E Sheet Cousin"),
    ("Tags", "e2e"),
    ("Notes", "SYNTHETIC e2e fixture, not a real trip."),
]
STOP_HEADERS = ["Stop", "Place", "Name", "Kind", "Arrive", "Depart", "Time zone"]
STOPS = [
    ["start", "37.6922, -97.3375", "E2E Sheet Start", "waypoint", "", "2023-04-10 08:00",
     "America/Chicago"],
    ["lake", "38.8403, -97.6114", "E2E Sheet Lake", "lodging", "2023-04-10 10:00",
     "2023-04-12 09:00", "America/Chicago"],
]  # fmt: skip
LEG_HEADERS = ["Leg", "From", "To", "Mode", "Depart", "Arrive"]
LEGS = [
    ["out", "start", "lake", "drive", "2023-04-10 08:00", "2023-04-10 10:00"],
    ["back", "lake", "start", "drive", "2023-04-12 09:00", "2023-04-12 11:00"],
]


def main() -> None:
    book = Workbook()
    notes = book.active
    notes.title = "Instructions"
    notes["A1"] = "SYNTHETIC e2e fixture: an invented trip; public city-centre points only."
    sheet = book.create_sheet(TAB)
    for label, value in TRIP:
        sheet.append([label, value])
    sheet.append([])
    sheet.append(STOP_HEADERS)
    for row in STOPS:
        sheet.append(row)
    sheet.append([])
    sheet.append(LEG_HEADERS)
    for row in LEGS:
        sheet.append(row)
    book.properties.creator = "SYNTHETIC"
    book.properties.title = "SYNTHETIC e2e trip sheet"
    book.properties.created = FIXED_TIME
    book.properties.modified = FIXED_TIME
    OUT.parent.mkdir(parents=True, exist_ok=True)
    book.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
