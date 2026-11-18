"""`/api/v1/routing/*`: the only way the frontend gets a road route (docs/design/routing.md §13.1).

The browser never talks to a routing provider. This proxy throttles per user, caches identical
requests, picks the provider (Valhalla inside its coverage, then ORS, then FOSSGIS) and answers
in OSRM format with the provenance and attribution a saved version records. Proposals are not
saved here: `POST /legs/{leg_id}/routes` (trips API) saves one as a frozen version.
"""

from __future__ import annotations

from typing import Literal

from django.http import HttpRequest, JsonResponse
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from pydantic import field_validator

from travel.core import policy

from . import services

router = Router(tags=["routing"])

MAX_WAYPOINTS = 25


class RouteRequestIn(Schema):
    waypoints: list[list[float]] = Field(
        min_length=2,
        max_length=MAX_WAYPOINTS,
        description="[lon, lat] pairs in order, 2-25; only these points leave the server",
    )
    profile: Literal["auto"] = "auto"

    @field_validator("waypoints")
    @classmethod
    def _check(cls, value: list[list[float]]) -> list[list[float]]:
        for point in value:
            if len(point) != 2:
                raise ValueError("each waypoint is [lon, lat]")
            lon, lat = point
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError("a waypoint is outside lon -180..180, lat -90..90")
        return value


class RouteGeometry(Schema):
    type: Literal["LineString"]
    coordinates: list[list[float]]


class RouteLegOut(Schema):
    distance: float = Field(description="metres")
    duration: float = Field(description="seconds")
    summary: str


class ProposedRoute(Schema):
    geometry: RouteGeometry
    distance: float = Field(description="metres")
    duration: float = Field(description="seconds")
    legs: list[RouteLegOut]


class SnappedWaypoint(Schema):
    location: list[float] = Field(description="[lon, lat] on the road network")
    name: str


class RouteProvenance(Schema):
    engine: str = Field(description="valhalla, ors or osrm-fossgis")
    engine_version: str
    data_date: str | None = Field(description="YYYY-MM-DD of the road data, when known")
    attribution: str = Field(description="must be shown wherever this route is drawn")
    produced_at: str


class RouteProposalOut(Schema):
    code: Literal["Ok"]
    routes: list[ProposedRoute]
    waypoints: list[SnappedWaypoint]
    provenance: RouteProvenance
    cached: bool = Field(description="served from the 10-minute cache of identical requests")


class RoutingErrorOut(Schema):
    detail: str


@router.post(
    "/routing/route",
    response={200: RouteProposalOut, 503: RoutingErrorOut},
    operation_id="proposeRoute",
)
def propose_route(request: HttpRequest, payload: RouteRequestIn):
    """Propose a road route through the waypoints (not saved). 429 with Retry-After when the
    caller routes too fast; 422 when no road connects the points; 503 when no provider can
    answer (Retry-After when the fallback is only busy)."""
    if not policy.can_propose_route(request.user):
        raise HttpError(403, "your account can't create routes")
    waypoints = [(float(lon), float(lat)) for lon, lat in payload.waypoints]
    try:
        return services.propose_route(request.user, waypoints, payload.profile)
    except services.RoutingFailed as error:
        response = JsonResponse({"detail": error.message}, status=error.status)
        if error.retry_after:
            response["Retry-After"] = str(error.retry_after)
        return response
