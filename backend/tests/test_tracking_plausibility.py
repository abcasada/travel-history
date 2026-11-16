"""Plausibility flags (travel/tracking/plausibility.py), as pure functions. The endpoint tests
in test_tracking_ingest.py check the same rules end to end."""

import datetime as dt

import pytest

from travel.tracking.payloads import Fix
from travel.tracking.plausibility import (
    IMPLIED_SPEED,
    REPORTED_SPEED,
    Anchor,
    distance_m,
    flag,
    lookback,
)

T0 = dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.UTC)
# Synthetic places: Wichita, Topeka, Denver city centres.
A = (37.6922, -97.3375)
B = (39.0473, -95.6890)
C = (39.7392, -104.9903)
LIMIT = 400.0


def fix(place, minutes, accuracy=None, speed=None) -> Fix:
    return Fix(T0 + dt.timedelta(minutes=minutes), *place, accuracy_m=accuracy, speed_mps=speed)


def anchor(place, minutes, implausible=False) -> Anchor:
    return Anchor(T0 + dt.timedelta(minutes=minutes), *place, None, implausible)


def test_distances_are_great_circle_metres():
    assert distance_m(*A, *A) == 0
    assert distance_m(*A, *C) == pytest.approx(700_000, rel=0.05)


def test_lookback_covers_the_longest_possible_jump():
    assert lookback(LIMIT) > dt.timedelta(hours=13)
    assert lookback(LIMIT) < dt.timedelta(hours=14)


def test_a_spike_flags_only_itself():
    assert flag([fix(A, 0), fix(C, 1), fix(A, 2)], [], LIMIT) == [[], [IMPLIED_SPEED], []]


def test_a_bad_unjudged_fix_flags_one_good_point():
    """The first fix after a long gap is wrong but can't be judged; the next real fix is
    flagged once, and the fix after it is judged from that one."""
    history = [anchor(A, -600)]
    result = flag([fix(C, 0), fix(A, 1), fix(A, 2)], history, LIMIT)
    assert result == [[], [IMPLIED_SPEED], []]


def test_history_counts_and_its_flags_are_respected():
    # Stored: A good, then C flagged as a spike. The new fix near A is fine.
    history = [anchor(C, -1, implausible=True), anchor(A, -2)]
    assert flag([fix(A, 0)], history, LIMIT) == [[]]


def test_accuracy_gives_slack():
    assert flag([fix(A, 0, accuracy=400_000), fix(C, 1, accuracy=400_000)], [], LIMIT) == [[], []]


def test_reported_speed_is_flagged_on_its_own():
    assert flag([fix(A, 0, speed=401)], [], LIMIT) == [[REPORTED_SPEED]]
    assert flag([fix(A, 0, speed=399)], [], LIMIT) == [[]]


def test_fast_but_possible_travel_passes():
    # A -> C by plane: ~700 km in 90 minutes is about 130 m/s.
    assert flag([fix(A, 0), fix(C, 90)], [], LIMIT) == [[], []]
