"""Forgiving parsers for values found in hand-kept flight spreadsheets: dates in many shapes
(including Excel serial numbers and partial dates), times, airport cells, routes, flight
numbers, cabins, seat types and participant lists. Shared by the converter and the template
importer so both read a value the same way."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

EXCEL_EPOCH = dt.date(1899, 12, 30)


class ValueProblem(ValueError):
    """A cell that can't be read; the message is shown in the unmatched report."""


@dataclass(frozen=True)
class FlightDate:
    date: dt.date  # first day of the period
    precision: str  # day, month, year

    @property
    def start(self) -> dt.date:
        return self.date

    @property
    def end(self) -> dt.date:
        if self.precision == "day":
            return self.date
        if self.precision == "month":
            following = (self.date.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            return following - dt.timedelta(days=1)
        return self.date.replace(month=12, day=31)

    def iso(self) -> str:
        if self.precision == "year":
            return f"{self.date.year:04d}"
        if self.precision == "month":
            return f"{self.date.year:04d}-{self.date.month:02d}"
        return self.date.isoformat()


def text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}


def _year(value: str) -> int:
    year = int(value)
    if len(value) == 2:  # two-digit years: 00-current are 2000s, the rest 1900s
        year += 2000 if year <= dt.date.today().year % 100 else 1900
    return year


def _checked(year: int, month: int, day: int | None) -> FlightDate:
    if not 1900 <= year <= 2100:
        raise ValueProblem(f"year {year} is out of range")
    try:
        if day is None:
            return FlightDate(dt.date(year, month, 1), "month")
        return FlightDate(dt.date(year, month, day), "day")
    except ValueError as exc:
        raise ValueProblem(f"not a real date ({exc})") from exc


def parse_date(value, *, dayfirst: bool = False) -> FlightDate | None:
    """None for an empty cell; ValueProblem for one that can't be read."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return FlightDate(value.date(), "day")
    if isinstance(value, dt.date):
        return FlightDate(value, "day")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if 1900 <= value <= 2100 and float(value).is_integer():
            return FlightDate(dt.date(int(value), 1, 1), "year")
        if 1 <= value < 80000:  # an Excel serial date that lost its formatting
            return FlightDate(EXCEL_EPOCH + dt.timedelta(days=int(value)), "day")
    raw = text(value)
    if not raw:
        return None
    lowered = raw.lower().rstrip(".")
    lowered = re.sub(r"[ t]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?(z|[+-]\d{2}:?\d{2})?$", "", lowered)
    if m := re.fullmatch(r"(\d{4})", lowered):
        year = int(m[1])
        if not 1900 <= year <= 2100:
            raise ValueProblem(f"year {year} is out of range")
        return FlightDate(dt.date(year, 1, 1), "year")
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})", lowered):
        return _checked(int(m[1]), int(m[2]), None)
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", lowered):
        return _checked(int(m[1]), int(m[2]), int(m[3]))
    if m := re.fullmatch(r"(\d{1,2})[/-](\d{4})", lowered):  # 03/1998
        return _checked(int(m[2]), int(m[1]), None)
    if m := re.fullmatch(r"(\d{1,2})([/.-])(\d{1,2})\2(\d{2}|\d{4})", lowered):
        first, second, year = int(m[1]), int(m[3]), _year(m[4])
        # Dots are a day-first convention; otherwise follow the setting, unless only one
        # reading is possible.
        day_first = dayfirst or m[2] == "." or first > 12
        if second > 12:
            day_first = False
        day, month = (first, second) if day_first else (second, first)
        return _checked(year, month, day)
    if m := re.fullmatch(r"(\d{8})", lowered):  # 19980314
        return _checked(int(m[1][:4]), int(m[1][4:6]), int(m[1][6:]))
    words = re.findall(r"[a-z]+|\d+", lowered)
    month_words = [w for w in words if w in MONTHS]
    numbers = [w for w in words if w.isdigit()]
    if len(month_words) == 1 and 1 <= len(numbers) <= 2:
        month = MONTHS[month_words[0]]
        years = [n for n in numbers if len(n) == 4]
        if len(numbers) == 1:  # "March 1998", "Mar-98"
            return _checked(_year(numbers[0]), month, None)
        if len(years) == 1:  # "14 Mar 1998", "Mar 14, 1998"
            day = next(n for n in numbers if n is not years[0])
            return _checked(int(years[0]), month, int(day))
        return _checked(_year(numbers[1]), month, int(numbers[0]))  # "14-Mar-98"
    raise ValueProblem(f"unrecognised date {raw!r}")


def parse_time(value) -> dt.time | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, dt.time):
        return value.replace(microsecond=0)
    if isinstance(value, float) and 0 <= value < 1:  # Excel time fraction
        seconds = round(value * 86400)
        return dt.time(seconds // 3600 % 24, seconds // 60 % 60)
    raw = text(value).lower().replace(".", "")
    if not raw:
        return None
    if m := re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?(?::(\d{2}))?\s*(am|pm|a|p)?", raw):
        hour, minute = int(m[1]), int(m[2] or 0)
        if m[4]:
            if not 1 <= hour <= 12:
                raise ValueProblem(f"unrecognised time {value!r}")
            hour = hour % 12 + (12 if m[4].startswith("p") else 0)
        if hour == 24 and minute == 0:
            hour = 0
        if hour > 23 or minute > 59:
            raise ValueProblem(f"unrecognised time {value!r}")
        return dt.time(hour, minute)
    raise ValueProblem(f"unrecognised time {value!r}")


AIRPORT_CODE = re.compile(r"\b([A-Z]{4}|[A-Z]{3})\b")


def airport_code(value) -> str:
    """The code in an airport cell: 'DEN', 'den', 'Denver (DEN)', 'DEN - Denver', 'KDEN'. Text
    without a code is returned as it is (the resolver may match it as a city name)."""
    raw = text(value)
    if not raw:
        return ""
    if m := re.search(r"\(([A-Za-z]{3,4})\)", raw):
        return m[1].upper()
    if re.fullmatch(r"[A-Za-z]{3,4}", raw):
        return raw.upper()
    if m := re.match(r"([A-Za-z]{3,4})\s*[-\u2013\u2014:/|,]\s*\S", raw):
        return m[1].upper()
    codes = AIRPORT_CODE.findall(raw)
    if len(codes) == 1:
        return codes[0]
    return raw


def split_route(value) -> tuple[str, str] | None:
    """'MCI-DEN', 'MCI → DEN', 'MCI to DEN', 'MCI/DEN', 'MCI DEN'."""
    raw = text(value)
    m = re.fullmatch(
        r"([A-Za-z]{3,4})\s*(?:-|\u2013|\u2014|>|\u2192|->|/|to|\s)\s*([A-Za-z]{3,4})",
        raw,
        flags=re.I,
    )
    if m:
        return m[1].upper(), m[2].upper()
    return None


FLIGHT_NUMBER = re.compile(r"^\s*([A-Z0-9]{2}[A-Z]?)\s*-?\s*(\d{1,4}[A-Z]?)\s*$", re.I)


def split_flight_number(value) -> tuple[str, str]:
    """('UA', '123') for 'UA 123', 'ua123', 'BAW12'; ('', '123') for '123'."""
    raw = text(value).upper()
    if not raw:
        return "", ""
    if re.fullmatch(r"\d{1,4}[A-Z]?", raw):
        return "", raw
    if (m := FLIGHT_NUMBER.match(raw)) and re.search(r"[A-Z]", m[1]):
        return m[1], m[2]
    return "", raw.replace(" ", "")[:16]


CABINS = {
    "economy": "economy",
    "coach": "economy",
    "y": "economy",
    "main": "economy",
    "main cabin": "economy",
    "basic economy": "economy",
    "standard": "economy",
    "premium economy": "premium_economy",
    "premium": "premium_economy",
    "economy plus": "premium_economy",
    "comfort": "premium_economy",
    "w": "premium_economy",
    "business": "business",
    "business class": "business",
    "biz": "business",
    "j": "business",
    "c": "business",
    "club": "business",
    "first": "first",
    "first class": "first",
    "f": "first",
}


def cabin_class(value) -> tuple[str, bool]:
    """(enum value, recognised). Unknown text maps to 'other' so it isn't lost silently."""
    raw = text(value).lower().replace("-", " ").replace("_", " ")
    if not raw:
        return "", True
    raw = re.sub(r"\s*class$", "", raw) if raw not in CABINS else raw
    if raw in CABINS:
        return CABINS[raw], True
    for key in ("premium", "business", "first", "economy", "coach"):
        if key in raw:
            return CABINS[key], True
    return "other", False


SEAT_TYPES = {
    "w": "window",
    "window": "window",
    "m": "middle",
    "middle": "middle",
    "center": "middle",
    "centre": "middle",
    "a": "aisle",
    "aisle": "aisle",
}


def seat_type(value) -> str:
    raw = text(value).lower()
    if not raw:
        return ""
    return SEAT_TYPES.get(raw, SEAT_TYPES.get(raw.split()[0], "other"))


def participants(value) -> list[str]:
    raw = text(value)
    if not raw:
        return []
    parts = re.split(r"\s*(?:;|,|/|&|\+|\band\b)\s*", raw)
    return [part.strip()[:100] for part in parts if part.strip()]
