"""Cell parsers for the trip spreadsheet (§28.3-§28.6). Each raises `CellProblem` with a reason
code from §28.7 for a cell that can't be read; nothing is guessed."""

from __future__ import annotations

import datetime as dt
import re
import zoneinfo
from dataclasses import dataclass, field
from functools import cache

from travel.flights import normalize as n
from travel.geo.gazetteer import fold


class CellProblem(Exception):
    def __init__(
        self, reason: str, message: str, hint: str = "", candidates: list[str] | None = None
    ):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.hint = hint
        self.candidates = candidates or []


def text(value) -> str:
    return n.text(value)


def is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def header_name(value) -> str:
    """Header matching ignores case, surrounding spaces and a trailing ':' or '*' (§28.2)."""
    name = re.sub(r"\s+", " ", text(value)).strip().lower()
    return name.rstrip(":*").strip()


def sheet_key(value: str) -> str:
    """Trip keys: trimmed, case-folded, spaces collapsed (§28.3)."""
    return re.sub(r"\s+", " ", value).strip().casefold()


def split_list(value) -> list[str]:
    """`;`-separated names, blanks dropped, duplicates (case-insensitive) dropped."""
    seen: dict[str, str] = {}
    for part in text(value).split(";"):
        name = part.strip()
        if name and name.casefold() not in seen:
            seen[name.casefold()] = name
    return list(seen.values())


# --- Enumerations -----------------------------------------------------------------------------

MODES = {
    "drive": "drive",
    "car": "drive",
    "auto": "drive",
    "flight": "flight",
    "plane": "flight",
    "air": "flight",
    "fly": "flight",
    "train": "train",
    "rail": "train",
    "bus": "bus",
    "coach": "bus",
    "boat": "boat",
    "ferry": "boat",
    "ship": "boat",
    "walk": "walk",
    "foot": "walk",
    "hike": "walk",
    "other": "other",
}
STOP_KINDS = ("lodging", "destination", "visit", "waypoint")
VISIBILITIES = ("private", "participants", "family")


def choice(value, allowed, what: str, aliases: dict[str, str] | None = None) -> str | None:
    raw = text(value).lower()
    if not raw:
        return None
    if aliases and raw in aliases:
        return aliases[raw]
    if raw in allowed:
        return raw
    known = ", ".join(sorted(set(aliases.values()) if aliases else allowed))
    raise CellProblem("bad_value", f"{what} {text(value)!r} is not one of: {known}", hint=known)


def mode(value) -> str | None:
    return choice(value, set(MODES.values()), "mode", MODES)


# --- Local times (§28.6) ----------------------------------------------------------------------


@dataclass(frozen=True)
class LocalTime:
    """A wall-clock time in the row's zone (midnight for a date), how precise it is, and an
    optional UTC offset given to settle a repeated hour."""

    value: dt.datetime
    precision: str  # exact, day, month, year
    offset: dt.timedelta | None = None

    @property
    def date(self) -> dt.date:
        return self.value.date()

    def last_date(self) -> dt.date:
        """The last day this value covers (a month or year stands for its whole period)."""
        return n.FlightDate(self.date, self.precision if self.precision != "exact" else "day").end

    def iso(self) -> str:
        if self.precision == "exact":
            return self.value.isoformat(sep=" ", timespec="minutes")
        return n.FlightDate(self.date, self.precision).iso()


OFFSET = re.compile(r"\s*(?:UTC|GMT)?\s*(Z|[+-]\d{2}:?\d{2})$", re.I)
TIME_AT_END = re.compile(
    r"(?:^|[\sT])(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]\.?m?\.?)?|\d{1,2}\s*[ap]\.?m\.?)$", re.I
)
SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b")


def _offset(raw: str) -> tuple[str, dt.timedelta | None]:
    m = OFFSET.search(raw)
    # Only after a time ("2015-11-01 01:30 -05:00"), so "2015-11" isn't read as an offset.
    if not m or not re.search(r"\d:\d{2}(:\d{2})?\s*$", raw[: m.start()]):
        return raw, None
    written = m[1].upper()
    if written == "Z":
        return raw[: m.start()].strip(), dt.timedelta(0)
    sign = -1 if written[0] == "-" else 1
    digits = written[1:].replace(":", "")
    hours, minutes = int(digits[:2]), int(digits[2:])
    if hours > 14 or minutes > 59:
        raise CellProblem("bad_time", f"UTC offset {m[1]} is out of range")
    return raw[: m.start()].strip(), sign * dt.timedelta(hours=hours, minutes=minutes)


def _date_part(raw: str) -> n.FlightDate:
    if m := SLASH_DATE.match(raw):
        first, second = int(m[1]), int(m[2])
        if first <= 12 and second <= 12 and first != second:
            raise CellProblem(
                "ambiguous_date",
                f"{raw!r} could be month/day or day/month",
                hint="write the date as YYYY-MM-DD",
            )
    try:
        parsed = n.parse_date(raw)
    except n.ValueProblem as exc:
        raise CellProblem("bad_date", str(exc), hint="write YYYY-MM-DD HH:MM") from None
    if parsed is None:
        raise CellProblem("bad_date", f"unrecognised date {raw!r}")
    return parsed


def local_time(value, number_format: str = "") -> LocalTime | None:
    """None for an empty cell. A date-time cell is wall-clock time; a date cell (a date or a
    midnight date-time whose format shows no hours) is a date only."""
    if is_blank(value):
        return None
    if isinstance(value, dt.datetime):
        shows_time = "h" in number_format.lower() if number_format else value.time() != dt.time()
        if shows_time:
            return LocalTime(value.replace(microsecond=0, tzinfo=None), "exact")
        return LocalTime(dt.datetime.combine(value.date(), dt.time()), "day")
    if isinstance(value, dt.date):
        return LocalTime(dt.datetime.combine(value, dt.time()), "day")
    if isinstance(value, dt.time):
        raise CellProblem("bad_time", "a time needs a date", hint="write YYYY-MM-DD HH:MM")
    if isinstance(value, bool):
        raise CellProblem("bad_date", f"unrecognised date {value!r}")
    if isinstance(value, int | float):
        try:
            parsed = n.parse_date(value)
        except n.ValueProblem as exc:
            raise CellProblem("bad_date", str(exc)) from None
        if parsed is None:
            return None
        return LocalTime(dt.datetime.combine(parsed.date, dt.time()), parsed.precision)
    raw, offset = _offset(text(value))
    time_part = None
    if m := TIME_AT_END.search(raw):
        date_text = raw[: m.start(1)].strip().rstrip("T").strip()
        if date_text:
            try:
                time_part = n.parse_time(m[1])
            except n.ValueProblem as exc:
                raise CellProblem("bad_time", str(exc), hint="write HH:MM (24-hour)") from None
            raw = date_text
    day = _date_part(raw)
    if time_part is not None:
        if day.precision != "day":
            raise CellProblem("bad_time", "a time needs a full date", hint="write YYYY-MM-DD HH:MM")
        return LocalTime(dt.datetime.combine(day.date, time_part), "exact", offset)
    if offset is not None:
        raise CellProblem("bad_time", "a UTC offset needs a time")
    return LocalTime(dt.datetime.combine(day.date, dt.time()), day.precision)


@cache
def zones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones())


def zone_name(value) -> str | None:
    raw = text(value)
    if not raw:
        return None
    if raw in zones():
        return raw
    for name in zones():  # "america/denver" is still clearly America/Denver
        if name.lower() == raw.lower():
            return name
    raise CellProblem(
        "bad_value", f"unknown time zone {raw!r}", hint="an IANA name such as America/Denver"
    )


def _offset_text(offset: dt.timedelta) -> str:
    minutes = int(offset.total_seconds() // 60)
    sign = "-" if minutes < 0 else "+"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def to_utc(local: LocalTime, zone: str) -> dt.datetime:
    """Never guessed (§28.6): a time in a spring-forward gap is a problem; one in a repeated
    hour needs an offset. A date alone is stored as local midnight."""
    tz = zoneinfo.ZoneInfo(zone)
    first = local.value.replace(tzinfo=tz, fold=0)
    second = local.value.replace(tzinfo=tz, fold=1)
    if local.offset is not None:
        for candidate in (first, second):
            if candidate.utcoffset() == local.offset:
                return candidate.astimezone(dt.UTC)
        raise CellProblem(
            "bad_time",
            f"offset {_offset_text(local.offset)} doesn't occur in {zone} at {local.iso()}",
        )
    if local.precision != "exact":
        return first.astimezone(dt.UTC)
    if first.astimezone(dt.UTC).astimezone(tz).replace(tzinfo=None) != local.value:
        raise CellProblem(
            "nonexistent_time",
            f"{local.iso()} doesn't exist in {zone} (the clocks skipped it)",
            hint="check the time; the hour was skipped when daylight saving began",
        )
    if first.utcoffset() != second.utcoffset():
        options = [_offset_text(c.utcoffset()) for c in (first, second)]
        raise CellProblem(
            "ambiguous_time",
            f"{local.iso()} happened twice in {zone}",
            hint=f"append the offset: {local.iso()} {options[0]} or {local.iso()} {options[1]}",
            candidates=[f"{local.iso()} {o}" for o in options],
        )
    return first.astimezone(dt.UTC)


PRECISION_ORDER = ("exact", "day", "month", "year")


def coarsest(precisions) -> str:
    found = [p for p in precisions if p]
    if not found:
        return "exact"
    return max(found, key=PRECISION_ORDER.index)


# --- Stop references (§28.5) ------------------------------------------------------------------

REF_FORMULA = re.compile(r"^=\s*(?:ROW\s*\(\s*)?\$?[A-Z]{1,3}\$?(\d+)\s*\)?\s*$", re.I)


@dataclass(frozen=True)
class StopRef:
    row: int | None = None
    label: str = ""


def stop_ref(value) -> StopRef | None:
    """A row number (14, 14.0, "14"), a formula =ROW(B14) / =B14 / =$A$14 read from its text,
    or a label (must contain a letter)."""
    if is_blank(value):
        return None
    if isinstance(value, bool):
        raise CellProblem("bad_reference", f"{value!r} is not a stop")
    if isinstance(value, int | float):
        if float(value).is_integer() and value > 0:
            return StopRef(row=int(value))
        raise CellProblem("bad_reference", f"{value!r} is not a row number")
    raw = text(value)
    if m := REF_FORMULA.match(raw):
        return StopRef(row=int(m[1]))
    if raw.startswith("="):
        raise CellProblem(
            "bad_reference",
            f"formula {raw!r} isn't a row reference",
            hint="use =ROW(B14), =B14, a row number or a stop label",
        )
    if re.fullmatch(r"\d+(\.0+)?", raw):
        return StopRef(row=int(float(raw)))
    return StopRef(label=fold(raw))


def stop_label(value) -> str:
    raw = text(value)
    if not raw:
        return ""
    if len(raw) > 40:
        raise CellProblem("bad_value", "a stop label is at most 40 characters")
    if not re.search(r"[^\W\d_]", raw):
        raise CellProblem(
            "bad_value",
            f"stop label {raw!r} needs a letter, so it can't be read as a row number",
        )
    return raw


# --- Issues ----------------------------------------------------------------------------------


@dataclass
class Issue:
    tab: str
    row: int | None
    column: str  # letter, e.g. "B"
    header: str
    field: str
    severity: str  # problem, warning, info
    reason: str
    message: str
    hint: str = ""
    candidates: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "tab": self.tab,
            "row": self.row,
            "column": self.column,
            "header": self.header,
            "field": self.field,
            "severity": self.severity,
            "reason": self.reason,
            "message": self.message,
            "hint": self.hint,
            "candidates": self.candidates,
        }
