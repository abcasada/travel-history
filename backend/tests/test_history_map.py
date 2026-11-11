"""Milestone 2.3: the raw-history map's tiles and coverage strip - filters, bounds, aggregation,
timeouts. Who may see what is in tests/permissions/test_history_tiles.py."""

import datetime as dt
import gzip
import os
import random
import time

import pytest
from django.contrib.gis.geos import LineString, Point
from django.db import connection

from tests import mvt
from tests.factories import WICHITA, LocationPointFactory, TimelineSegmentFactory, UserFactory
from tests.helpers import as_owner
from tests.permissions.test_history_tiles import point_count, segment_ids, tile_of
from travel.core.rls import get_context, rls_context
from travel.history import tiles
from travel.history.models import PointSource

pytestmark = pytest.mark.django_db

UTC = dt.UTC
DAY1 = dt.datetime(2025, 3, 1, 18, 0, tzinfo=UTC)
DAY2 = dt.datetime(2025, 3, 2, 3, 0, tzinfo=UTC)  # evening of 1 March in Kansas


@pytest.fixture
def member(client):
    with as_owner():
        user = UserFactory()
        client.force_login(user)
    client.user = user
    return client


def add_points(user, when, n=1, source=PointSource.OWNTRACKS, where=WICHITA):
    with as_owner():
        for i in range(n):
            LocationPointFactory(
                owner=user, ts=when + dt.timedelta(seconds=i), source=source, geom=where
            )


def get_tile(client, z, query="", where=WICHITA, kind="tiles"):
    z, x, y = tile_of(where, z)
    prefix = "history/tiles" if kind == "tiles" else "history/segments/tiles"
    return client.get(f"/api/v1/{prefix}/{z}/{x}/{y}.mvt{query}")


# --- Tiles ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/history/tiles/19/0/0.mvt",  # above the zoom cap
        "/api/v1/history/tiles/3/8/0.mvt",  # outside the grid
        "/api/v1/history/tiles/3/0/8.mvt",
        "/api/v1/history/segments/tiles/4/3/6.mvt",  # segments start at zoom 5
    ],
)
def test_out_of_range_tiles_are_404(member, path):
    assert member.get(path).status_code == 404


def test_date_filter_selects_points(member):
    add_points(member.user, DAY1, 3)
    add_points(member.user, DAY1 + dt.timedelta(days=10), 2)
    assert point_count(get_tile(member, 6).content) == 5
    query = "?from=2025-03-01T00:00:00Z&to=2025-03-02T00:00:00Z"
    assert point_count(get_tile(member, 6, query).content) == 3
    query = "?from=2025-03-05T00:00:00%2B00:00"
    assert point_count(get_tile(member, 6, query).content) == 2


def test_cache_buster_is_ignored(member):
    """The map appends `rev=` (latest import) so new data isn't hidden by the browser cache."""
    add_points(member.user, DAY1, 2)
    assert point_count(get_tile(member, 6, "?rev=3.17").content) == 2
    assert get_tile(member, 12, "?rev=3.17", kind="segments").status_code == 200


def test_source_filter(member):
    add_points(member.user, DAY1, 3, source=PointSource.OWNTRACKS)
    add_points(member.user, DAY1, 2, source=PointSource.GOOGLE_PATH)
    assert point_count(get_tile(member, 16, "?source=google_path").content) == 2
    assert point_count(get_tile(member, 16, "?source=google_path,owntracks").content) == 5
    assert get_tile(member, 16, "?source=nonsense").status_code == 422


@pytest.mark.parametrize(
    "query",
    [
        "?from=2025-03-01T00:00:00",  # no offset
        "?from=2025-03-02T00:00:00Z&to=2025-03-01T00:00:00Z",  # backwards
        "?from=yesterday",
    ],
)
def test_bad_ranges_are_422(member, query):
    assert get_tile(member, 6, query).status_code == 422


def test_zoomed_in_tile_has_single_points_with_time_and_source(member):
    add_points(member.user, DAY1, 3)
    response = get_tile(member, 16)
    assert response["X-Tile-Aggregated"] == "0"
    features = mvt.decode(response.content)["points"].features
    assert len(features) == 3
    assert {f.properties["n"] for f in features} == {1}
    assert {f.properties["src"] for f in features} == {"owntracks"}
    assert min(f.properties["ts"] for f in features) == int(DAY1.timestamp())


def test_dense_zoomed_in_tile_falls_back_to_cells(member, monkeypatch):
    monkeypatch.setattr(tiles, "MAX_POINTS_PER_TILE", 3)
    add_points(member.user, DAY1, 4)
    response = get_tile(member, 16)
    assert response["X-Tile-Aggregated"] == "1"
    assert [f.properties["n"] for f in mvt.decode(response.content)["points"].features] == [4]


def test_aggregated_tile_is_bounded_and_counts_everything(member):
    """2,000 scattered points in one zoom-9 tile: at most one feature per grid cell, nothing
    dropped, every cell centre inside the tile's grid (plus margin)."""
    z, x, y = tile_of(WICHITA, 9)
    rng = random.Random(9)  # noqa: S311 - synthetic test data
    with as_owner(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b) "
            "FROM ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326) b",
            [z, x, y],
        )
        x0, y0, x1, y1 = cursor.fetchone()
        for i in range(2000):
            LocationPointFactory(
                owner=member.user,
                ts=DAY1 + dt.timedelta(seconds=i),
                geom=Point(rng.uniform(x0, x1), rng.uniform(y0, y1), srid=4326),
            )
    response = member.get(f"/api/v1/history/tiles/{z}/{x}/{y}.mvt")
    layer = mvt.decode(response.content)["points"]
    assert sum(f.properties["n"] for f in layer.features) == 2000
    assert len(layer.features) <= (tiles.GRID + 2 * tiles.MARGIN_CELLS) ** 2
    for feature in layer.features:
        ((px, py),) = feature.points()
        assert -tiles.BUFFER <= px < tiles.EXTENT + tiles.BUFFER
        assert -tiles.BUFFER <= py < tiles.EXTENT + tiles.BUFFER
    assert len({tuple(f.points()[0]) for f in layer.features}) == len(layer.features)


def test_tiles_are_private_and_gzipped_on_request(member):
    add_points(member.user, DAY1, 3)
    response = get_tile(member, 6, "", WICHITA)
    plain = response.content
    z, x, y = tile_of(WICHITA, 6)
    zipped = member.get(f"/api/v1/history/tiles/{z}/{x}/{y}.mvt", HTTP_ACCEPT_ENCODING="gzip")
    assert zipped["Content-Encoding"] == "gzip"
    assert gzip.decompress(zipped.content) == plain
    assert zipped["Cache-Control"].startswith("private")


def test_empty_tile_is_an_empty_body(member):
    response = get_tile(member, 6)
    assert response.status_code == 200
    assert response.content == b""


def test_segments_tile_shows_current_versions_in_range(member):
    with as_owner():
        line = LineString((WICHITA.x, WICHITA.y), (WICHITA.x + 0.02, WICHITA.y + 0.01))
        march = TimelineSegmentFactory(
            owner=member.user, kind="path", geom=line, start_utc=DAY1, end_utc=DAY2
        )
        old = TimelineSegmentFactory(
            owner=member.user,
            kind="visit",
            start_utc=DAY1,
            end_utc=DAY2,
            is_current=False,
        )
        later = TimelineSegmentFactory(
            owner=member.user,
            kind="activity",
            activity_type="CYCLING",
            geom=line,
            start_utc=DAY1 + dt.timedelta(days=30),
            end_utc=DAY2 + dt.timedelta(days=30),
        )
    response = get_tile(member, 12, kind="segments")
    assert segment_ids(response.content) == {march.pk, later.pk}
    assert old.pk not in segment_ids(response.content)
    query = "?from=2025-03-01T00:00:00Z&to=2025-03-10T00:00:00Z"
    assert segment_ids(get_tile(member, 12, query, kind="segments").content) == {march.pk}
    features = mvt.decode(get_tile(member, 12, kind="segments").content)["segments"].features
    cycling = next(f for f in features if f.properties["id"] == later.pk)
    assert cycling.type == 2  # a line
    assert cycling.properties["activity"] == "CYCLING"
    assert cycling.properties["t0"] == int((DAY1 + dt.timedelta(days=30)).timestamp())


def test_segments_tile_is_capped(member, monkeypatch):
    monkeypatch.setattr(tiles, "MAX_SEGMENTS_PER_TILE", 2)
    with as_owner():
        for i in range(3):
            TimelineSegmentFactory(
                owner=member.user,
                start_utc=DAY1 + dt.timedelta(hours=i),
                end_utc=DAY1 + dt.timedelta(hours=i, minutes=30),
            )
    response = get_tile(member, 12, kind="segments")
    assert len(segment_ids(response.content)) == 2
    assert response["X-Tile-Truncated"] == "1"


def test_slow_tile_query_times_out_without_breaking_the_request(member, monkeypatch):
    monkeypatch.setattr(tiles, "TIMEOUT_MS", 50)
    with rls_context(member.user.pk):
        with pytest.raises(tiles.TileTimeout):
            tiles._run("SELECT pg_sleep(0.5)", {})
        # Only the savepoint rolled back: the RLS context and the old timeout are intact.
        assert get_context() == (member.user.pk, "")
        with connection.cursor() as cursor:
            cursor.execute("SHOW statement_timeout")
            assert cursor.fetchone()[0] != "50ms"


def test_timeout_becomes_503(member, monkeypatch):
    def slow(*args, **kwargs):
        raise tiles.TileTimeout

    monkeypatch.setattr(tiles, "points_tile", slow)
    response = get_tile(member, 6)
    assert response.status_code == 503
    assert response["Retry-After"]


# --- Coverage ------------------------------------------------------------------------------


def coverage(client, first="2025-02-01", last="2025-03-31", tz="America/Chicago"):
    return client.get(f"/api/v1/history/coverage?from={first}&to={last}&tz={tz}")


def test_coverage_buckets_by_local_day(member):
    add_points(member.user, DAY1, 2)
    add_points(member.user, DAY2, 3)  # 21:00 on 1 March in Chicago
    add_points(member.user, DAY1 + dt.timedelta(days=5), 1)
    body = coverage(member).json()
    assert body["days"] == [
        {"day": "2025-03-01", "points": 5, "segments": 0},
        {"day": "2025-03-06", "points": 1, "segments": 0},
    ]
    assert body["first_day"] == "2025-03-01"
    assert body["last_day"] == "2025-03-06"
    utc = coverage(member, tz="UTC").json()
    assert [d["day"] for d in utc["days"]] == ["2025-03-01", "2025-03-02", "2025-03-06"]


def test_coverage_counts_a_segment_on_every_day_it_touches(member):
    with as_owner():
        TimelineSegmentFactory(
            owner=member.user,
            start_utc=dt.datetime(2025, 3, 10, 23, 0, tzinfo=UTC),  # 18:00 local
            end_utc=dt.datetime(2025, 3, 12, 14, 0, tzinfo=UTC),  # 09:00 local
        )
    body = coverage(member).json()
    assert [(d["day"], d["segments"]) for d in body["days"]] == [
        ("2025-03-10", 1),
        ("2025-03-11", 1),
        ("2025-03-12", 1),
    ]
    clipped = coverage(member, first="2025-03-11", last="2025-03-11").json()
    assert [(d["day"], d["segments"]) for d in clipped["days"]] == [("2025-03-11", 1)]


@pytest.mark.parametrize(
    "first,last,tz",
    [
        ("2024-01-01", "2025-03-01", "UTC"),  # more than 400 days
        ("2025-03-02", "2025-03-01", "UTC"),  # backwards
        ("2025-03-01", "2025-03-02", "Mars/Olympus"),
        ("2025-03-01", "2025-03-02", "../../etc/passwd"),
    ],
)
def test_coverage_rejects_bad_requests(member, first, last, tz):
    assert coverage(member, first, last, tz).status_code == 422


def test_coverage_without_history(member):
    assert coverage(member).json() == {"first_day": None, "last_day": None, "days": []}


# --- Timings on synthetic data (PLAN.md resource budget) ------------------------------------

BENCH_POINTS = int(os.environ.get("TILE_BENCH_POINTS", "300000"))


@pytest.mark.slow
def test_tile_timings_on_synthetic_history(member, capsys):
    """A year of synthetic tracking (a random walk around Wichita) for one user, plus another
    user's points in the same place. Prints timings and sizes; fails only if a tile is far over
    budget. Set TILE_BENCH_POINTS for a bigger run."""
    with as_owner(), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO history_locationpoint (owner_id, ts, geom, source, received_at)
            SELECT %(owner)s,
                   timestamptz '2025-01-01 00:00Z' + make_interval(secs => g * 60),
                   ST_SetSRID(ST_Point(%(lon)s + 0.6 * sin(g / 5000.0) + random() * 0.05,
                                       %(lat)s + 0.4 * cos(g / 7000.0) + random() * 0.05), 4326),
                   'owntracks', now()
              FROM generate_series(1, %(n)s) g
            """,
            {"owner": member.user.pk, "lon": WICHITA.x, "lat": WICHITA.y, "n": BENCH_POINTS},
        )
        other = UserFactory()
        cursor.execute(
            """
            INSERT INTO history_locationpoint (owner_id, ts, geom, source, received_at)
            SELECT %s, timestamptz '2025-01-01 00:00Z' + make_interval(secs => g * 60),
                   ST_SetSRID(ST_Point(%s, %s), 4326), 'owntracks', now()
              FROM generate_series(1, 50000) g
            """,
            [other.pk, WICHITA.x, WICHITA.y],
        )
        cursor.execute("ANALYZE history_locationpoint")
        # Timeline segments along the same walk: one 30-minute path every 3 hours.
        cursor.execute(
            """
            INSERT INTO history_timelinesegment (
                owner_id, lineage_id, version, is_current, kind, start_utc, end_utc,
                hierarchy_level, place_id, semantic_type, activity_type, geom, data,
                fingerprint, edited_in_app, created_at)
            SELECT %(owner)s, gen_random_uuid(), 1, true, 'path',
                   timestamptz '2025-01-01 00:00Z' + make_interval(hours => g * 3),
                   timestamptz '2025-01-01 00:30Z' + make_interval(hours => g * 3),
                   0, '', '', '',
                   ST_SetSRID(ST_MakeLine(
                     ST_Point(%(lon)s + 0.6 * sin(g * 180 / 5000.0),
                              %(lat)s + 0.4 * cos(g * 180 / 7000.0)),
                     ST_Point(%(lon)s + 0.6 * sin((g * 180 + 30) / 5000.0) + 0.01,
                              %(lat)s + 0.4 * cos((g * 180 + 30) / 7000.0))), 4326),
                   '{}'::jsonb, md5(g::text) || md5(g::text), false, now()
              FROM generate_series(1, %(n)s / 180) g
            """,
            {"owner": member.user.pk, "lon": WICHITA.x, "lat": WICHITA.y, "n": BENCH_POINTS},
        )
        cursor.execute("ANALYZE history_locationpoint")
        cursor.execute("ANALYZE history_timelinesegment")
    on_walk = Point(WICHITA.x, WICHITA.y + 0.4, srid=4326)  # where the walk passes often
    results = []

    def timed(label, fetch):
        started = time.perf_counter()
        response = fetch()
        elapsed = time.perf_counter() - started
        assert response.status_code == 200
        is_tile = response["Content-Type"] == "application/vnd.mapbox-vector-tile"
        count = point_count(response.content) if is_tile else 0
        results.append((label, elapsed, len(response.content), count))

    for z in (2, 6, 10, 13, 16):
        timed(z, lambda z=z: get_tile(member, z, "", on_walk))
    month = "?from=2025-06-01T00:00:00Z&to=2025-07-01T00:00:00Z"
    timed("6/month", lambda: get_tile(member, 6, month, on_walk))
    for z in (5, 9, 13):
        timed(f"{z}/segments", lambda z=z: get_tile(member, z, "", on_walk, kind="segments"))
    timed("coverage/yr", lambda: coverage(member, "2025-01-01", "2025-12-31", "UTC"))
    with capsys.disabled():
        print(f"\ntile timings, {BENCH_POINTS} points:")
        for label, elapsed, size, count in results:
            print(f"  {label}: {elapsed * 1000:.0f} ms, {size / 1024:.1f} KiB, n={count}")
    for label, elapsed, size, _count in results:
        assert elapsed < 10, f"{label} took {elapsed:.1f}s"
        assert size < 512 * 1024, f"{label} is {size} bytes"
    assert results[0][3] == BENCH_POINTS  # the whole world at z2: every own point, no others


def test_point_keys_match_tile_ranges(member):
    """app.tile_key() (SQL) and tiles.key_range() (Python) agree on the bit layout: a point's
    key lies in the range of the tile it falls in, at every zoom."""
    rng = random.Random(20)  # noqa: S311 - synthetic test data
    where = [Point(rng.uniform(-179.9, 179.9), rng.uniform(-84, 84), srid=4326) for _ in range(40)]
    where += [Point(0.0001, 0.0001, srid=4326), Point(-179.99, 84.9, srid=4326), WICHITA]
    with connection.cursor() as cursor:
        for point in where:
            cursor.execute("SELECT app.tile_key(%s::geometry)", [point.ewkt])
            (key,) = cursor.fetchone()
            for z in (0, 1, 5, 9, 14, 18, 20):
                lo, hi = tiles.key_range(*tile_of(point, z))
                assert lo <= key < hi, (point.coords, z)


@pytest.mark.parametrize("z", [4, 9, 13])
def test_key_cells_match_geometric_cells(member, monkeypatch, z):
    """Grouping by key prefix (zoom <= 13) yields exactly the cells and counts that the
    geometric grid (used for dense tiles at zoom 14+) does."""
    rng = random.Random(z)  # noqa: S311 - synthetic test data
    with as_owner():
        for i in range(300):
            where = Point(
                WICHITA.x + rng.uniform(-0.3, 0.3) * 2 ** (6 - z),
                WICHITA.y + rng.uniform(-0.3, 0.3) * 2 ** (6 - z),
                srid=4326,
            )
            LocationPointFactory(owner=member.user, ts=DAY1 + dt.timedelta(seconds=i), geom=where)

    def cells():
        with rls_context(member.user.pk):
            layer = mvt.decode(tiles.points_tile(*tile_of(WICHITA, z)).data)["points"]
        return sorted((f.points()[0], f.properties["n"]) for f in layer.features)

    by_key = cells()
    monkeypatch.setattr(tiles, "KEY_CELLS_MAX_ZOOM", -1)
    assert by_key == cells()
    assert sum(n for _, n in by_key) > 0


def test_key_ranges_cover_the_margin():
    z, x, y = 10, 300, 400
    ranges = tiles.key_ranges(z, x, y)
    assert tiles.key_range(z, x, y)[0] >= ranges[0][0]
    # The neighbours' sub-tiles next to the shared edge are covered, the far ones are not.
    inside = lambda key: any(lo <= key < hi for lo, hi in ranges)  # noqa: E731
    sub = z + tiles.NEIGHBOUR_DEPTH
    s = 2**tiles.NEIGHBOUR_DEPTH
    assert inside(tiles.key_range(sub, (x + 1) * s, y * s + 1)[0])  # east, adjacent column
    assert not inside(tiles.key_range(sub, (x + 1) * s + 1, y * s + 1)[0])  # east, one further
    assert inside(tiles.key_range(sub, x * s - 1, y * s - 1)[0])  # north-west corner
    assert len(ranges) <= 21
    assert tiles.key_ranges(0, 0, 0) == [(0, 1 << 40)]
