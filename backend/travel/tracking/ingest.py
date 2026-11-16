"""Tracker ingestion service (PLAN.md §9.1): resolve a device token, store its points.

Runs inside the request's transaction (RlsContextMiddleware). The token is looked up in the
narrow `ingest` context, which can read device-token rows and nothing else (D-51); everything
after that runs as the token's owner, so row-level security limits the writes to the owner's
own history, and history migration 0009 also requires the owner's unrevoked token on every
tracker point. Nothing else happens on the request path: coverage, detection and home
suggestions run later in the worker.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.models import F
from django.utils import timezone

from travel.accounts.models import DeviceToken, User
from travel.core import policy
from travel.core.rls import set_context
from travel.history.models import PointSource

from . import plausibility
from .payloads import Fix

log = logging.getLogger(__name__)

OWNTRACKS = "owntracks"
OVERLAND = "overland"

# Which token kinds each endpoint takes (a token is made for one tracker app).
ENDPOINT_KINDS = {
    OWNTRACKS: frozenset(
        {
            DeviceToken.Kind.OWNTRACKS,
            DeviceToken.Kind.GPSLOGGER,
            DeviceToken.Kind.COLOTA,
            DeviceToken.Kind.GENERIC,
        }
    ),
    OVERLAND: frozenset(
        {DeviceToken.Kind.OVERLAND, DeviceToken.Kind.COLOTA, DeviceToken.Kind.GENERIC}
    ),
}
SOURCE_BY_KIND = {
    DeviceToken.Kind.OWNTRACKS: PointSource.OWNTRACKS,
    DeviceToken.Kind.OVERLAND: PointSource.OVERLAND,
    DeviceToken.Kind.GPSLOGGER: PointSource.GPSLOGGER,
    DeviceToken.Kind.COLOTA: PointSource.COLOTA,
    DeviceToken.Kind.GENERIC: PointSource.OTHER,
}

# Points outside this window are refused and counted (§9.1), not stored.
EARLIEST = dt.datetime(2000, 1, 1, tzinfo=dt.UTC)
FUTURE_SLACK = dt.timedelta(days=1)
HISTORY_POINTS = 20
RLS_VIOLATION = "42501"  # insufficient_privilege: a row policy's WITH CHECK failed


class TokenRefused(Exception):
    """Unknown, malformed, revoked, wrong endpoint, or an owner who may not record history.
    The tracker gets the same answer for each."""


@dataclass
class Outcome:
    received: int = 0
    stored: int = 0
    duplicates: int = 0
    out_of_window: int = 0
    flagged: int = 0


def resolve(token_hash: str, endpoint: str) -> DeviceToken:
    """The live token for this hash, with the request now acting as its owner."""
    set_context(None, "ingest")
    row = (
        DeviceToken.objects.filter(token_hash=token_hash)
        .values("id", "user_id", "kind", "revoked_at")
        .first()
    )
    set_context(None)
    if row is None or row["revoked_at"] is not None or row["kind"] not in ENDPOINT_KINDS[endpoint]:
        raise TokenRefused
    set_context(row["user_id"])
    # Both reads go through the owner's own policies: an inactive account sees neither.
    user = User.objects.filter(pk=row["user_id"]).first()
    token = DeviceToken.objects.filter(pk=row["id"]).first()
    if user is None or token is None or not policy.can_ingest_points(user, token):
        set_context(None)
        raise TokenRefused
    return token


INSERT_SQL = """
    INSERT INTO history_locationpoint
        (owner_id, ts, geom, accuracy_m, altitude_m, speed_mps, course_deg, battery_pct,
         source, device_id, received_at, extra)
    SELECT %s, u.ts, ST_SetSRID(ST_MakePoint(u.lon, u.lat), 4326), u.acc, u.alt, u.spd, u.cog,
           u.batt, %s, %s, now(), u.extra::jsonb
    FROM unnest(%s::timestamptz[], %s::float8[], %s::float8[], %s::float8[], %s::float8[],
                %s::float8[], %s::float8[], %s::int2[], %s::text[])
         AS u(ts, lat, lon, acc, alt, spd, cog, batt, extra)
    ON CONFLICT ON CONSTRAINT point_dedupe DO NOTHING
"""

HISTORY_SQL = """
    SELECT ts, ST_Y(geom), ST_X(geom), accuracy_m,
           coalesce(extra -> 'flags' ? %s, false)
    FROM history_locationpoint
    WHERE owner_id = %s AND device_id = %s AND ts < %s AND ts >= %s
    ORDER BY ts DESC
    LIMIT %s
"""


def store(token: DeviceToken, fixes: list[Fix], *, now: dt.datetime | None = None) -> Outcome:
    """Insert the fixes as the token owner's points in one statement; duplicates (same owner,
    source, device and time) are dropped by the unique constraint."""
    now = now or timezone.now()
    outcome = Outcome(received=len(fixes))
    by_time: dict[dt.datetime, Fix] = {}
    for fix in fixes:
        if not EARLIEST <= fix.ts <= now + FUTURE_SLACK:
            outcome.out_of_window += 1
        else:
            by_time.setdefault(fix.ts, fix)
    batch = [by_time[ts] for ts in sorted(by_time)]
    if batch:
        max_speed = settings.TRACKER_MAX_SPEED_MPS
        history = _history(token, batch[0].ts, max_speed)
        flags = plausibility.flag(batch, history, max_speed)
        outcome.flagged = sum(1 for reasons in flags if reasons)
        outcome.stored = _insert(token, batch, flags)
    outcome.duplicates = outcome.received - outcome.out_of_window - outcome.stored
    DeviceToken.objects.filter(pk=token.pk).update(
        last_used_at=now, points_received=F("points_received") + outcome.stored
    )
    return outcome


def _history(token: DeviceToken, before: dt.datetime, max_speed: float) -> list:
    since = before - plausibility.lookback(max_speed)
    with connection.cursor() as cursor:
        cursor.execute(
            HISTORY_SQL,
            [plausibility.IMPLIED_SPEED, token.user_id, token.pk, before, since, HISTORY_POINTS],
        )
        return [plausibility.Anchor(*row) for row in cursor.fetchall()]


def _insert(token: DeviceToken, batch: list[Fix], flags: list[list[str]]) -> int:
    columns = [
        [f.ts for f in batch],
        [f.lat for f in batch],
        [f.lon for f in batch],
        [f.accuracy_m for f in batch],
        [f.altitude_m for f in batch],
        [f.speed_mps for f in batch],
        [f.course_deg for f in batch],
        [f.battery_pct for f in batch],
        [json.dumps({"flags": reasons}) if reasons else None for reasons in flags],
    ]
    params = [token.user_id, SOURCE_BY_KIND[token.kind], token.pk, *columns]
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(INSERT_SQL, params)
            return cursor.rowcount
    except DatabaseError as error:
        if getattr(error.__cause__, "sqlstate", None) != RLS_VIOLATION:
            raise
        # Row-level security refused the write: the token was revoked (or its owner lost the
        # right to record history) after it was resolved. Same answer as any refused token.
        log.warning("ingest refused by row-level security for device %s", token.pk)
        raise TokenRefused from None
