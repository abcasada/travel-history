"""Routing providers behind `/api/v1/routing/route` (docs/design/routing.md §13.1, D-15).

Each provider takes only the user-drawn waypoints and returns one OSRM-shaped answer:

    {"code": "Ok", "routes": [{"geometry": <GeoJSON LineString>, "distance": m, "duration": s,
      "legs": [{"distance", "duration", "summary"}]}], "waypoints": [{"location", "name"}]}

plus a `Provenance`. Nothing else leaves the server: no user identity, no history, no cookies,
no Referer (standing rule 13; ORS terms, Q-9). Outbound requests are built here and only here.

- `Unavailable`: the provider is down, refused, misconfigured or over its limit; the chain
  tries the next one.
- `NoRoute`: the provider answered that these waypoints can't be routed; that is the answer.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Any

import polyline
import requests
from django.conf import settings

Waypoint = tuple[float, float]  # (lon, lat)

VALHALLA = "valhalla"
ORS = "ors"
FOSSGIS = "osrm-fossgis"

ATTRIBUTION = {
    VALHALLA: "Route: Valhalla, data © OpenStreetMap contributors",
    ORS: "© openrouteservice by HeiGIT, data © OpenStreetMap",
    FOSSGIS: "Route: FOSSGIS OSRM (routing.openstreetmap.de), data © OpenStreetMap contributors",
}
# The FOSSGIS service asks users to fix the map where a route is wrong (licenses.md §27).
FIX_THE_MAP_URL = "https://www.openstreetmap.org/fixthemap"


def attribution(engine: str) -> str:
    return ATTRIBUTION.get(engine, "")


@dataclass(frozen=True)
class Provenance:
    engine: str
    engine_version: str
    data_date: dt.date | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "engine_version": self.engine_version,
            "data_date": self.data_date.isoformat() if self.data_date else None,
            "attribution": attribution(self.engine),
        }


class Unavailable(Exception):
    """Try the next provider."""


class NoRoute(Exception):
    """The provider answered, and there is no route between these waypoints."""


def _coord(value: float) -> float:
    # About 0.1 m: enough for routing, and nothing finer than the user drew.
    return round(float(value), 6)


def _headers(**extra: str) -> dict[str, str]:
    # Every outbound header is listed here; requests adds only Accept-Encoding and Connection.
    return {"User-Agent": settings.ROUTING_USER_AGENT, "Accept": "application/json", **extra}


def _timeout() -> float:
    return settings.ROUTING_TIMEOUT


def _post(url: str, body: dict, headers: dict[str, str]) -> requests.Response:
    try:
        return requests.post(url, json=body, headers=headers, timeout=_timeout())
    except requests.RequestException as error:
        raise Unavailable(type(error).__name__) from error


def _get(url: str, headers: dict[str, str], params: dict | None = None) -> requests.Response:
    try:
        return requests.get(url, params=params, headers=headers, timeout=_timeout())
    except requests.RequestException as error:
        raise Unavailable(type(error).__name__) from error


def _json(response: requests.Response) -> dict:
    try:
        data = response.json()
    except ValueError as error:
        raise Unavailable("invalid JSON") from error
    if not isinstance(data, dict):
        raise Unavailable("unexpected answer")
    return data


def _osrm_route(route: dict) -> dict:
    """Keep the OSRM fields the app uses; drop provider extras (admins, weights, steps)."""
    geometry = route.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        raise Unavailable("route without a GeoJSON line")
    coords = [[_coord(c[0]), _coord(c[1])] for c in geometry.get("coordinates", [])]
    if len(coords) < 2:
        raise Unavailable("route with fewer than two points")
    return {
        "geometry": {"type": "LineString", "coordinates": coords},
        "distance": float(route.get("distance", 0.0)),
        "duration": float(route.get("duration", 0.0)),
        "legs": [
            {
                "distance": float(leg.get("distance", 0.0)),
                "duration": float(leg.get("duration", 0.0)),
                "summary": str(leg.get("summary", "")),
            }
            for leg in route.get("legs", [])
        ],
    }


def _osrm_waypoints(raw: list[dict]) -> list[dict]:
    return [
        {
            "location": [_coord(w["location"][0]), _coord(w["location"][1])],
            "name": str(w.get("name", "")),
        }
        for w in raw
    ]


def normalize_osrm(data: dict) -> dict:
    """An OSRM(-format) answer from Valhalla or FOSSGIS, reduced to the shared shape."""
    if data.get("code") != "Ok" or not data.get("routes"):
        raise NoRoute(str(data.get("code", "NoRoute")))
    return {
        "code": "Ok",
        "routes": [_osrm_route(data["routes"][0])],
        "waypoints": _osrm_waypoints(data.get("waypoints", [])),
    }


# --- Valhalla (self-hosted) ------------------------------------------------------------------

_STATUS_TTL = 300.0
_status_cache: dict[str, tuple[float, Provenance]] = {}


def valhalla_provenance() -> Provenance:
    """Version and data date from `/status` (cached for 5 minutes). The data date is
    VALHALLA_DATA_DATE (the OSM extract's date) when set, else the tile build time."""
    url = settings.VALHALLA_URL.rstrip("/")
    cached = _status_cache.get(url)
    now = time.monotonic()
    if cached and now - cached[0] < _STATUS_TTL:
        return cached[1]
    version, data_date = "", None
    try:
        status = requests.get(f"{url}/status", headers=_headers(), timeout=5).json()
        version = str(status.get("version", ""))
        built = status.get("tileset_last_modified")
        if isinstance(built, int | float):
            data_date = dt.datetime.fromtimestamp(built, tz=dt.UTC).date()
    except (requests.RequestException, ValueError, AttributeError):
        pass  # provenance is best effort; the route itself already came back
    if settings.VALHALLA_DATA_DATE:
        data_date = dt.date.fromisoformat(settings.VALHALLA_DATA_DATE)
    result = Provenance(VALHALLA, version, data_date)
    _status_cache[url] = (now, result)
    return result


def valhalla(waypoints: list[Waypoint]) -> tuple[dict, Provenance]:
    body = {
        "locations": [{"lon": _coord(lon), "lat": _coord(lat)} for lon, lat in waypoints],
        "costing": "auto",
        "format": "osrm",
        "shape_format": "geojson",
        "narrative": False,
    }
    response = _post(f"{settings.VALHALLA_URL.rstrip('/')}/route", body, _headers())
    if response.status_code >= 500 or response.status_code in (401, 403, 429):
        raise Unavailable(f"valhalla {response.status_code}")
    data = _json(response)
    if response.status_code >= 400:
        # Valhalla answers 400 with an OSRM code ("NoRoute", "NoSegment") for unroutable input.
        raise NoRoute(str(data.get("code", "NoRoute")))
    return normalize_osrm(data), valhalla_provenance()


# --- OpenRouteService (hosted) ---------------------------------------------------------------


def ors_configured() -> bool:
    return bool(settings.ORS_API_KEY)


def _ors_date(value: Any) -> dt.date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def ors(waypoints: list[Waypoint]) -> tuple[dict, Provenance]:
    """`driving-car` directions. The key goes in the Authorization header; the body holds only
    the waypoints. The encoded polyline (precision 5) is decoded into a GeoJSON line."""
    if not ors_configured():
        raise Unavailable("no ORS key")
    body = {
        "coordinates": [[_coord(lon), _coord(lat)] for lon, lat in waypoints],
        "instructions": False,
    }
    url = f"{settings.ORS_URL.rstrip('/')}/v2/directions/driving-car"
    response = _post(url, body, _headers(Authorization=settings.ORS_API_KEY))
    data = _json(response) if response.content else {}
    error = data.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    # 2004 too far for the service, 2009 route not found, 2010 a point not near a road.
    if response.status_code == 404 or code in (2004, 2009, 2010):
        raise NoRoute("NoRoute")
    if response.status_code != 200:
        raise Unavailable(f"ors {response.status_code}")
    routes = data.get("routes") or []
    if not routes:
        raise NoRoute("NoRoute")
    route = routes[0]
    try:
        line = [[lon, lat] for lat, lon in polyline.decode(route["geometry"], 5)]
    except (KeyError, TypeError, ValueError) as error:
        raise Unavailable("ors geometry") from error
    summary = route.get("summary", {})
    way_points = route.get("way_points", [])
    normalized = normalize_osrm(
        {
            "code": "Ok",
            "routes": [
                {
                    "geometry": {"type": "LineString", "coordinates": line},
                    "distance": summary.get("distance", 0.0),
                    "duration": summary.get("duration", 0.0),
                    "legs": [
                        {"distance": s.get("distance", 0.0), "duration": s.get("duration", 0.0)}
                        for s in route.get("segments", [])
                    ],
                }
            ],
            "waypoints": [
                {"location": line[i], "name": ""} for i in way_points if 0 <= i < len(line)
            ],
        }
    )
    engine = data.get("metadata", {}).get("engine", {})
    return normalized, Provenance(
        ORS, str(engine.get("version", "")), _ors_date(engine.get("graph_date"))
    )


# --- FOSSGIS OSRM (emergency) ----------------------------------------------------------------


def fossgis(waypoints: list[Waypoint]) -> tuple[dict, Provenance]:
    """routing.openstreetmap.de, car profile. The caller enforces the global 1 request/s."""
    coords = ";".join(f"{_coord(lon)},{_coord(lat)}" for lon, lat in waypoints)
    url = f"{settings.FOSSGIS_OSRM_URL.rstrip('/')}/route/v1/driving/{coords}"
    params = {"overview": "full", "geometries": "geojson", "steps": "false"}
    response = _get(url, _headers(), params)
    if response.status_code >= 500 or response.status_code == 429:
        raise Unavailable(f"fossgis {response.status_code}")
    data = _json(response)
    if response.status_code >= 400 and data.get("code") not in ("NoRoute", "NoSegment"):
        raise Unavailable(f"fossgis {response.status_code}")
    return normalize_osrm(data), Provenance(FOSSGIS, "", None)
