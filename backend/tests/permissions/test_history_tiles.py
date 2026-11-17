"""Milestone 2.3: the raw-history map shows a user only their own history (PLAN.md §6.3 "Raw
history": own only, never the Admin). Checked at the API level for every actor, and at the SQL
level by running the tile and coverage builders as `travel_app` under each RLS context, so a
missing policy check in a view could not leak either. Another user's points share the exact
location and time of the caller's, so they would land in the same aggregated cell."""

import datetime as dt
import math

import pytest
from django.contrib.gis.geos import LineString
from django.utils import timezone

from tests import mvt
from tests.factories import WICHITA, LocationPointFactory, TimelineSegmentFactory
from tests.helpers import as_owner, rollup_mismatches
from travel.core.rls import rls_context
from travel.history import tiles
from travel.history.models import LocationPoint

pytestmark = [pytest.mark.django_db]

ALICE_POINTS = 5  # one from the family fixture + 4 here
BOB_POINTS = 4  # one from the family fixture + 3 here


def tile_of(point, z: int) -> tuple[int, int, int]:
    n = 2**z
    x = int((point.x + 180) / 360 * n)
    lat = math.radians(point.y)
    y = int((1 - math.asinh(math.tan(lat)) / math.pi) / 2 * n)
    return z, x, y


@pytest.fixture
def history(family):
    """Alice and Bob both have points at the same place and times; Bob also has a segment."""
    with as_owner():
        base = timezone.now().replace(microsecond=0) - dt.timedelta(days=2)
        for i in range(4):
            LocationPointFactory(owner=family.alice, ts=base + dt.timedelta(minutes=i))
        for i in range(3):
            LocationPointFactory(owner=family.bob, ts=base + dt.timedelta(minutes=i))
        family.bob_segment = TimelineSegmentFactory(
            owner=family.bob,
            kind="path",
            geom=LineString((WICHITA.x, WICHITA.y), (WICHITA.x + 0.01, WICHITA.y)),
        )
    return family


def login(client, user):
    with as_owner():
        client.force_login(user)


def point_count(data: bytes) -> int:
    layer = mvt.decode(data).get("points")
    return sum(f.properties["n"] for f in layer.features) if layer else 0


def segment_ids(data: bytes) -> set[int]:
    layer = mvt.decode(data).get("segments")
    return {f.properties["id"] for f in layer.features} if layer else set()


# Expected points visible to each actor at Wichita (aggregated and single-point zooms alike).
VISIBLE = {"alice": ALICE_POINTS, "bob": BOB_POINTS, "admin": 0, "carol": 0, "victor": 0}


@pytest.mark.parametrize("z", [3, 10, 16])
@pytest.mark.parametrize("actor", sorted(VISIBLE))
def test_api_points_tile_shows_only_own_points(client, history, actor, z):
    login(client, getattr(history, actor))
    zz, x, y = tile_of(WICHITA, z)
    response = client.get(f"/api/v1/history/tiles/{zz}/{x}/{y}.mvt")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.mapbox-vector-tile"
    assert "private" in response["Cache-Control"]
    assert point_count(response.content) == VISIBLE[actor]


@pytest.mark.parametrize("actor", ["anon", "ivan"])
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/history/tiles/3/1/3.mvt",
        "/api/v1/history/segments/tiles/8/58/98.mvt",
        "/api/v1/history/coverage?from=2025-01-01&to=2025-01-31",
    ],
)
def test_api_refuses_signed_out_and_deactivated(client, history, actor, path):
    if actor != "anon":
        login(client, getattr(history, actor))
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("actor", ["alice", "bob", "admin", "carol", "victor"])
def test_api_segments_tile_shows_only_own_segments(client, history, actor):
    login(client, getattr(history, actor))
    z, x, y = tile_of(WICHITA, 12)
    response = client.get(f"/api/v1/history/segments/tiles/{z}/{x}/{y}.mvt")
    assert response.status_code == 200
    expected = {
        "alice": {history.alice_segment.pk},
        "bob": {history.bob_segment.pk},
    }.get(actor, set())
    assert segment_ids(response.content) == expected


@pytest.mark.parametrize("actor", ["alice", "bob", "admin", "carol", "victor"])
def test_api_coverage_counts_only_own_history(client, history, actor):
    login(client, getattr(history, actor))
    today = timezone.now().date()
    response = client.get(
        f"/api/v1/history/coverage?from={today - dt.timedelta(days=30)}&to={today}&tz=UTC"
    )
    assert response.status_code == 200
    body = response.json()
    assert sum(d["points"] for d in body["days"]) == VISIBLE[actor]
    # The fixture's segment ends 1-3 hours ago, so it may touch two days.
    assert (sum(d["segments"] for d in body["days"]) > 0) == (actor in ("alice", "bob"))
    assert (body["first_day"] is None) == (VISIBLE[actor] == 0)


# --- SQL level: the builders themselves, as travel_app under each RLS context --------------


@pytest.mark.parametrize("z", [3, 10, 16])
@pytest.mark.parametrize("actor", [*sorted(VISIBLE), "ivan", None])
def test_rls_points_tile_as_travel_app(history, actor, z):
    """Calls the builder directly - no view, no policy check - so only RLS stands between the
    caller and other users' rows. Deactivated users and a missing context see nothing."""
    user_id = getattr(history, actor).pk if actor else None
    with rls_context(user_id):
        tile = tiles.points_tile(*tile_of(WICHITA, z))
    assert point_count(tile.data) == VISIBLE.get(actor, 0)


@pytest.mark.parametrize("actor", ["alice", "bob", "admin", "ivan", None])
def test_rls_segments_and_coverage_as_travel_app(history, actor):
    user_id = getattr(history, actor).pk if actor else None
    today = timezone.now().date()
    with rls_context(user_id):
        segs = segment_ids(tiles.segments_tile(*tile_of(WICHITA, 12)).data)
        cov = tiles.coverage(today - dt.timedelta(days=30), today, tiles.ZoneInfo("UTC"))
    own = {"alice": history.alice_segment.pk, "bob": history.bob_segment.pk}
    assert segs == ({own[actor]} if actor in own else set())
    assert sum(d.points for d in cov.days) == VISIBLE.get(actor, 0)


def test_dense_tile_never_mixes_owners_in_a_cell(history):
    """Force aggregation at a high zoom: Alice's cell holds exactly her points."""
    with rls_context(history.alice.pk):
        tile = tiles.points_tile(*tile_of(WICHITA, 3))
    layer = mvt.decode(tile.data)["points"]
    assert tile.aggregated
    assert [f.properties["n"] for f in layer.features] == [ALICE_POINTS]


# --- The point roll-up (history migration 0010): same rules as the points -------------------

# Date ranges for the aggregated tiles: whole history (roll-up years), and a window with partial
# days at both ends (raw points for the edges, roll-up days in between).
WINDOWS = {"all": None, "partial days": (dt.timedelta(days=-3, hours=-5), dt.timedelta(hours=7))}


@pytest.mark.parametrize("window", sorted(WINDOWS))
@pytest.mark.parametrize("z", [0, 9, 13, 16])
@pytest.mark.parametrize("actor", [*sorted(VISIBLE), "ivan", None])
def test_rls_aggregated_cells_count_only_own_points(history, monkeypatch, actor, z, window):
    """Aggregated cells are summed from the roll-up (and raw points at the window's edges) as
    travel_app: another user's points at the same place and time never add to a cell."""
    monkeypatch.setattr(tiles, "MAX_POINTS_PER_TILE", 0)  # aggregate at z16 too
    start = end = None
    if WINDOWS[window]:
        base = timezone.now().replace(microsecond=0) - dt.timedelta(days=2)
        start, end = (base + offset for offset in WINDOWS[window])
    user_id = getattr(history, actor).pk if actor else None
    with rls_context(user_id):
        tile = tiles.points_tile(*tile_of(WICHITA, z), start=start, end=end)
    layer = mvt.decode(tile.data).get("points")
    cells = [f.properties["n"] for f in layer.features] if layer else []
    expected = 0
    if actor in VISIBLE:
        with as_owner():
            own = LocationPoint.objects.filter(owner=getattr(history, actor))
            if start is not None:
                own = own.filter(ts__gte=start, ts__lt=end)
            expected = own.count()
    assert expected == (VISIBLE.get(actor, 0) if window == "all" else expected)
    assert cells == ([expected] if expected else [])
    assert tile.aggregated or not expected


@pytest.mark.parametrize("actor", [*sorted(VISIBLE), "ivan", None])
def test_rls_rollup_rows_are_own_only(history, actor):
    from django.db import connection

    user_id = getattr(history, actor).pk if actor else None
    with rls_context(user_id), connection.cursor() as cursor:
        cursor.execute(
            "SELECT owner_id, sum(n) FROM history_pointrollup WHERE level = 20 AND grain = %s"
            " GROUP BY 1",
            [tiles.GRAIN_YEAR],
        )
        rows = dict(cursor.fetchall())
    assert rows == ({user_id: VISIBLE[actor]} if VISIBLE.get(actor) else {})


def test_rls_rollup_of_another_user_cannot_be_written(history):
    """As travel_app, Alice can neither add to, change nor delete Bob's roll-up rows."""
    from django.db import DatabaseError, connection, transaction

    with as_owner(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, n FROM history_pointrollup WHERE owner_id = %s ORDER BY id",
            [history.bob.pk],
        )
        before = cursor.fetchall()
    assert before
    with rls_context(history.alice.pk), connection.cursor() as cursor:
        with pytest.raises(DatabaseError, match="row-level security"), transaction.atomic():
            cursor.execute(
                "INSERT INTO history_pointrollup (owner_id, level, grain, period, source, cell, n)"
                " VALUES (%s, 20, 1, '2025-01-01', 'owntracks', 1, 5)",
                [history.bob.pk],
            )
        cursor.execute(
            "UPDATE history_pointrollup SET n = n + 1 WHERE owner_id = %s", [history.bob.pk]
        )
        assert cursor.rowcount == 0
        cursor.execute("DELETE FROM history_pointrollup WHERE owner_id = %s", [history.bob.pk])
        assert cursor.rowcount == 0
        # Deleting her own points (the trigger path) leaves Bob's roll-up alone too.
        cursor.execute("DELETE FROM history_locationpoint")
        assert cursor.rowcount == ALICE_POINTS
    with as_owner(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, n FROM history_pointrollup WHERE owner_id = %s ORDER BY id",
            [history.bob.pk],
        )
        assert cursor.fetchall() == before
    assert rollup_mismatches() == []
