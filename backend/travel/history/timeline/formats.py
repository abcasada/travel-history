"""Streaming parser for Google Maps Timeline on-device exports (PLAN.md §8.1).

Two variants exist and are detected by the root token:
  Android: {"semanticSegments": [...], "rawSignals": [...], "userLocationProfile": {...}}
  iOS:     [ {"startTime", "endTime", "visit"|"activity"|"timelinePath"}, ... ]
           (unverified until checked against a real iOS export; PLAN.md D-38)
Both are normalized to `Segment` / `RawPoint` / `Hint`. Files can be hundreds of MB, so nothing
here holds more than one segment at a time (ijson, C backend)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import BinaryIO

import ijson

ANDROID, IOS = "android", "ios"

_DEGREES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)°?\s*,\s*(-?\d+(?:\.\d+)?)°?\s*$")
_GEO_URI = re.compile(r"^\s*geo:\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)")


class ParseWarning(Exception):
    """A malformed record: skipped and counted, never fatal for the whole import."""


@dataclass(frozen=True)
class PathPoint:
    ts: dt.datetime
    lat: float
    lon: float


@dataclass
class Segment:
    kind: str  # visit | activity | path | memory
    start: dt.datetime
    end: dt.datetime
    utc_offset_min: int | None = None
    hierarchy_level: int = 0
    place_id: str = ""
    semantic_type: str = ""
    activity_type: str = ""
    probability: float | None = None
    coords: list[tuple[float, float]] = field(default_factory=list)  # (lat, lon)
    distance_m: float | None = None
    points: list[PathPoint] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def canonical(self) -> dict:
        """The content that identifies this segment's version (probability excluded: Google
        recomputes it without the user changing anything)."""
        return {
            "kind": self.kind,
            "start": self.start.isoformat(timespec="seconds"),
            "end": self.end.isoformat(timespec="seconds"),
            "level": self.hierarchy_level,
            "place_id": self.place_id,
            "semantic_type": self.semantic_type,
            "activity_type": self.activity_type,
            "coords": [[round(lat, 6), round(lon, 6)] for lat, lon in self.coords],
            "distance_m": None if self.distance_m is None else round(self.distance_m),
            "points": [
                [p.ts.isoformat(timespec="seconds"), round(p.lat, 6), round(p.lon, 6)]
                for p in self.points
            ],
            "extra": self.extra,
        }

    @property
    def fingerprint(self) -> str:
        blob = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class RawPoint:
    ts: dt.datetime
    lat: float
    lon: float
    accuracy_m: float | None = None
    altitude_m: float | None = None
    speed_mps: float | None = None
    source_detail: str = ""


@dataclass(frozen=True)
class Hint:
    label: str  # HOME | WORK
    place_id: str
    lat: float
    lon: float


# --- Scalar normalization ---------------------------------------------------------------------


def parse_latlng(value) -> tuple[float, float]:
    """'48.8566120°, 2.3522190°' (Android) or 'geo:48.856612,2.352219' (iOS) or {'latLng': …}."""
    if isinstance(value, dict):
        value = value.get("latLng") or value.get("LatLng") or value.get("point")
    if not isinstance(value, str):
        raise ParseWarning(f"coordinates missing or not a string: {value!r}"[:120])
    match = _GEO_URI.match(value) or _DEGREES.match(value)
    if not match:
        raise ParseWarning(f"unrecognized coordinates {value!r}"[:120])
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ParseWarning(f"coordinates out of range {value!r}"[:120])
    return round(lat, 7), round(lon, 7)


def parse_time(value) -> dt.datetime:
    if not isinstance(value, str):
        raise ParseWarning(f"time missing: {value!r}"[:80])
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ParseWarning(f"bad time {value!r}"[:80]) from exc
    if parsed.tzinfo is None:
        raise ParseWarning(f"time without offset {value!r}"[:80])
    return parsed.astimezone(dt.UTC)


def num(value) -> float | None:
    """Numbers are JSON numbers on Android and strings on iOS."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def enum(value) -> str:
    """'in passenger vehicle' / 'IN_PASSENGER_VEHICLE' / 'Searched Address' -> upper snake."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")


def _offset_minutes(record: dict) -> int | None:
    value = num(record.get("startTimeTimezoneUtcOffsetMinutes"))
    return None if value is None else int(value)


# --- Segment builders (shared by both variants) ----------------------------------------------


def _segment(record: dict, *, ios: bool) -> Segment:
    start, end = parse_time(record.get("startTime")), parse_time(record.get("endTime"))
    if end < start:
        raise ParseWarning("segment ends before it starts")
    offset = _offset_minutes(record)
    if "visit" in record:
        visit = record["visit"] or {}
        top = visit.get("topCandidate") or {}
        lat, lon = parse_latlng(top.get("placeLocation"))
        return Segment(
            kind="visit",
            start=start,
            end=end,
            utc_offset_min=offset,
            hierarchy_level=int(num(visit.get("hierarchyLevel")) or 0),
            place_id=str(top.get("placeId") or top.get("placeID") or ""),
            semantic_type=enum(top.get("semanticType")),
            probability=num(top.get("probability")),
            coords=[(lat, lon)],
        )
    if "activity" in record:
        activity = record["activity"] or {}
        top = activity.get("topCandidate") or {}
        coords = [parse_latlng(activity.get("start")), parse_latlng(activity.get("end"))]
        return Segment(
            kind="activity",
            start=start,
            end=end,
            utc_offset_min=offset,
            activity_type=enum(top.get("type")),
            probability=num(top.get("probability")),
            coords=coords,
            distance_m=num(activity.get("distanceMeters")),
        )
    if "timelinePath" in record:
        points = []
        for item in record.get("timelinePath") or []:
            lat, lon = parse_latlng(item.get("point"))
            if ios:  # minute offsets from the segment start
                minutes = num(item.get("durationMinutesOffsetFromStartTime")) or 0
                ts = start + dt.timedelta(minutes=minutes)
            else:
                ts = parse_time(item.get("time"))
            points.append(PathPoint(ts, lat, lon))
        if not points:
            raise ParseWarning("empty timelinePath")
        return Segment(
            kind="path",
            start=start,
            end=end,
            utc_offset_min=offset,
            coords=[(p.lat, p.lon) for p in points],
            points=points,
        )
    if "timelineMemory" in record:
        trip = (record["timelineMemory"] or {}).get("trip") or {}
        destinations = [
            str((d.get("identifier") or {}).get("placeId") or "")
            for d in trip.get("destinations") or []
        ]
        return Segment(
            kind="memory",
            start=start,
            end=end,
            utc_offset_min=offset,
            extra={
                "destinations": destinations,
                "distance_from_origin_km": num(trip.get("distanceFromOriginKms")),
            },
        )
    raise ParseWarning("segment without visit/activity/timelinePath/timelineMemory")


# --- Readers -------------------------------------------------------------------------------------


def detect(open_stream: Callable[[], BinaryIO]) -> str:
    with open_stream() as stream:
        head = stream.read(4096).lstrip()
    if head[:1] == b"{":
        return ANDROID
    if head[:1] == b"[":
        return IOS
    raise ValueError("not a Google Timeline export (expected a JSON object or array)")


@dataclass
class ParseStats:
    warnings: list[str] = field(default_factory=list)
    warning_count: int = 0

    def warn(self, message: str) -> None:
        self.warning_count += 1
        if len(self.warnings) < 20:
            self.warnings.append(message)


def iter_segments(
    open_stream: Callable[[], BinaryIO], variant: str, stats: ParseStats
) -> Iterator[Segment]:
    prefix = "semanticSegments.item" if variant == ANDROID else "item"
    with open_stream() as stream:
        for index, record in enumerate(ijson.items(stream, prefix, use_float=True)):
            try:
                yield _segment(record, ios=variant == IOS)
            except ParseWarning as warning:
                stats.warn(f"segment {index}: {warning}")


def iter_raw_points(
    open_stream: Callable[[], BinaryIO], variant: str, stats: ParseStats
) -> Iterator[RawPoint]:
    """Android `rawSignals[].position`; the iOS export has no raw signals."""
    if variant != ANDROID:
        return
    with open_stream() as stream:
        for index, record in enumerate(ijson.items(stream, "rawSignals.item", use_float=True)):
            position = record.get("position")
            if not position:
                continue  # wifiScan / activityRecord: kept only in the raw file
            try:
                lat, lon = parse_latlng(position.get("LatLng") or position.get("latLng"))
                yield RawPoint(
                    ts=parse_time(position.get("timestamp")),
                    lat=lat,
                    lon=lon,
                    accuracy_m=num(position.get("accuracyMeters")),
                    altitude_m=num(position.get("altitudeMeters")),
                    speed_mps=num(position.get("speedMetersPerSecond")),
                    source_detail=enum(position.get("source")),
                )
            except ParseWarning as warning:
                stats.warn(f"raw signal {index}: {warning}")


def iter_hints(
    open_stream: Callable[[], BinaryIO], variant: str, stats: ParseStats
) -> Iterator[Hint]:
    """Android `userLocationProfile.frequentPlaces` labelled HOME/WORK."""
    if variant != ANDROID:
        return
    with open_stream() as stream:
        for index, place in enumerate(
            ijson.items(stream, "userLocationProfile.frequentPlaces.item", use_float=True)
        ):
            label = enum(place.get("label"))
            if label not in {"HOME", "WORK"}:
                continue
            try:
                lat, lon = parse_latlng(place.get("placeLocation"))
                yield Hint(label, str(place.get("placeId") or ""), lat, lon)
            except ParseWarning as warning:
                stats.warn(f"frequent place {index}: {warning}")
