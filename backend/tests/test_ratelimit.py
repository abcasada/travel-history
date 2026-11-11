"""PostgreSQL-backed rate limiter (D-10, D-77): fixed windows, atomic upserts on a dedicated
autocommit connection, hashed keys, cleanup, and the Ninja integration. The concurrency test
uses real parallel PostgreSQL connections (one per thread), not mocks."""

import datetime as dt
import threading

import pytest
from django.db import connections, transaction
from django.test import RequestFactory

from travel.core import ratelimit
from travel.core.models import RateLimitBucket
from travel.core.ratelimit import MAX_PERIOD, Rate, RateLimited
from travel.core.tasks import purge_rate_limits

LIMITER_DB = pytest.mark.django_db(databases=["default", "ratelimit"])
NOW = dt.datetime(2026, 3, 14, 15, 9, 26, tzinfo=dt.UTC)  # 26 s into a 60 s window


def stored_keys() -> list[str]:
    with connections["ratelimit"].cursor() as cursor:
        cursor.execute("SELECT key FROM core_ratelimitbucket ORDER BY key")
        return [row[0] for row in cursor.fetchall()]


# --- Pure parts ------------------------------------------------------------------------------


@pytest.mark.parametrize(("limit", "period"), [(0, 60), (1, 0), (1, MAX_PERIOD + 1)])
def test_rate_rejects_nonsense(limit, period):
    with pytest.raises(ValueError):
        Rate(limit=limit, period=period)


@pytest.mark.parametrize(
    "scope", ["", "Ingest", "198.51.100.7", "a:b", "trk_abc", "with space", "x" * 49]
)
def test_scope_must_be_a_plain_lower_case_word(scope):
    with pytest.raises(ValueError):
        ratelimit.bucket_key(scope, "id")


def test_bucket_key_is_scoped_and_never_contains_the_identifier():
    key = ratelimit.bucket_key("ingest-token", "198.51.100.7")
    scope, digest = key.split(":")
    assert scope == "ingest-token"
    assert len(digest) == 64 and "198.51.100.7" not in key
    assert key == ratelimit.bucket_key("ingest-token", "198.51.100.7")
    assert key != ratelimit.bucket_key("ingest-ip", "198.51.100.7")
    assert key != ratelimit.bucket_key("ingest-token", "198.51.100.8")
    assert (
        len(ratelimit.bucket_key("a" * 48, "x"))
        <= RateLimitBucket._meta.get_field("key").max_length
    )


def test_windows_are_aligned_to_the_epoch():
    assert ratelimit.window_start(NOW, 60) == NOW.replace(second=0)
    assert ratelimit.window_start(NOW, 3600) == NOW.replace(minute=0, second=0)
    assert ratelimit.window_start(NOW, 86_400) == NOW.replace(hour=0, minute=0, second=0)


def _request(remote="203.0.113.9", **headers):
    return RequestFactory().get("/", REMOTE_ADDR=remote, headers=headers)


def test_client_ip_uses_the_socket_address_and_ignores_headers_by_default(settings):
    settings.RATELIMIT_CLIENT_IP_HEADER = ""
    request = _request(**{"CF-Connecting-IP": "198.51.100.1", "X-Forwarded-For": "198.51.100.2"})
    assert ratelimit.client_ip(request) == "203.0.113.9"


def test_client_ip_trusts_only_the_configured_proxy_header(settings):
    settings.RATELIMIT_CLIENT_IP_HEADER = "CF-Connecting-IP"
    assert ratelimit.client_ip(_request(**{"CF-Connecting-IP": "198.51.100.1"})) == "198.51.100.1"
    assert ratelimit.client_ip(_request()) == "203.0.113.9"  # header missing: socket address


def test_client_ip_groups_ipv6_by_64_and_unwraps_mapped_ipv4(settings):
    settings.RATELIMIT_CLIENT_IP_HEADER = ""
    assert ratelimit.client_ip(_request("2001:db8:1:2:aaaa::1")) == "2001:db8:1:2::/64"
    assert ratelimit.client_ip(_request("2001:db8:1:2:bbbb::7")) == "2001:db8:1:2::/64"
    assert ratelimit.client_ip(_request("::ffff:198.51.100.4")) == "198.51.100.4"
    assert ratelimit.client_ip(_request("not-an-ip")) == "unknown"


# --- Counting ----------------------------------------------------------------------------------


@LIMITER_DB
def test_allows_up_to_the_limit_then_denies_until_the_window_ends():
    rate = Rate(limit=3, period=60)
    decisions = [ratelimit.hit("test", "client", rate, now=NOW) for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.count for d in decisions] == [1, 2, 3, 4]
    assert decisions[-1].reset_at == NOW.replace(second=0) + dt.timedelta(minutes=1)
    assert decisions[-1].retry_after == 34
    later = ratelimit.hit("test", "client", rate, now=NOW + dt.timedelta(seconds=34))
    assert (later.allowed, later.count) == (True, 1)


@LIMITER_DB
def test_scopes_and_identifiers_count_separately():
    rate = Rate(limit=1, period=60)
    assert ratelimit.hit("test-a", "one", rate, now=NOW).allowed
    assert ratelimit.hit("test-a", "two", rate, now=NOW).allowed
    assert ratelimit.hit("test-b", "one", rate, now=NOW).allowed
    assert not ratelimit.hit("test-a", "one", rate, now=NOW).allowed


@LIMITER_DB
def test_enforce_raises_with_the_decision():
    rate = Rate(limit=1, period=60)
    ratelimit.enforce("test", "client", rate, now=NOW)
    with pytest.raises(RateLimited) as raised:
        ratelimit.enforce("test", "client", rate, now=NOW)
    assert raised.value.decision.count == 2


@LIMITER_DB
def test_only_hmac_keys_are_stored():
    secret = "token-hash-or-ip-that-must-not-be-stored"
    ratelimit.hit("test", secret, Rate(limit=5, period=60), now=NOW)
    keys = stored_keys()
    assert len(keys) == 1
    assert secret not in keys[0]


@LIMITER_DB
def test_counts_survive_a_rolled_back_request_transaction():
    """The limiter writes on its own connection: a request that fails and rolls back still
    used up its attempt."""
    rate = Rate(limit=5, period=60)
    with pytest.raises(RuntimeError), transaction.atomic():
        ratelimit.hit("test", "client", rate, now=NOW)
        raise RuntimeError("the request failed")
    assert ratelimit.hit("test", "client", rate, now=NOW).count == 2


@LIMITER_DB
def test_purge_deletes_only_finished_windows():
    day = Rate(limit=5, period=MAX_PERIOD)
    minute = Rate(limit=5, period=60)
    ratelimit.hit("test-old", "x", minute, now=NOW - dt.timedelta(days=2))
    ratelimit.hit("test-old-day", "x", day, now=NOW - dt.timedelta(days=2))
    ratelimit.hit("test-current-day", "x", day, now=NOW)
    ratelimit.hit("test-recent", "x", minute, now=NOW - dt.timedelta(minutes=5))
    assert ratelimit.purge_expired(now=NOW) == 2
    scopes = sorted(key.split(":")[0] for key in stored_keys())
    assert scopes == ["test-current-day", "test-recent"]


@LIMITER_DB
def test_hourly_task_purges_old_buckets():
    ratelimit.hit("test-old", "x", Rate(limit=5, period=60), now=NOW - dt.timedelta(days=400))
    assert purge_rate_limits(0) == 1
    assert stored_keys() == []


def test_purge_task_is_scheduled():
    from procrastinate.contrib.django import app

    assert ("core.purge_rate_limits", "purge-rate-limits") in app.periodic_registry.periodic_tasks


# --- Concurrency: real parallel connections ------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "ratelimit"])
def test_parallel_requests_on_separate_connections_are_counted_exactly():
    """Threads each open their own PostgreSQL connection (as travel_app) and hit the same bucket
    at the same moment, several rounds. Every increment must land exactly once (the counts seen
    are 1..N) and exactly `limit` requests per round are allowed."""
    threads, rounds = 12, 4
    rate = Rate(limit=5, period=60)
    barrier = threading.Barrier(threads)
    lock = threading.Lock()
    seen: list[tuple[int, ratelimit.Decision]] = []
    backends: set[int] = set()
    errors: list[BaseException] = []

    def client() -> None:
        try:
            with connections["ratelimit"].cursor() as cursor:
                cursor.execute("SET ROLE travel_app")
                cursor.execute("SELECT pg_backend_pid()")
                backend = cursor.fetchone()[0]
            mine = []
            for round_ in range(rounds):
                barrier.wait(timeout=30)
                mine.append((round_, ratelimit.hit("test-parallel", f"r{round_}", rate, now=NOW)))
            with lock:
                seen.extend(mine)
                backends.add(backend)
        except BaseException as exc:  # noqa: BLE001 (reported by the main thread)
            errors.append(exc)
            barrier.abort()
        finally:
            connections.close_all()

    workers = [threading.Thread(target=client) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)
    assert errors == []
    assert len(backends) == threads  # really separate server connections
    for round_ in range(rounds):
        decisions = [d for r, d in seen if r == round_]
        assert sorted(d.count for d in decisions) == list(range(1, threads + 1))
        assert sum(d.allowed for d in decisions) == rate.limit
        assert all(d.allowed == (d.count <= rate.limit) for d in decisions)


# --- Through Ninja endpoints ------------------------------------------------------------------


@LIMITER_DB
@pytest.mark.urls("tests.ratelimit_urls")
def test_decorator_answers_429_with_retry_after_per_client_ip(client):
    first = client.get("/t/rl/decorated?q=7", REMOTE_ADDR="198.51.100.20")
    assert (first.status_code, first.json()) == (200, {"q": 7})
    assert client.get("/t/rl/decorated", REMOTE_ADDR="198.51.100.20").status_code == 200
    limited = client.get("/t/rl/decorated", REMOTE_ADDR="198.51.100.20")
    assert limited.status_code == 429
    assert limited.json() == {"detail": "too many requests"}
    assert 1 <= int(limited["Retry-After"]) <= 60
    assert client.get("/t/rl/decorated", REMOTE_ADDR="198.51.100.21").status_code == 200


@LIMITER_DB
@pytest.mark.urls("tests.ratelimit_urls")
def test_enforce_inside_an_endpoint_becomes_429(client):
    assert client.post("/t/rl/enforced/a").status_code == 200
    limited = client.post("/t/rl/enforced/a")
    assert limited.status_code == 429
    assert int(limited["Retry-After"]) >= 1
    assert client.post("/t/rl/enforced/b").status_code == 200


def test_main_api_turns_rate_limited_into_429():
    from config.api import api

    assert RateLimited in api._exception_handlers
