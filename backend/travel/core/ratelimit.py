"""PostgreSQL-backed rate limiting (D-10, D-77): fixed-window counters, no Redis.

A limit is a scope (what is limited, e.g. "ingest-token") plus an identifier (who: a client
IP, a token *hash*, a user id) and a `Rate`. Each `hit` adds one to the counter for the current
window with a single atomic upsert and says whether the caller is still within the limit.

- Identifiers are never stored: the bucket key is the scope plus an HMAC of the identifier
  under the server's secret key, so a database dump reveals neither IPs nor tokens.
- Counters use their own database connection (alias `ratelimit`, autocommit), not the
  request's transaction. A count is final as soon as `hit` returns, even if the request later
  fails and rolls back, and the bucket's row lock lasts one statement, not a whole request.
- Expired buckets are deleted hourly by the `core.purge_rate_limits` task.

Use it from endpoints in one of two ways:

    @router.post("/thing", auth=None)
    @ratelimit.limit("thing", Rate(limit=10, period=60))  # keyed by client IP by default
    def thing(request): ...

    decision = ratelimit.enforce("ingest-token", token_hash, Rate(limit=120, period=60))

`limit` answers 429 itself; `enforce` raises `RateLimited`, which the API turns into a 429 with
`Retry-After` (see `install`). Tests that hit a limiter need
`@pytest.mark.django_db(databases=["default", "ratelimit"])`.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import connections
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac

if TYPE_CHECKING:
    from ninja import NinjaAPI

ALIAS = "ratelimit"
# Longest window allowed. Cleanup deletes buckets whose window started longer ago than this.
MAX_PERIOD = 86_400
# Lower-case words only, so a raw value (an IP, an email, a token) can't be passed as a scope.
SCOPE_PATTERN = re.compile(r"^[a-z][a-z-]{0,47}$")
_HMAC_SALT = "travel.core.ratelimit"

_UPSERT = """
INSERT INTO core_ratelimitbucket (key, window_start, count) VALUES (%s, %s, 1)
ON CONFLICT (key, window_start) DO UPDATE SET count = core_ratelimitbucket.count + 1
RETURNING count
"""


@dataclass(frozen=True)
class Rate:
    """At most `limit` requests per `period` seconds (fixed windows aligned to the epoch)."""

    limit: int
    period: int

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("a rate limit allows at least one request")
        if not 1 <= self.period <= MAX_PERIOD:
            raise ValueError(f"the period must be between 1 and {MAX_PERIOD} seconds")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    count: int  # requests counted in this window, including this one
    limit: int
    reset_at: dt.datetime  # when the window ends
    retry_after: int  # whole seconds until then (at least 1)


class RateLimited(Exception):
    def __init__(self, decision: Decision):
        super().__init__("rate limit exceeded")
        self.decision = decision


def bucket_key(scope: str, identifier: str) -> str:
    """`scope:` + HMAC-SHA256 of the identifier. Pass token hashes, never raw tokens; the HMAC
    is a second layer, not a licence to pass secrets."""
    if not SCOPE_PATTERN.match(scope):
        raise ValueError(f"invalid rate-limit scope {scope!r}")
    digest = salted_hmac(_HMAC_SALT, f"{scope}\0{identifier}", algorithm="sha256").hexdigest()
    return f"{scope}:{digest}"


def window_start(now: dt.datetime, period: int) -> dt.datetime:
    epoch = math.floor(now.timestamp())
    return dt.datetime.fromtimestamp(epoch - epoch % period, tz=dt.UTC)


def hit(scope: str, identifier: str, rate: Rate, *, now: dt.datetime | None = None) -> Decision:
    """Count one request and report whether it is within the limit. Requests over the limit
    are counted too, so a caller stays limited until the window ends."""
    now = now or timezone.now()
    start = window_start(now, rate.period)
    with connections[ALIAS].cursor() as cursor:
        cursor.execute(_UPSERT, [bucket_key(scope, identifier), start])
        (count,) = cursor.fetchone()
    reset_at = start + dt.timedelta(seconds=rate.period)
    return Decision(
        allowed=count <= rate.limit,
        count=count,
        limit=rate.limit,
        reset_at=reset_at,
        retry_after=max(1, math.ceil((reset_at - now).total_seconds())),
    )


def enforce(scope: str, identifier: str, rate: Rate, *, now: dt.datetime | None = None) -> Decision:
    """`hit`, raising `RateLimited` when over the limit."""
    decision = hit(scope, identifier, rate, now=now)
    if not decision.allowed:
        raise RateLimited(decision)
    return decision


def too_many_requests(decision: Decision) -> JsonResponse:
    response = JsonResponse({"detail": "too many requests"}, status=429)
    response["Retry-After"] = str(decision.retry_after)
    return response


def client_ip(request: HttpRequest) -> str:
    """The client's address for per-IP limits. Behind a proxy every request comes from the
    proxy, so `RATELIMIT_CLIENT_IP_HEADER` names the header carrying the real address (e.g.
    `CF-Connecting-IP`). Set it only when every request passes through that proxy: otherwise
    clients could choose their own bucket. IPv6 clients are grouped by /64, the block one
    subscriber usually gets."""
    raw = ""
    header = settings.RATELIMIT_CLIENT_IP_HEADER
    if header:
        raw = request.headers.get(header, "").split(",")[0].strip()
    raw = raw or request.META.get("REMOTE_ADDR", "")
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return "unknown"
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


def limit(
    scope: str, rate: Rate, key: Callable[[HttpRequest], str] = client_ip
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """View decorator (Django or Ninja; place it below the route decorator). Answers 429 with
    `Retry-After` once `key(request)` is over the limit."""
    bucket_key(scope, "")  # an invalid scope fails at import time, not on the first request

    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            decision = hit(scope, key(request), rate)
            if not decision.allowed:
                return too_many_requests(decision)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def install(api: NinjaAPI) -> None:
    """Make `RateLimited` raised inside an endpoint answer 429 with `Retry-After`."""

    def handler(_request: HttpRequest, exc: RateLimited) -> JsonResponse:
        return too_many_requests(exc.decision)

    api.add_exception_handler(RateLimited, handler)


def purge_expired(*, now: dt.datetime | None = None) -> int:
    """Delete buckets whose window is over, whatever their period. Returns the count."""
    cutoff = (now or timezone.now()) - dt.timedelta(seconds=MAX_PERIOD)
    with connections[ALIAS].cursor() as cursor:
        cursor.execute("DELETE FROM core_ratelimitbucket WHERE window_start < %s", [cutoff])
        return cursor.rowcount
