"""Valhalla coverage polygon (docs/design/routing.md §13.1, §13.5; work-order item 17)."""

import json

import pytest

from travel.routing import coverage
from travel.routing.management.commands.valhalla_smoke import synthetic_track

# Public town centres (lon, lat).
WICHITA = (-97.3301, 37.6872)
SALINA = (-97.6114, 38.8403)
DODGE_CITY = (-100.0171, 37.7528)
LEAVENWORTH = (-94.9225, 39.3111)
ST_JOSEPH_MO = (-94.8466, 39.7675)
KANSAS_CITY_MO = (-94.5786, 39.0997)
DENVER = (-104.9903, 39.7392)
OMAHA = (-95.9345, 41.2565)


@pytest.fixture(autouse=True)
def _kansas(settings):
    settings.VALHALLA_COVERAGE = "kansas"


def test_kansas_towns_are_covered():
    assert coverage.in_valhalla_coverage([WICHITA, SALINA, DODGE_CITY, LEAVENWORTH])


@pytest.mark.parametrize("outside", [ST_JOSEPH_MO, KANSAS_CITY_MO, DENVER, OMAHA])
def test_any_waypoint_outside_sends_the_request_elsewhere(outside):
    assert not coverage.in_valhalla_coverage([WICHITA, outside])


def test_no_waypoints_is_not_covered():
    assert not coverage.in_valhalla_coverage([])


def test_coverage_file_can_be_swapped_by_path(settings, tmp_path):
    square = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    path = tmp_path / "square.geojson"
    path.write_text(json.dumps(square))
    settings.VALHALLA_COVERAGE = str(path)
    assert coverage.in_valhalla_coverage([(0.5, 0.5)])
    assert not coverage.in_valhalla_coverage([WICHITA])


def test_synthetic_track_is_evenly_spaced_and_timed():
    line = [[-97.0, 38.0], [-97.0, 38.01]]  # about 1.1 km north
    track = synthetic_track(line, spacing_m=100, jitter_m=0)
    assert len(track) == 12
    assert [p["time"] - track[0]["time"] for p in track[:3]] == [0, 4, 8]
