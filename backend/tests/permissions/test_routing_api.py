"""Routing API (work-order item 25): `POST /routing/route` (proposals) and
`POST /legs/{leg_id}/routes` (save a proposal as a frozen version), for every actor of the
synthetic family, through real requests. Providers are faked (tests/test_routing_proxy.py);
the SQL/RLS side of both actions is in test_matrix.py (`propose_route`,
`view_alice_route_cache`, `add_route_version`, `save_route_version_on_bobs_leg`).
"""

import pytest

from tests.factories import LegFactory
from tests.helpers import as_owner
from tests.permissions.test_trips_api import API, call, login
from tests.routing_fakes import (
    SALINA,
    STATUS,
    WICHITA,
    FakeResponse,
    osrm_answer,
)
from travel.trips.models import Leg, Route, RouteSimplified

pytestmark = pytest.mark.django_db(databases=["default", "ratelimit"])

ACTORS = ("admin", "alice", "bob", "carol", "victor", "ivan", "anon")
KANSAS = [list(WICHITA), list(SALINA)]


@pytest.fixture
def valhalla(fake):
    return fake({"valhalla:8002/route": FakeResponse(200, osrm_answer()), "/status": STATUS})


def propose(client, waypoints=KANSAS):
    return call(client, "POST", f"{API}/routing/route", {"waypoints": waypoints})


def save(client, leg_id, waypoints=KANSAS, note=""):
    return call(
        client, "POST", f"{API}/legs/{leg_id}/routes", {"waypoints": waypoints, "note": note}
    )


@pytest.mark.parametrize(
    ("actor", "status"), zip(ACTORS, (200, 200, 200, 200, 403, 401, 401), strict=True)
)
def test_who_may_propose(client, scenario, valhalla, actor, status):
    if actor != "anon":
        login(client, getattr(scenario, actor))
    response = propose(client)
    assert response.status_code == status
    if status == 200:
        body = response.json()
        assert body["provenance"]["engine"] == "valhalla"
        assert body["provenance"]["attribution"]
        assert body["routes"][0]["geometry"]["type"] == "LineString"


@pytest.mark.parametrize(
    "waypoints",
    [
        [[-97.3, 37.6]],
        [[-97.3, 37.6]] * 26,
        [[-97.3, 95.0], [-97.6, 38.8]],
        [[-197.3, 37.6], [-97.6, 38.8]],
        [[-97.3, 37.6, 1.0], [-97.6, 38.8]],
    ],
)
def test_invalid_waypoints(client, scenario, valhalla, waypoints):
    login(client, scenario.alice)
    assert propose(client, waypoints).status_code == 422
    assert valhalla.calls == []


def test_unroutable_points_answer_422(client, scenario, fake):
    fake({"valhalla:8002/route": FakeResponse(400, {"code": "NoRoute"})})
    login(client, scenario.alice)
    assert propose(client).status_code == 422


def test_busy_fallback_answers_503_with_retry_after(client, scenario, fake):
    fake({"fossgis.invalid": FakeResponse(200, osrm_answer())})
    login(client, scenario.alice)
    outside = [[-104.99, 39.74], [-95.93, 41.26]]
    assert propose(client, outside).status_code == 200
    login(client, scenario.bob)
    busy = propose(client, [[-104.99, 39.74], [-95.0, 41.0]])
    assert busy.status_code == 503
    assert busy["Retry-After"] == "1"


# --- Saving a proposal as a version -------------------------------------------------------------


@pytest.mark.parametrize(
    ("actor", "core", "bobs"),
    [
        ("admin", 201, 403),
        ("alice", 201, 403),
        ("bob", 403, 201),
        ("carol", 403, 403),
        ("victor", 403, 403),
        ("ivan", 401, 401),
        ("anon", 401, 401),
    ],
)
def test_who_may_save_a_version(client, scenario, valhalla, actor, core, bobs):
    f = scenario
    if actor != "anon":
        login(client, getattr(f, actor))
    propose(client)
    assert save(client, f.core_leg.pk).status_code == core
    assert save(client, f.bob_leg.pk).status_code == bobs


def test_a_leg_on_an_invisible_trip_is_not_found(client, scenario, valhalla):
    f = scenario
    with as_owner():
        leg = LegFactory(trip=f.trips["private"], author=f.alice)
    login(client, f.carol)
    propose(client)
    assert save(client, leg.pk).status_code == 404


def test_saving_needs_the_callers_own_recent_proposal(client, scenario, valhalla):
    f = scenario
    login(client, f.bob)
    assert propose(client).status_code == 200  # bob's proposal is not alice's
    login(client, f.alice)
    assert save(client, f.core_leg.pk).status_code == 409
    assert propose(client).status_code == 200
    assert save(client, f.core_leg.pk, [list(SALINA), list(WICHITA)]).status_code == 409


def test_saving_creates_a_new_current_version_and_never_touches_old_ones(
    client, scenario, valhalla
):
    f = scenario
    login(client, f.alice)
    with as_owner():
        old = Route.objects.get(pk=f.route.pk)
    propose(client)
    response = save(client, f.core_leg.pk, note="first proposal")
    assert response.status_code == 201
    body = response.json()
    assert (body["version"], body["kind"], body["is_current"]) == (2, "routed", True)
    assert body["engine"] == "valhalla" and body["engine_version"] == "3.9.1"
    assert body["attribution"].startswith("Route: Valhalla")
    assert body["note"] == "first proposal"
    assert [w["role"] for w in body["waypoints"]] == ["start", "end"]
    assert body["geometry"]["coordinates"] == [
        osrm_answer()["routes"][0]["geometry"]["coordinates"]
    ]
    assert 100_000 < body["length_m"] < 200_000

    again = save(client, f.core_leg.pk).json()
    assert again["version"] == 3
    with as_owner():
        leg = Leg.objects.get(pk=f.core_leg.pk)
        unchanged = Route.objects.get(pk=old.pk)
        zooms = sorted(
            RouteSimplified.objects.filter(route_id=again["id"]).values_list("zoom", flat=True)
        )
    assert leg.current_route_id == again["id"]
    assert leg.distance_m == pytest.approx(again["length_m"])
    assert (unchanged.geom.wkt, unchanged.note, unchanged.version) == (
        old.geom.wkt,
        old.note,
        old.version,
    )
    assert zooms == [3, 6, 9, 12]

    versions = call(client, "GET", f"{API}/legs/{f.core_leg.pk}/routes").json()
    assert [v["version"] for v in versions] == [3, 2, 1]
    legs = call(client, "GET", f"{API}/trips/map").json()["legs"]
    drawn = next(row for row in legs if row["id"] == f.core_leg.pk)
    assert drawn["routed"] is True
    assert len(drawn["coordinates"]) >= 2


def test_only_road_legs_take_a_road_route(client, scenario, valhalla):
    f = scenario
    with as_owner():
        Leg.objects.filter(pk=f.core_leg.pk).update(mode="flight")
    login(client, f.alice)
    propose(client)
    assert save(client, f.core_leg.pk).status_code == 422
