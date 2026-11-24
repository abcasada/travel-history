"""Offline reverse geocoding (statistics.md §15.1, milestone 6.1, D-20, D-112): which country,
state/region and US county a point is in, and the town it is near, from the boundary tables
and the GeoNames gazetteer in PostGIS. Nothing leaves the server (rule 13).

    reverse_geocode(-97.33, 37.69).label  ->  "near Wichita, Kansas, United States"

Runs as any role: the `geo_` tables are readable by the app role.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from django.db import connection

# A town counts as "near" within this distance (statistics.md §15.1).
PLACE_RADIUS_M = 25_000
# Natural Earth's 1:10m coastlines are off by up to a few hundred metres, so a point on a beach
# or a pier can fall just outside every country; the nearest boundary within this distance
# counts as the one it is in.
BOUNDARY_SLACK_M = 2_000
# Neighbourhoods (PPLX) and abandoned, historical or destroyed places name no town.
NOT_TOWNS = ("PPLX", "PPLQ", "PPLH", "PPLW", "PPLCH")
METRES_PER_DEGREE = 111_320.0


@dataclass(frozen=True)
class Area:
    code: str  # ISO 3166-1 alpha-2, ISO 3166-2, or the county's 5-digit GEOID
    name: str


@dataclass(frozen=True)
class NearbyPlace:
    geonameid: int
    name: str
    admin1_name: str
    country_code: str
    country_name: str
    population: int
    distance_m: float


@dataclass(frozen=True)
class ReverseGeocode:
    country: Area | None
    region: Area | None
    region_geonames_id: int | None
    county: Area | None
    place: NearbyPlace | None
    label: str  # "" when nothing is known (open sea)


def _degrees(metres: float, lat: float) -> tuple[float, float]:
    """Half-sizes (lon, lat) in degrees of a box that holds a circle of `metres`."""
    dlat = metres / METRES_PER_DEGREE * 1.01
    cos = math.cos(math.radians(lat))
    dlon = 180.0 if cos < 0.01 else min(180.0, dlat / cos)
    return dlon, dlat


def _envelopes(lon: float, lat: float, metres: float) -> list[tuple[float, float, float, float]]:
    """Boxes (xmin, ymin, xmax, ymax) covering the circle, split at the antimeridian so the
    GiST index can still answer for points near ±180° (Fiji, the Aleutians)."""
    dlon, dlat = _degrees(metres, lat)
    ymin, ymax = max(-90.0, lat - dlat), min(90.0, lat + dlat)
    if dlon >= 180.0:
        return [(-180.0, ymin, 180.0, ymax)]
    xmin, xmax = lon - dlon, lon + dlon
    boxes = [(max(-180.0, xmin), ymin, min(180.0, xmax), ymax)]
    if xmin < -180.0:
        boxes.append((xmin + 360.0, ymin, 180.0, ymax))
    if xmax > 180.0:
        boxes.append((-180.0, ymin, xmax - 360.0, ymax))
    return boxes


def nearest_place(lon: float, lat: float, radius_m: float = PLACE_RADIUS_M) -> NearbyPlace | None:
    """The town a point is near: among GeoNames places within `radius_m`, the lowest
    distance / (1 + log10(1 + population)), so a city a little farther away beats a hamlet
    next door, but a village beats a city twice the radius off (D-112)."""
    boxes = _envelopes(lon, lat, radius_m)
    in_boxes = " OR ".join(["p.point && ST_MakeEnvelope(%s, %s, %s, %s, 4326)"] * len(boxes))
    params: list[object] = [lon, lat]
    for box in boxes:
        params.extend(box)
    params.extend([list(NOT_TOWNS), radius_m])
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH here AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS g)
            SELECT geonameid, name, admin1_name, country_code, country_name, population, d
              FROM (
                SELECT p.*, ST_Distance(p.point::geography, here.g) AS d
                  FROM geo_geonamesplace p, here
                 WHERE ({in_boxes})
                   AND p.feature_code <> ALL(%s)
              ) candidates
             WHERE d <= %s
             ORDER BY d / (1 + log(1 + greatest(population, 0))), d, geonameid
             LIMIT 1
            """,  # noqa: S608 (only placeholders are interpolated)
            params,
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return NearbyPlace(
        geonameid=row[0],
        name=row[1],
        admin1_name=row[2],
        country_code=row[3],
        country_name=row[4],
        population=row[5],
        distance_m=float(row[6]),
    )


def _containing(table: str, columns: str, lon: float, lat: float) -> tuple | None:
    """The row of `table` whose polygon holds the point (the smallest, where polygons overlap),
    else the nearest one within BOUNDARY_SLACK_M."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {columns} FROM {table}
             WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
             ORDER BY ST_Area(geom), id
             LIMIT 1
            """,  # noqa: S608 (table and columns are constants in this module)
            [lon, lat],
        )
        row = cursor.fetchone()
        if row is not None:
            return row
        dlon, _ = _degrees(BOUNDARY_SLACK_M, lat)
        cursor.execute(
            f"""
            WITH here AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS g)
            SELECT {columns} FROM (
              SELECT t.*, ST_Distance(t.geom::geography, here.g::geography) AS d
                FROM {table} t, here
               WHERE ST_DWithin(t.geom, here.g, %s)
            ) near
             WHERE d <= %s
             ORDER BY d, id
             LIMIT 1
            """,  # noqa: S608
            [lon, lat, dlon, BOUNDARY_SLACK_M],
        )
        return cursor.fetchone()


def _label(country: Area | None, region: Area | None, place: NearbyPlace | None) -> str:
    """ "near <town>, <its state>, <its country>"; without a town, "<state>, <country>" from
    the boundaries. Parts that repeat the one before (Singapore, Singapore) are dropped."""
    if place is not None:
        parts = [place.name, place.admin1_name, place.country_name or (country and country.name)]
        prefix = "near "
    else:
        parts = [region and region.name, country and country.name]
        prefix = ""
    kept: list[str] = []
    for part in parts:
        if part and (not kept or part != kept[-1]):
            kept.append(part)
    return prefix + ", ".join(kept) if kept else ""


def reverse_geocode(lon: float, lat: float) -> ReverseGeocode:
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        raise ValueError(f"not a WGS 84 coordinate: {lon}, {lat}")
    country_row = _containing("geo_country", "iso_a2, name", lon, lat)
    region_row = _containing("geo_region", "iso_3166_2, name, geonames_id", lon, lat)
    county_row = _containing(
        "geo_uscounty", "geoid, coalesce(nullif(name_lsad, ''), name)", lon, lat
    )
    country = Area(*country_row) if country_row else None
    region = Area(region_row[0], region_row[1]) if region_row else None
    county = Area(*county_row) if county_row else None
    place = nearest_place(lon, lat)
    return ReverseGeocode(
        country=country,
        region=region,
        region_geonames_id=region_row[2] if region_row else None,
        county=county,
        place=place,
        label=_label(country, region, place),
    )
