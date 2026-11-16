"""Tracker payloads (PLAN.md §9.1), validated strictly.

Every field a tracker may send is listed with its type and range; anything else, a wrong type
(strings for numbers, booleans for numbers), NaN or infinity, or a value out of range rejects
the whole request with 400. The tracker then keeps the data and retries, so nothing is lost
while a server-side fix is made (for example, if an app update adds a field). The field lists
come from the OwnTracks JSON booklet, the OwnTracks Android message classes, the Overland API
page and Colota's OwnTracks template (docs/research/formats-trackers-datasets.md).

Only position, time, accuracy, altitude, speed, course and battery are kept. The rest (Wi-Fi
names, regions, images, motion, trip data) is accepted and discarded: it isn't needed, and
some of it (network names) would say where someone lives.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

MAX_ERRORS = 5


@dataclass(frozen=True)
class Fix:
    """One position report, normalized (speed in m/s, battery in percent, UTC time)."""

    ts: dt.datetime
    lat: float
    lon: float
    accuracy_m: float | None = None
    altitude_m: float | None = None
    speed_mps: float | None = None
    course_deg: float | None = None
    battery_pct: int | None = None


@dataclass
class Parsed:
    fixes: list[Fix] = field(default_factory=list)
    ignored: int = 0  # messages that are not positions (OwnTracks lwt/card/…, Overland trips)


class PayloadError(Exception):
    """A request the endpoint refuses. `detail` and `errors` go back to the tracker; they name
    fields and problems, never values."""

    def __init__(self, status: int, detail: str, errors: list[str] | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.errors = errors or []


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


def load_json(body: bytes) -> Any:
    try:
        return json.loads(body, parse_constant=_reject_constant)
    except (ValueError, RecursionError, UnicodeDecodeError):
        raise PayloadError(400, "the body is not valid JSON") from None


def _num(low: float, high: float) -> Any:
    return Field(default=None, ge=low, le=high, allow_inf_nan=False)


def _text(max_length: int) -> Any:
    return Annotated[str, StringConstraints(max_length=max_length)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


# --- OwnTracks (also GPSLogger with the documented body template, and Colota's template) ---

OWNTRACKS_IGNORED_TYPES = frozenset(
    {
        "beacon",
        "card",
        "cmd",
        "configuration",
        "lwt",
        "request",
        "status",
        "steps",
        "transition",
        "waypoint",
        "waypoints",
    }
)


class OwnTracksLocation(_Strict):
    type_: Literal["location"] = Field(alias="_type")
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    tst: int = Field(ge=0, le=10**10)  # epoch seconds; the plausible window is checked later
    acc: float | None = _num(0, 10_000_000)  # metres
    alt: float | None = _num(-12_000, 100_000)  # metres
    vac: float | None = _num(-1, 10_000_000)
    vel: float | None = _num(-1, 100_000)  # km/h
    cog: float | None = _num(-1, 360)
    rad: float | None = _num(0, 10_000_000)
    batt: float | None = _num(-1, 100)
    bs: int | None = Field(default=None, ge=0, le=3)
    p: float | None = _num(0, 1_000)  # kPa
    m: int | None = Field(default=None, ge=-1, le=10)
    created_at: int | None = Field(default=None, ge=0, le=10**10)
    t: _text(4) | None = None
    conn: _text(4) | None = None
    tid: _text(16) | None = None
    topic: _text(256) | None = None
    source: _text(64) | None = None
    id_: _text(64) | None = Field(default=None, alias="_id")
    SSID: _text(128) | None = None
    BSSID: _text(64) | None = None
    poi: _text(512) | None = None
    tag: _text(512) | None = None
    image: str | None = None  # bounded by the request size cap
    imagename: _text(256) | None = None
    inregions: list[_text(256)] | None = Field(default=None, max_length=256)
    inrids: list[_text(64)] | None = Field(default=None, max_length=256)
    motionactivities: list[_text(32)] | None = Field(default=None, max_length=16)
    # Serialized by some OwnTracks Android versions; never used here.
    modeId: int | None = Field(default=None, ge=0, le=10)
    qos: int | None = Field(default=None, ge=0, le=2)
    retained: bool | None = None

    def fix(self) -> Fix:
        return Fix(
            ts=dt.datetime.fromtimestamp(self.tst, tz=dt.UTC),
            lat=self.lat,
            lon=self.lon,
            accuracy_m=self.acc,
            altitude_m=self.alt,
            speed_mps=None if self.vel is None or self.vel < 0 else self.vel / 3.6,
            course_deg=None if self.cog is None or self.cog < 0 else self.cog,
            battery_pct=None if self.batt is None or self.batt < 0 else round(self.batt),
        )


def parse_owntracks(document: Any) -> Parsed:
    """One OwnTracks message: a `location` becomes a fix; the other known types are ignored;
    `encrypted` and unknown types are refused."""
    if not isinstance(document, dict):
        raise PayloadError(400, "expected one OwnTracks message (a JSON object)")
    kind = document.get("_type")
    if kind == "location":
        return Parsed(fixes=[_validate(OwnTracksLocation, document, "").fix()])
    if kind == "encrypted":
        raise PayloadError(
            400, "encrypted OwnTracks payloads are not supported; turn encryption off"
        )
    if isinstance(kind, str) and kind in OWNTRACKS_IGNORED_TYPES:
        return Parsed(ignored=1)
    raise PayloadError(400, "unknown or missing OwnTracks message type", ["_type: invalid"])


# --- Overland (iOS; also Colota's Overland template) ----------------------------------------

OVERLAND_IGNORED_RECORDS = frozenset({"trip", "visit"})


class OverlandGeometry(_Strict):
    type: Literal["Point"]
    coordinates: list[float] = Field(min_length=2, max_length=3)


class OverlandProperties(_Strict):
    timestamp: _text(40)
    altitude: float | None = _num(-12_000, 100_000)
    speed: float | None = _num(-1, 100_000)  # m/s, -1 = unknown
    course: float | None = _num(-1, 360)
    horizontal_accuracy: float | None = _num(-1, 10_000_000)
    vertical_accuracy: float | None = _num(-1, 10_000_000)
    speed_accuracy: float | None = _num(-1, 100_000)
    course_accuracy: float | None = _num(-1, 360)
    motion: list[_text(32)] | None = Field(default=None, max_length=16)
    battery_state: _text(16) | None = None
    battery_level: float | None = _num(-1, 1)
    wifi: _text(128) | None = None
    wifi_bssid: _text(64) | None = None
    device_id: _text(128) | None = None
    unique_id: _text(128) | None = None
    trip_id: _text(64) | None = None
    trip_mode: _text(64) | None = None
    pauses: bool | None = None
    activity: _text(32) | None = None
    desired_accuracy: float | None = _num(-1, 10_000_000)
    deferred: float | None = _num(-1, 10_000_000)
    significant_change: _text(16) | None = None
    locations_in_payload: int | None = Field(default=None, ge=0, le=100_000)


class OverlandFeature(_Strict):
    type: Literal["Feature"]
    geometry: OverlandGeometry
    properties: OverlandProperties

    def fix(self, where: str) -> Fix:
        lon, lat = self.geometry.coordinates[0], self.geometry.coordinates[1]
        errors = []
        if not -180 <= lon <= 180:
            errors.append(f"{where}.geometry.coordinates.0: out of range")
        if not -90 <= lat <= 90:
            errors.append(f"{where}.geometry.coordinates.1: out of range")
        ts = _iso_utc(self.properties.timestamp)
        if ts is None:
            errors.append(f"{where}.properties.timestamp: needs ISO 8601 with a UTC offset")
        if errors:
            raise PayloadError(400, "the payload does not match the Overland format", errors)
        p = self.properties
        speed = p.speed if p.speed is not None and p.speed >= 0 else None
        level = p.battery_level if p.battery_level is not None and p.battery_level >= 0 else None
        altitude = p.altitude
        if altitude is None and len(self.geometry.coordinates) == 3:
            altitude = self.geometry.coordinates[2]
        return Fix(
            ts=ts,
            lat=lat,
            lon=lon,
            accuracy_m=_known(p.horizontal_accuracy),
            altitude_m=altitude,
            speed_mps=speed,
            course_deg=_known(p.course),
            battery_pct=None if level is None else round(level * 100),
        )


class OverlandBatch(_Strict):
    locations: list[dict[str, Any]]
    current: dict[str, Any] | None = None  # newest queued point; it is also in a later batch
    trip: dict[str, Any] | None = None


def parse_overland(document: Any, max_points: int) -> Parsed:
    if not isinstance(document, dict):
        raise PayloadError(400, "expected an Overland batch (a JSON object)")
    locations = document.get("locations")
    if isinstance(locations, list) and len(locations) > max_points:
        raise PayloadError(413, f"too many locations in one request (at most {max_points})")
    batch = _validate(OverlandBatch, document, "")
    parsed = Parsed()
    for index, item in enumerate(batch.locations):
        where = f"locations.{index}"
        properties = item.get("properties")
        if isinstance(properties, dict) and properties.get("type") in OVERLAND_IGNORED_RECORDS:
            parsed.ignored += 1
            continue
        parsed.fixes.append(_validate(OverlandFeature, item, where).fix(where))
    return parsed


# --- Helpers -------------------------------------------------------------------------------

_SAFE_KEY = re.compile(r"[^A-Za-z0-9_]")


def _validate[M: BaseModel](model: type[M], document: Any, where: str) -> M:
    try:
        return model.model_validate(document)
    except ValidationError as error:
        problems = []
        for item in error.errors(include_input=False, include_url=False)[:MAX_ERRORS]:
            path = [where] if where else []
            path += [_SAFE_KEY.sub("", str(part))[:40] for part in item["loc"]]
            problems.append(f"{'.'.join(path)}: {_problem(item['type'])}")
        raise PayloadError(
            400, "the payload does not match the expected format", problems
        ) from None


def _problem(kind: str) -> str:
    if kind == "extra_forbidden":
        return "unknown field"
    if kind == "missing":
        return "required"
    if kind.endswith(("_greater_than_equal", "_less_than_equal", "finite_number")):
        return "out of range"
    if kind.endswith("too_long") or kind.endswith("too_short"):
        return "wrong length"
    if kind == "literal_error":
        return "invalid"
    return "wrong type"


def _iso_utc(text: str) -> dt.datetime | None:
    try:
        value = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        return None
    return value.astimezone(dt.UTC)


def _known(value: float | None) -> float | None:
    return None if value is None or value < 0 else value
