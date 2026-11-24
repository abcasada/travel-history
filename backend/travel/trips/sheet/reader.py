"""Reading an uploaded trip spreadsheet safely (§28.1): size and archive limits checked before
openpyxl sees the file, read-only mode, XML parsed through defusedxml (openpyxl uses it when it
is installed; `defused_xml_active` lets a test insist on it), formulas never evaluated (their
text is kept: §28.5 reads two forms of row reference from it)."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter

from travel.history.models import ImportBatch
from travel.history.uploads import KIND_MAX_BYTES

MAX_FILE_BYTES = KIND_MAX_BYTES[ImportBatch.Kind.TRIP_SHEET]  # 10 MB
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 5000
MAX_TRIP_TABS = 500
MAX_ROWS = 2000
MAX_COLUMNS = 40
SKIPPED_TABS = {"instructions"}


class SheetFileError(ValueError):
    """The file as a whole can't be read (not .xlsx, too large); no tab is imported."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass
class Cell:
    value: Any
    number_format: str = ""


@dataclass
class RawTab:
    name: str
    position: int  # 1-based among the workbook's worksheets
    rows: list[tuple[int, list[Cell]]]  # (sheet row number, cells A..)
    truncated: bool = False  # more than MAX_ROWS rows or MAX_COLUMNS columns of data


def defused_xml_active() -> bool:
    from openpyxl.xml import DEFUSEDXML

    return bool(DEFUSEDXML)


def column_letter(index: int) -> str:
    """0-based column index -> spreadsheet letter."""
    return get_column_letter(index + 1)


def check_archive(data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise SheetFileError("too_large", "the file is larger than 10 MB")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise SheetFileError(
            "bad_file", "not an .xlsx file (save .xls, .ods or Numbers files as .xlsx first)"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
    except (zipfile.BadZipFile, ValueError) as exc:
        raise SheetFileError("bad_file", f"the .xlsx archive is damaged ({exc})") from None
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise SheetFileError("too_large", "the .xlsx archive has too many parts")
    if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
        raise SheetFileError("too_large", "the .xlsx file unpacks to more than 100 MB")


def is_skipped(name: str) -> bool:
    """`Instructions` and tabs starting with `_` (the template's `_Example`) are never trips."""
    return name.strip().casefold() in SKIPPED_TABS or name.startswith("_")


def read_tabs(data: bytes) -> tuple[list[RawTab], int]:
    """The trip tabs (at most MAX_TRIP_TABS) and how many more trip tabs were left unread."""
    if not defused_xml_active():  # pragma: no cover - the requirement pins defusedxml
        raise SheetFileError("bad_file", "the server can't read spreadsheets safely right now")
    check_archive(data)
    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(data), read_only=True, data_only=False, keep_links=False
        )
    except Exception as exc:  # noqa: BLE001 - openpyxl raises many types for a broken file
        raise SheetFileError(
            "bad_file", f"the .xlsx file can't be read ({type(exc).__name__})"
        ) from None
    tabs: list[RawTab] = []
    extra = 0
    try:
        for position, sheet in enumerate(workbook.worksheets, start=1):
            if is_skipped(sheet.title):
                continue
            if len(tabs) >= MAX_TRIP_TABS:
                extra += 1
                continue
            tabs.append(_read_tab(sheet, position))
    finally:
        workbook.close()
    return tabs, extra


def _read_tab(sheet, position: int) -> RawTab:
    rows: list[tuple[int, list[Cell]]] = []
    truncated = False
    # One row and one column past the limits, only to notice that there is more.
    for number, cells in enumerate(
        sheet.iter_rows(min_row=1, max_row=MAX_ROWS + 1, max_col=MAX_COLUMNS + 1), start=1
    ):
        values = [
            Cell(getattr(c, "value", None), getattr(c, "number_format", "") or "") for c in cells
        ]
        if len(values) > MAX_COLUMNS:
            if any(_filled(c.value) for c in values[MAX_COLUMNS:]):
                truncated = True
            values = values[:MAX_COLUMNS]
        if number > MAX_ROWS:
            truncated = truncated or any(_filled(c.value) for c in values)
            break
        rows.append((number, values))
    return RawTab(sheet.title, position, rows, truncated)


def _filled(value) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())
