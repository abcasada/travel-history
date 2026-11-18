"""Proposing a route (docs/design/routing.md §13.1, D-15; work-order item 25).

`propose_route` is the whole proxy: per-user throttle, the per-user cache of identical requests,
then the provider chain

1. Valhalla, when every waypoint is inside its coverage polygon;
2. OpenRouteService, when a key is configured (skipped cleanly otherwise), within the free
   plan's limits (40/min, 2,000/day, counted for the whole server);
3. FOSSGIS OSRM, the emergency fallback, at most one request per second for the whole server.

A provider that answers "no route" ends the chain: the next one would only see the same roads
(and get waypoints it didn't need). Proposals are never saved here; saving a version is
`travel.trips.services.save_route_version`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.utils import timezone

from travel.core import ratelimit
from travel.core.ratelimit import Rate

from . import providers
from .coverage import in_valhalla_coverage
from .models import RouteRequestCache
from .providers import NoRoute, Unavailable, Waypoint

USER_RATE = Rate(limit=10, period=10)  # routing.md §13.1: 10 requests / 10 s per user …
USER_BURST = Rate(limit=5, period=2)  # … in bursts of at most 5
ORS_RATE_MINUTE = Rate(limit=40, period=60)  # ORS free plan, whole server
ORS_RATE_DAY = Rate(limit=2000, period=86_400)
FOSSGIS_RATE = Rate(limit=1, period=1)  # FOSSGIS usage policy, whole server
SERVER = "server"  # rate-limit identifier for limits shared by every user


class RoutingFailed(Exception):
    """No provider could answer. `status` is the HTTP status for the API."""

    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


def request_key(waypoints: list[Waypoint], profile: str) -> str:
    canonical = json.dumps(
        {"v": 1, "profile": profile, "waypoints": [[round(x, 6), round(y, 6)] for x, y in waypoints]},
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _cached(user, key: str, now: dt.datetime) -> dict | None:
    row = RouteRequestCache.objects.filter(owner=user, key=key, expires_at__gt=now).first()
    return row.response if row else None


def _store(user, key: str, response: dict, now: dt.datetime) -> None:
    RouteRequestCache.objects.filter(owner=user, expires_at__lte=now).delete()
    RouteRequestCache.objects.update_or_create(
        owner=user,
        key=key,
        defaults={
            "response": response,
            "created_at": now,
            "expires_at": now + dt.timedelta(seconds=settings.ROUTING_CACHE_SECONDS),
        },
    )


def _within(scope: str, *rates: Rate) -> bool:
    return all(ratelimit.hit(scope, SERVER, rate).allowed for rate in rates)


def _chain(waypoints: list[Waypoint]) -> tuple[dict, providers.Provenance]:
    attempts: list[Callable[[], tuple[dict, providers.Provenance]]] = []
    if in_valhalla_coverage(waypoints):
        attempts.append(lambda: providers.valhalla(waypoints))
    if providers.ors_configured():

        def ors() -> tuple[dict, providers.Provenance]:
            if not (
                _within("routing-ors-minute", ORS_RATE_MINUTE)
                and _within("routing-ors-day", ORS_RATE_DAY)
            ):
                raise Unavailable("ORS plan limit")
            return providers.ors(waypoints)

        attempts.append(ors)
    for attempt in attempts:
        try:
            return attempt()
        except Unavailable:
            continue
    if not settings.ROUTING_FOSSGIS_ENABLED:
        raise RoutingFailed(503, "no routing service is available for these waypoints")
    decision = ratelimit.hit("routing-fossgis", SERVER, FOSSGIS_RATE)
    if not decision.allowed:
        raise RoutingFailed(
            503, "the fallback routing service is busy; try again", decision.retry_after
        )
    try:
        return providers.fossgis(waypoints)
    except Unavailable as error:
        raise RoutingFailed(503, "no routing service is available right now") from error


def propose_route(user, waypoints: list[Waypoint], profile: str = "auto") -> dict[str, Any]:
    """An OSRM-format proposal with `provenance` and `cached`. Raises `RateLimited` (429) when
    the user routes too fast, `RoutingFailed` otherwise."""
    ratelimit.enforce("routing-user", str(user.pk), USER_RATE)
    ratelimit.enforce("routing-burst", str(user.pk), USER_BURST)
    now = timezone.now()
    key = request_key(waypoints, profile)
    hit = _cached(user, key, now)
    if hit is not None:
        return {**hit, "cached": True}
    try:
        answer, provenance = _chain(waypoints)
    except NoRoute as error:
        raise RoutingFailed(422, "no road route connects these points") from error
    response = {**answer, "provenance": {**provenance.as_dict(), "produced_at": now.isoformat()}}
    _store(user, key, response, now)
    return {**response, "cached": False}


def cached_proposal(user, waypoints: list[Waypoint], profile: str = "auto") -> dict | None:
    """The user's unexpired proposal for exactly these waypoints, as `propose_route` returned
    it. Saving a version reads the geometry and provenance from here, never from the client."""
    return _cached(user, request_key(waypoints, profile), timezone.now())


def purge_expired_cache(user_id: int) -> int:
    """Per-user job body (`routing_cache`, travel/core/jobs.py): drop expired proposals."""
    deleted, _ = RouteRequestCache.objects.filter(
        owner_id=user_id, expires_at__lte=timezone.now()
    ).delete()
    return deleted
