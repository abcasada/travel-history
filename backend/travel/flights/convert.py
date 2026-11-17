"""Spreadsheet → flight template conversion (PLAN.md §12.3, milestone 3.2).

Reads a hand-kept flight list (CSV or XLSX), finds the header row and maps its columns to the
template by name (a mapping YAML is written next to the file on the first run; edit it and run
again to correct the guess), normalises every cell, resolves the codes by flight date, and
writes the converted template plus an unmatched report. The input file is only ever read.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .normalize import text
from .template import COLUMNS, REASONS, ProcessedRow, process_row

HEADER_SCAN_ROWS = 25
TARGETS = [*COLUMNS, "route"]

SYNONYMS = {
    "trip_key": ["trip", "trip key", "trip id", "trip name", "journey", "trip no"],
    "date": [
        "date",
        "flight date",
        "departure date",
        "dep date",
        "dept date",
        "date of flight",
        "day",
        "when",
        "travel date",
        "date flown",
        "flown",
        "year",
    ],
    "dep_time": [
        "dep time",
        "departure time",
        "departs",
        "depart",
        "std",
        "time dep",
        "takeoff",
        "take off",
        "dept time",
        "time",
        "etd",
        "out",
    ],
    "arr_time": [
        "arr time",
        "arrival time",
        "arrives",
        "arrive",
        "sta",
        "landing",
        "landed",
        "eta",
        "time arr",
        "in",
    ],
    "arr_date": ["arr date", "arrival date", "date arrived", "landing date"],
    "from": [
        "from",
        "origin",
        "orig",
        "dep",
        "dept",
        "departure",
        "departure airport",
        "from airport",
        "dep airport",
        "departure city",
        "from city",
        "leaving from",
        "depart from",
    ],
    "to": [
        "to",
        "destination",
        "dest",
        "arr",
        "arrival",
        "arrival airport",
        "to airport",
        "arr airport",
        "arrival city",
        "to city",
        "going to",
        "arrive at",
    ],
    "route": ["route", "routing", "sector", "segment", "from to", "city pair", "leg", "from/to"],
    "airline": [
        "airline",
        "carrier",
        "operator",
        "airline name",
        "operated by",
        "company",
        "airlines",
    ],
    "flight_number": [
        "flight",
        "flight number",
        "flight no",
        "flight num",
        "flight #",
        "flt",
        "flt no",
        "flight code",
    ],
    "aircraft": [
        "aircraft",
        "plane",
        "aircraft type",
        "equipment",
        "equip",
        "type",
        "plane type",
        "model",
        "airplane",
    ],
    "registration": [
        "registration",
        "reg",
        "tail",
        "tail number",
        "tail no",
        "aircraft registration",
    ],
    "seat": ["seat", "seat number", "seat no", "seat #"],
    "cabin_class": [
        "class",
        "cabin",
        "cabin class",
        "fare class",
        "travel class",
        "service class",
    ],
    "seat_type": ["seat type", "window aisle", "window/aisle", "seat position", "position"],
    "purpose": ["purpose", "reason", "trip reason", "flight reason", "why", "business leisure"],
    "notes": ["notes", "note", "comments", "comment", "remarks", "memo", "description"],
    "participants": [
        "participants",
        "with",
        "travelers",
        "travellers",
        "passengers",
        "people",
        "companions",
        "who",
        "traveling with",
        "travelling with",
        "pax",
        "names",
    ],
}


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


LOOKUP = {_key(name): target for target, names in SYNONYMS.items() for name in names}


def guess(header: str) -> str | None:
    key = _key(header)
    if not key:
        return None
    if key in LOOKUP:
        return LOOKUP[key]
    words = set(re.findall(r"[a-z]+", header.lower()))
    arrival = bool(words & {"arr", "arrival", "arrive", "arrives", "landing", "landed", "to"})
    departure = bool(words & {"dep", "dept", "departure", "depart", "departs", "from"})
    if "date" in words:
        return "arr_date" if arrival and not departure else "date"
    if "time" in words:
        return "arr_time" if arrival and not departure else "dep_time"
    if words & {"airport", "city", "iata", "code"}:
        if arrival:
            return "to"
        if departure:
            return "from"
    if "flight" in words and words & {"number", "no", "num", "nr"}:
        return "flight_number"
    if words & {"airline", "carrier"}:
        return "airline"
    if words & {"aircraft", "plane", "equipment"}:
        return "aircraft"
    if words & {"note", "notes", "comment", "comments", "remarks"}:
        return "notes"
    return None


# --- Reading --------------------------------------------------------------------------------


@dataclass
class Table:
    sheet: str
    rows: list[list[Any]]


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("unreadable text encoding")


def read_tables(path: Path) -> list[Table]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            return [
                Table(sheet.title, [list(row) for row in sheet.iter_rows(values_only=True)])
                for sheet in workbook.worksheets
            ]
        finally:
            workbook.close()
    if suffix == ".xls":
        raise ValueError("old .xls files aren't supported: save the sheet as .xlsx or .csv")
    content = _decode(path.read_bytes())
    sample = content[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [Table("", [list(row) for row in csv.reader(io.StringIO(content), dialect)])]


# --- Mapping --------------------------------------------------------------------------------


@dataclass
class Mapping:
    sheet: str
    header_row: int  # 1-based
    columns: dict[str, str]  # template column → source header
    append_to_notes: list[str] = field(default_factory=list)
    dayfirst: bool = False
    unused: list[str] = field(default_factory=list)

    def dump(self, source_name: str) -> str:
        body = yaml.safe_dump(
            {
                "source": source_name,
                "sheet": self.sheet,
                "header_row": self.header_row,
                "dayfirst": self.dayfirst,
                "columns": self.columns,
                "append_to_notes": self.append_to_notes,
                "unused": self.unused,
            },
            sort_keys=False,
            allow_unicode=True,
        )
        return (
            "# Column mapping for flights_convert (docs/flights/README.md). Edit it and run the\n"
            "# converter again; delete it to guess again. Template columns: "
            + ", ".join(TARGETS)
            + ".\n# dayfirst: true reads 03/04/1998 as 3 April. Columns under append_to_notes\n"
            "# are copied into notes as 'Header: value'; unused columns are ignored.\n" + body
        )

    @classmethod
    def load(cls, path: Path) -> Mapping:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        columns = {str(k): str(v) for k, v in (data.get("columns") or {}).items() if v}
        unknown = sorted(set(columns) - set(TARGETS))
        if unknown:
            raise ValueError(f"{path.name}: unknown template column(s) {', '.join(unknown)}")
        return cls(
            sheet=str(data.get("sheet") or ""),
            header_row=int(data.get("header_row") or 1),
            columns=columns,
            append_to_notes=[str(c) for c in data.get("append_to_notes") or []],
            dayfirst=bool(data.get("dayfirst")),
            unused=[str(c) for c in data.get("unused") or []],
        )


def _header_mapping(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    columns: dict[str, str] = {}
    leftover = []
    for header in headers:
        if not header:
            continue
        target = guess(header)
        if target and target not in columns:
            columns[target] = header
        else:
            leftover.append(header)
    return columns, leftover


def _score(columns: dict[str, str]) -> int:
    essential = ("date" in columns) + (
        ("from" in columns and "to" in columns) or "route" in columns
    )
    return essential * 10 + len(columns)


def detect(tables: list[Table]) -> Mapping:
    best: tuple[int, Mapping] | None = None
    for table in tables:
        for index, row in enumerate(table.rows[:HEADER_SCAN_ROWS]):
            headers = [text(cell) for cell in row]
            columns, leftover = _header_mapping(headers)
            score = _score(columns)
            if score >= 12 and (best is None or score > best[0]):
                best = (score, Mapping(table.sheet, index + 1, columns, append_to_notes=leftover))
    if best is None:
        raise ValueError(
            "couldn't find a header row with a date and from/to (or route) column; "
            "write the mapping file by hand (see docs/flights/README.md)"
        )
    return best[1]


# --- Conversion -----------------------------------------------------------------------------


@dataclass
class Result:
    rows: list[ProcessedRow]
    skipped_blank: int
    mapping: Mapping


def convert_rows(tables: list[Table], mapping: Mapping) -> Result:
    table = next((t for t in tables if t.sheet == mapping.sheet), None) or tables[0]
    header = [text(cell) for cell in table.rows[mapping.header_row - 1]]
    position = {name: i for i, name in reversed(list(enumerate(header))) if name}
    missing = [
        h for h in [*mapping.columns.values(), *mapping.append_to_notes] if h not in position
    ]
    if missing:
        raise ValueError(f"column(s) not found in the header row: {', '.join(missing)}")
    rows: list[ProcessedRow] = []
    blank = 0
    for offset, cells in enumerate(table.rows[mapping.header_row :]):
        number = mapping.header_row + offset + 1

        def cell(name: str, cells=cells):
            i = position[name]
            return cells[i] if i < len(cells) else None

        raw = {target: cell(source) for target, source in mapping.columns.items()}
        if not any(text(value) for value in raw.values()):
            blank += 1
            continue
        extra = [
            f"{name}: {text(cell(name))}" for name in mapping.append_to_notes if text(cell(name))
        ]
        if extra:
            raw["notes"] = "; ".join(filter(None, [text(raw.get("notes")), *extra]))
        rows.append(process_row(raw, number, dayfirst=mapping.dayfirst))
    return Result(rows, blank, mapping)


def output_paths(source: Path) -> dict[str, Path]:
    stem = source.with_suffix("")
    return {
        "mapping": Path(f"{stem}.mapping.yaml"),
        "template": Path(f"{stem}.template.csv"),
        "unmatched": Path(f"{stem}.unmatched.csv"),
    }


def write_template(rows: list[ProcessedRow], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.values)


REPORT_COLUMNS = [
    "source_row",
    "kind",
    "field",
    "reason",
    "explanation",
    "detail",
    "date",
    "from",
    "to",
    "airline",
    "flight_number",
]


def write_report(rows: list[ProcessedRow], path: Path) -> int:
    """One line per problem (and per warning, marked as such). Returns the problem count."""
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for row in rows:
            for kind, issues in (("problem", row.problems), ("warning", row.warnings)):
                for issue in issues:
                    count += kind == "problem"
                    writer.writerow(
                        {
                            "source_row": row.row_number,
                            "kind": kind,
                            "field": issue.field,
                            "reason": issue.reason,
                            "explanation": REASONS.get(issue.reason, ""),
                            "detail": issue.detail,
                            **{k: row.values[k] for k in REPORT_COLUMNS[6:]},
                        }
                    )
    return count


def convert_file(source: Path, *, redetect: bool = False) -> tuple[Result, dict[str, Path], bool]:
    """Convert `source`; returns the result, the paths written, and whether the mapping was
    newly guessed. Never writes to `source`."""
    paths = output_paths(source)
    if source.resolve() in {p.resolve() for p in paths.values()}:
        raise ValueError("refusing to overwrite the input file")
    tables = read_tables(source)
    guessed = redetect or not paths["mapping"].exists()
    mapping = detect(tables) if guessed else Mapping.load(paths["mapping"])
    if guessed:
        paths["mapping"].write_text(mapping.dump(source.name), encoding="utf-8")
    result = convert_rows(tables, mapping)
    write_template(result.rows, paths["template"])
    write_report(result.rows, paths["unmatched"])
    return result, paths, guessed
