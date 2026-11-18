"""Where the self-hosted Valhalla has road data (docs/design/routing.md §13.1, §13.5).

The routing proxy (work-order item 25) sends a request to Valhalla only when every waypoint is
inside this polygon; anything else goes to the fallback providers. The polygon file is chosen by
the VALHALLA_COVERAGE setting (a name in ./coverage/ or a path), so swapping Kansas for North
America later is a new file plus a setting, not a code change.
"""

import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, Point
from django.contrib.gis.geos.prepared import PreparedGeometry

COVERAGE_DIR = Path(__file__).resolve().parent / "coverage"


def coverage_path(name: str | None = None) -> Path:
    value = name or settings.VALHALLA_COVERAGE
    path = Path(value)
    if path.suffix != ".geojson":
        path = COVERAGE_DIR / f"{value}.geojson"
    return path


@cache
def _prepared(path: Path) -> PreparedGeometry:
    data = json.loads(path.read_text())
    geometry = data.get("geometry", data)  # a Feature or a bare geometry
    geom = GEOSGeometry(json.dumps(geometry), srid=4326)
    if geom.geom_type not in ("Polygon", "MultiPolygon") or not geom.valid:
        raise ValueError(f"{path} is not a valid (multi)polygon")
    return geom.prepared


def valhalla_coverage() -> PreparedGeometry:
    return _prepared(coverage_path())


def in_valhalla_coverage(waypoints: Iterable[tuple[float, float]]) -> bool:
    """True when every [lon, lat] waypoint lies inside the coverage polygon (and there is one)."""
    coverage = valhalla_coverage()
    points = [Point(float(lon), float(lat), srid=4326) for lon, lat in waypoints]
    return bool(points) and all(coverage.covers(p) for p in points)
