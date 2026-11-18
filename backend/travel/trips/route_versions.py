"""Saving a leg's route as a new frozen version (docs/design/routing.md §13.2, CLAUDE.md rule 5).

Versions are only ever inserted: a trigger rejects UPDATE on `trips_route`, and nothing here
re-routes or rewrites one. Saving inserts the version, its simplified copies for the map's zoom
buckets (data-model.md `route_simplified`), and makes it the leg's current route.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.contrib.gis.geos import LineString, MultiLineString
from django.db import connection
from django.db.models import Max

from travel.core.choices import TravelMode

from .models import Leg, Route
from .services import guarded_write, invalid, touch

# Modes a car-profile road route fits (routing.md §13.1 profile "auto"). Flights get
# great-circle arcs, trains and boats their own lines later; walking needs another profile.
ROAD_MODES = frozenset({TravelMode.DRIVE, TravelMode.BUS, TravelMode.OTHER})

# Zoom bucket -> tolerance in degrees, about one 256-px tile pixel at that zoom (360 / 256 / 2^z).
SIMPLIFY_TOLERANCES = {3: 0.17, 6: 0.02, 9: 0.0027, 12: 0.00034}

_INSERT_SIMPLIFIED = """
INSERT INTO trips_routesimplified (route_id, zoom, geom)
SELECT r.id, z.zoom, ST_Multi(ST_SimplifyPreserveTopology(r.geom, z.tolerance))
FROM trips_route r, unnest(%s::smallint[], %s::float8[]) AS z(zoom, tolerance)
WHERE r.id = %s
"""


def _line(coordinates: list[list[float]]) -> MultiLineString:
    if len(coordinates) < 2:
        raise invalid("a route needs at least two points")
    for point in coordinates:
        if len(point) != 2 or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
            raise invalid("a route point is outside lon -180..180, lat -90..90")
    return MultiLineString(LineString([tuple(p) for p in coordinates]), srid=4326)


def _length_m(geom: MultiLineString) -> float:
    with connection.cursor() as cursor:
        cursor.execute("SELECT ST_Length(ST_GeomFromEWKB(%s)::geography)", [bytes(geom.ewkb)])
        (length,) = cursor.fetchone()
    return float(length or 0.0)


def control_points(waypoints: list[list[float]]) -> list[dict[str, Any]]:
    """The user's control points as stored on a version: {lon, lat, role}."""
    last = len(waypoints) - 1
    return [
        {"lon": lon, "lat": lat, "role": "start" if i == 0 else "end" if i == last else "via"}
        for i, (lon, lat) in enumerate(waypoints)
    ]


def save_route_version(
    user,
    leg: Leg,
    *,
    coordinates: list[list[float]],
    waypoints: list[list[float]],
    kind: str,
    provenance: dict[str, Any],
    produced_at: dt.datetime,
    note: str = "",
) -> Route:
    """Insert version n+1 of the leg's route and make it current. The caller has checked
    `policy.can_save_route_version`; RLS (`route_insert`, `leg_update`) checks it again."""
    if leg.mode not in ROAD_MODES:
        raise invalid("only drive, bus and other legs take a road route")
    geom = _line(coordinates)
    data_date = provenance.get("data_date")
    with guarded_write():
        # Serialise versions of this leg; the unique (leg, version) constraint backs it up.
        Leg.objects.select_for_update().filter(pk=leg.pk).first()
        latest = Route.objects.filter(leg=leg).aggregate(n=Max("version"))["n"] or 0
        route = Route.objects.create(
            leg=leg,
            version=latest + 1,
            geom=geom,
            kind=kind,
            waypoints=control_points(waypoints),
            engine=str(provenance.get("engine", ""))[:32],
            engine_version=str(provenance.get("engine_version", ""))[:32],
            engine_data_date=dt.date.fromisoformat(data_date) if data_date else None,
            attribution=str(provenance.get("attribution", ""))[:200],
            produced_at=produced_at,
            created_by=user,
            length_m=_length_m(geom),
            note=note,
        )
        zooms = list(SIMPLIFY_TOLERANCES)
        with connection.cursor() as cursor:
            cursor.execute(
                _INSERT_SIMPLIFIED,
                [zooms, [SIMPLIFY_TOLERANCES[z] for z in zooms], route.pk],
            )
        leg.current_route = route
        leg.distance_m = route.length_m
        leg.save(update_fields=["current_route", "distance_m", "updated_at"])
    if not leg.is_contribution:
        touch(leg.trip)
    return route
