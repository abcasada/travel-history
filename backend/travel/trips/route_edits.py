"""Assembling a hand-edited route from the drag editor (docs/design/routing.md §13.4, D-93).

The editor sends the line as ordered pieces instead of one list of coordinates, so the server
can take as much of it as possible from data it already holds:

- `proposal`: a slice of the caller's own cached proposal for exactly these waypoints (the
  geometry the routing proxy returned; checked like `POST /legs/{id}/routes`);
- `version`: a slice of a saved version of the same leg (frozen, rule 5);
- `drawn`: coordinates from the client (an anchor clicked on the map, a straight span, or a
  proposal that expired before saving). Validated and recorded as unverified; an `engine` claim
  only adds that provider's credit from the server's own table, never free text.

The result is always labelled `hand_edited` unless it is exactly one whole proposal, and
`Route.sources` records which engines produced how many points and what was verified.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

from django.contrib.gis.geos import MultiLineString

from travel.routing import providers
from travel.routing import services as routing

from .models import Leg, Route
from .services import TripError, invalid

MAX_PIECES = 2_000
MAX_DRAWN_POINTS = 10_000  # client-supplied coordinates, all drawn pieces together
MAX_ROUTE_POINTS = 200_000  # the assembled line (a long map-matched drive can be large)
MAX_CONTROL_POINTS = 500
MAX_LENGTH_M = 20_000_000  # no single road leg is longer than half the equator
CLAIMABLE_ENGINES = (providers.VALHALLA, providers.ORS, providers.FOSSGIS)


class ProposalsExpired(TripError):
    """Some proposal pieces are no longer in the caller's cache (409). `pieces` are their
    positions in the request, so the editor can resend them as drawn pieces."""

    def __init__(self, pieces: list[int]):
        super().__init__(409, "some routed parts are older than the proposal cache")
        self.pieces = pieces


def check_point(point: list[float]) -> tuple[float, float]:
    if len(point) != 2:
        raise invalid("each point is [lon, lat]")
    lon, lat = float(point[0]), float(point[1])
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise invalid("a point is not a finite number")
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise invalid("a point is outside lon -180..180, lat -90..90")
    return lon, lat


@dataclass
class Assembled:
    coordinates: list[list[float]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    kind: str = Route.Kind.HAND_EDITED
    engine: str = ""
    engine_version: str = ""
    data_date: str | None = None
    attribution: str = ""
    # Set when the line is one whole proposal: its waypoints become the version's control points.
    proposal_waypoints: list[list[float]] | None = None


def _flatten(geom: MultiLineString) -> list[list[float]]:
    return [[x, y] for line in geom.coords for x, y in line]


def _slice(coords: list[list[float]], start: int, end: int, what: str) -> list[list[float]]:
    if not (0 <= start <= end < len(coords)):
        raise invalid(f"a {what} piece's range is outside its geometry")
    return coords[start : end + 1]


def _tally(sources: dict[tuple, dict[str, Any]], key: tuple, entry: dict, points: int) -> None:
    if key not in sources:
        sources[key] = {**entry, "points": 0}
    sources[key]["points"] += points


def assemble(user, leg: Leg, pieces: list[dict[str, Any]]) -> Assembled:
    """Build the edited line from `pieces` (dicts as validated by the API schema). Raises
    TripError 422 for invalid input and ProposalsExpired (409) for proposals no longer cached."""
    if not pieces or len(pieces) > MAX_PIECES:
        raise invalid(f"an edited route has 1-{MAX_PIECES} pieces")
    drawn_total = sum(len(p["coordinates"]) for p in pieces if p["source"] == "drawn")
    if drawn_total > MAX_DRAWN_POINTS:
        raise invalid(f"at most {MAX_DRAWN_POINTS} drawn points")

    proposals: dict[str, dict | None] = {}
    whole = False  # the line is exactly one complete proposal
    versions: dict[int, tuple[Route, list[list[float]]]] = {}
    expired: list[int] = []
    out = Assembled()
    tally: dict[tuple, dict[str, Any]] = {}
    attributions: list[str] = []
    engines: list[tuple[str, str, str | None]] = []

    def credit(text: str) -> None:
        if text and text not in attributions:
            attributions.append(text)

    for position, piece in enumerate(pieces):
        kind = piece["source"]
        if kind == "proposal":
            waypoints = [check_point(w) for w in piece["waypoints"]]
            key = routing.request_key(waypoints, "auto")
            if key not in proposals:
                proposals[key] = routing.cached_proposal(user, waypoints)
            proposal = proposals[key]
            if proposal is None:
                expired.append(position)
                continue
            geometry = proposal["routes"][0]["geometry"]["coordinates"]
            line = _slice(geometry, piece["start"], piece["end"], "proposal")
            whole = len(pieces) == 1 and len(line) == len(geometry)
            if whole:
                out.proposal_waypoints = [list(w) for w in waypoints]
            prov = proposal["provenance"]
            engine = (prov["engine"], prov.get("engine_version", ""), prov.get("data_date"))
            engines.append(engine)
            credit(prov.get("attribution", ""))
            _tally(
                tally,
                ("proposal", *engine),
                {
                    "source": "proposal",
                    "engine": engine[0],
                    "engine_version": engine[1],
                    "data_date": engine[2],
                    "verified": True,
                },
                len(line),
            )
        elif kind == "version":
            route_id = piece["route_id"]
            if route_id not in versions:
                # RLS has already limited what the caller sees; the leg check keeps the editor
                # to this leg's own history.
                route = Route.objects.filter(pk=route_id, leg=leg).first()
                if route is None:
                    raise invalid("unknown route version for this leg")
                versions[route_id] = (route, _flatten(route.geom))
            route, coords = versions[route_id]
            line = _slice(coords, piece["start"], piece["end"], "version")
            data_date = route.engine_data_date.isoformat() if route.engine_data_date else None
            if route.engine:
                engines.append((route.engine, route.engine_version, data_date))
            credit(route.attribution)
            _tally(
                tally,
                ("version", route.pk),
                {
                    "source": "version",
                    "route_id": route.pk,
                    "version": route.version,
                    "kind": route.kind,
                    "engine": route.engine,
                    "verified": True,
                },
                len(line),
            )
        elif kind == "drawn":
            line = [list(check_point(p)) for p in piece["coordinates"]]
            if not line:
                raise invalid("a drawn piece needs at least one point")
            claim = piece.get("engine") or ""
            if claim and claim not in CLAIMABLE_ENGINES:
                raise invalid("unknown routing engine")
            if claim:
                engines.append((claim, "", None))
                credit(providers.attribution(claim))
            _tally(
                tally,
                ("drawn", claim),
                {"source": "drawn", "engine": claim, "verified": False},
                len(line),
            )
        else:  # the schema allows nothing else
            raise invalid("unknown piece source")
        for point in line:
            if not out.coordinates or out.coordinates[-1] != point:
                out.coordinates.append(point)
        if len(out.coordinates) > MAX_ROUTE_POINTS:
            raise invalid(f"an edited route has at most {MAX_ROUTE_POINTS} points")

    if expired:
        raise ProposalsExpired(expired)
    if len(out.coordinates) < 2:
        raise invalid("a route needs at least two points")

    out.sources = list(tally.values())
    names = {e[0] for e in engines}
    if len(names) == 1:
        out.engine = names.pop()
        versions_of = {e[1] for e in engines if e[1]}
        out.engine_version = versions_of.pop() if len(versions_of) == 1 else ""
    elif names:
        out.engine = "mixed"
    dates = sorted(e[2] for e in engines if e[2])
    # The oldest road data in the line: the version is at least that old.
    out.data_date = dates[0] if dates else None
    out.attribution = "; ".join(attributions)[:200]
    if _length_m(out.coordinates) > MAX_LENGTH_M:
        raise invalid("an edited route is longer than any road leg can be")
    if whole:
        out.kind = Route.Kind.ROUTED
    return out


def _length_m(coords: list[list[float]]) -> float:
    """Haversine length, only for the sanity cap (the stored length comes from PostGIS)."""
    total = 0.0
    for (x1, y1), (x2, y2) in itertools.pairwise(coords):
        p1, p2 = math.radians(y1), math.radians(y2)
        a = (
            math.sin((p2 - p1) / 2) ** 2
            + math.cos(p1) * math.cos(p2) * math.sin(math.radians(x2 - x1) / 2) ** 2
        )
        total += 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(a)))
    return total
