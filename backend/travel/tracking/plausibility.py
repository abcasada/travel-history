"""Plausibility flags for tracker points (work-order item 7).

A point is never dropped for looking wrong: it is stored with flags in `extra["flags"]`, so a
consumer (map, trip detection) can skip it and a person can still see it.

- `reported_speed`: the device itself reported a speed above the limit.
- `implied_speed`: getting here from the device's previous point would need a speed above the
  limit, after allowing for both points' reported accuracy. A point passes if the jump is
  plausible from either the previous point or the last point that wasn't flagged; so after a
  single bad fix (a spike) only the spike is flagged, and after a bad fix that couldn't be
  judged (the first fix after a long gap) only one good point is.

The limit (`TRACKER_MAX_SPEED_MPS`, default 400 m/s ≈ 1,440 km/h) is above any airliner's
ground speed, so a flag means a glitch, not a fast trip.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from .payloads import Fix

EARTH_RADIUS_M = 6_371_008.8
HALF_CIRCUMFERENCE_M = math.pi * EARTH_RADIUS_M
REPORTED_SPEED = "reported_speed"
IMPLIED_SPEED = "implied_speed"


@dataclass(frozen=True)
class Anchor:
    ts: dt.datetime
    lat: float
    lon: float
    accuracy_m: float | None
    implausible: bool  # flagged for its position (implied speed)


def lookback(max_speed_mps: float) -> dt.timedelta:
    """How far back a previous point can matter: beyond this, no jump on Earth is too fast."""
    return dt.timedelta(seconds=math.ceil(HALF_CIRCUMFERENCE_M / max_speed_mps) + 1)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def _too_fast(a: Anchor, b: Fix, max_speed_mps: float) -> bool:
    slack = (a.accuracy_m or 0.0) + (b.accuracy_m or 0.0)
    moved = distance_m(a.lat, a.lon, b.lat, b.lon) - slack
    if moved <= 0:
        return False
    seconds = (b.ts - a.ts).total_seconds()
    return seconds <= 0 or moved / seconds > max_speed_mps


def flag(fixes: list[Fix], history: list[Anchor], max_speed_mps: float) -> list[list[str]]:
    """Flags for each fix. `fixes` are in time order with distinct times; `history` holds the
    device's stored points just before them, newest first."""
    previous = history[0] if history else None
    last_good = next((a for a in history if not a.implausible), None)
    result: list[list[str]] = []
    for fix in fixes:
        reasons = []
        if fix.speed_mps is not None and fix.speed_mps > max_speed_mps:
            reasons.append(REPORTED_SPEED)
        if previous is not None and _too_fast(previous, fix, max_speed_mps):
            # Plausible from the last good point: the previous one was the glitch.
            recovered = (
                last_good is not None
                and last_good is not previous
                and not _too_fast(last_good, fix, max_speed_mps)
            )
            if not recovered:
                reasons.append(IMPLIED_SPEED)
        result.append(reasons)
        anchor = Anchor(fix.ts, fix.lat, fix.lon, fix.accuracy_m, IMPLIED_SPEED in reasons)
        previous = anchor
        if not anchor.implausible:
            last_good = anchor
    return result
