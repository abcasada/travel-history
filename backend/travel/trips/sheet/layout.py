"""Finding a tab's blocks (§28.2): the optional trip block (label in A, value in B), the stops
table under the first row with a `Place` cell, and the legs table under the next row with
`From`, `To` and `Mode` cells. Column order is free; unknown columns are ignored."""

from __future__ import annotations

from dataclasses import dataclass, field

from .reader import Cell, RawTab, column_letter
from .values import header_name, is_blank

TRIP_FIELDS = ("title", "key", "start", "end", "purpose", "people", "tags", "visibility", "notes")

STOP_COLUMNS = {
    "stop": "label",
    "place": "place",
    "name": "name",
    "kind": "kind",
    "arrive": "arrive",
    "depart": "depart",
    "time zone": "tz",
    "timezone": "tz",
    "notes": "notes",
}
LEG_COLUMNS = {
    "leg": "label",
    "from": "from",
    "to": "to",
    "mode": "mode",
    "depart": "depart",
    "arrive": "arrive",
    "depart zone": "depart_tz",
    "arrive zone": "arrive_tz",
    "from airport": "from_airport",
    "to airport": "to_airport",
    "airline": "airline",
    "flight": "flight",
    "aircraft": "aircraft",
    "registration": "registration",
    "seat": "seat",
    "cabin": "cabin",
    "vehicle": "vehicle",
    "people": "people",
    "notes": "notes",
}


@dataclass
class Block:
    header_row: int
    columns: dict[str, int]  # field -> 0-based column
    headers: dict[str, str]  # field -> header as written
    rows: list[tuple[int, dict[str, Cell]]] = field(default_factory=list)  # non-blank rows
    unknown: list[str] = field(default_factory=list)  # other header texts

    def first_row(self) -> int | None:
        return self.rows[0][0] if self.rows else None

    def last_row(self) -> int | None:
        return self.rows[-1][0] if self.rows else None

    def letter(self, name: str) -> str:
        return column_letter(self.columns[name]) if name in self.columns else ""


@dataclass
class TripField:
    cell: Cell
    row: int


@dataclass
class Layout:
    trip: dict[str, TripField] = field(default_factory=dict)
    trip_unknown: list[tuple[int, str]] = field(default_factory=list)  # (row, label)
    trip_duplicates: list[tuple[int, str]] = field(default_factory=list)
    stops: Block | None = None
    legs: Block | None = None


def _names(cells: list[Cell]) -> list[str]:
    return [header_name(c.value) for c in cells]


def _block(row: int, cells: list[Cell], known: dict[str, str]) -> Block:
    columns: dict[str, int] = {}
    headers: dict[str, str] = {}
    unknown: list[str] = []
    for index, cell in enumerate(cells):
        name = header_name(cell.value)
        if not name:
            continue
        target = known.get(name)
        if target and target not in columns:
            columns[target] = index
            headers[target] = str(cell.value).strip()
        else:
            unknown.append(str(cell.value).strip())
    return Block(row, columns, headers, unknown=unknown)


def _fill(block: Block, rows: list[tuple[int, list[Cell]]]) -> None:
    for number, cells in rows:
        values = {
            name: cells[index] if index < len(cells) else Cell(None)
            for name, index in block.columns.items()
        }
        if all(is_blank(cell.value) for cell in values.values()):
            continue  # nothing in a known column: blank
        block.rows.append((number, values))


def find_blocks(tab: RawTab) -> Layout:
    rows = tab.rows
    stops_at = next((i for i, (_, cells) in enumerate(rows) if "place" in _names(cells)), None)
    search_from = stops_at + 1 if stops_at is not None else 0
    legs_at = next(
        (
            i
            for i, (_, cells) in enumerate(rows[search_from:], start=search_from)
            if {"from", "to", "mode"} <= set(_names(cells))
        ),
        None,
    )
    layout = Layout()
    first_header = min(i for i in (stops_at, legs_at, len(rows)) if i is not None)
    for number, cells in rows[:first_header]:
        label = header_name(cells[0].value) if cells else ""
        value = cells[1] if len(cells) > 1 else Cell(None)
        if not label:
            if any(not is_blank(c.value) for c in cells):
                layout.trip_unknown.append((number, ""))
            continue
        if label in TRIP_FIELDS:
            if label in layout.trip:
                layout.trip_duplicates.append((number, str(cells[0].value).strip()))
                continue
            layout.trip[label] = TripField(value, number)
        else:
            layout.trip_unknown.append((number, str(cells[0].value).strip()))
    if stops_at is not None:
        number, cells = rows[stops_at]
        layout.stops = _block(number, cells, STOP_COLUMNS)
        end = legs_at if legs_at is not None else len(rows)
        _fill(layout.stops, rows[stops_at + 1 : end])
    if legs_at is not None:
        number, cells = rows[legs_at]
        layout.legs = _block(number, cells, LEG_COLUMNS)
        _fill(layout.legs, rows[legs_at + 1 :])
    return layout
