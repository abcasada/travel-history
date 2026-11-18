"""Saving the drag editor's line (work-order item 26, D-93): `POST /legs/{id}/routes/edited`
for every actor, and how pieces are checked: proposals only from the caller's own cache,
versions only of the same leg, drawn points validated and recorded as unverified. The SQL/RLS
side is the matrix rows `add_route_version` (a hand_edited insert) and
`save_route_version_on_bobs_leg` in test_matrix.py.
"""

import pytest

from tests.factories import LegFactory, RouteFactory
from tests.helpers import as_owner
from tests.permissions.test_routing_api import KANSAS, propose, valhalla  # noqa: F401
from tests.permissions.test_trips_api import API, call, login
from tests.routing_fakes import LINE
from travel.trips.models import Leg, Route

pytestmark = pytest.mark.django_db(databases=["default", "ratelimit"])

DRAWN = [[-97.2, 37.7], [-97.25, 37.75]]


def edited(client, leg_id, pieces, waypoints=None, note=""):
    body = {"pieces": pieces, "waypoints": waypoints or KANSAS, "note": note}
    return call(client, "POST", f"{API}/legs/{leg_id}/routes/edited", body)


LAST = len(LINE) - 1


def proposal_piece(start=0, end=LAST, waypoints=KANSAS):
    return {"source": "proposal", "waypoints": waypoints, "start": start, "end": end}


def drawn_piece(coordinates=DRAWN, engine=None):
    piece = {"source": "drawn", "coordinates": coordinates}
    if engine:
        piece["engine"] = engine
    return piece


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
def test_who_may_save_an_edited_route(client, scenario, valhalla, actor, core, bobs):  # noqa: F811
    f = scenario
    if actor != "anon":
        login(client, getattr(f, actor))
    propose(client)
    pieces = [proposal_piece(0, 1), drawn_piece()]
    assert edited(client, f.core_leg.pk, pieces).status_code == core
    assert edited(client, f.bob_leg.pk, pieces).status_code == bobs


def test_a_leg_on_an_invisible_trip_is_not_found(client, scenario):
    f = scenario
    with as_owner():
        leg = LegFactory(trip=f.trips["private"], author=f.alice)
    login(client, f.carol)
    assert edited(client, leg.pk, [drawn_piece()]).status_code == 404


def test_mixed_pieces_make_a_hand_edited_version_with_sources(client, scenario, valhalla):  # noqa: F811
    f = scenario
    login(client, f.alice)
    with as_owner():
        old = Route.objects.get(pk=f.route.pk)
        old_coords = [list(p) for line in old.geom.coords for p in line]
    propose(client)
    pieces = [
        {"source": "version", "route_id": old.pk, "start": 0, "end": 0},
        drawn_piece(),
        proposal_piece(1, 2),
    ]
    response = edited(client, f.core_leg.pk, pieces, note="dragged")
    assert response.status_code == 201, response.content
    body = response.json()
    assert (body["version"], body["kind"], body["is_current"]) == (2, "hand_edited", True)
    assert body["geometry"]["coordinates"] == [[old_coords[0], *DRAWN, LINE[1], LINE[2]]]
    assert [w["role"] for w in body["waypoints"]] == ["start", "end"]
    assert body["engine"] == "valhalla"
    assert body["attribution"].startswith("Route: Valhalla")
    by_source = {s["source"]: s for s in body["sources"]}
    assert by_source["proposal"]["points"] == 2 and by_source["proposal"]["verified"] is True
    assert by_source["version"]["route_id"] == old.pk and by_source["version"]["verified"]
    assert by_source["drawn"] == {"source": "drawn", "engine": "", "verified": False, "points": 2}
    with as_owner():
        unchanged = Route.objects.get(pk=old.pk)
        assert Leg.objects.get(pk=f.core_leg.pk).current_route_id == body["id"]
    assert unchanged.geom.wkt == old.geom.wkt and unchanged.version == 1


def test_one_whole_proposal_is_saved_as_routed(client, scenario, valhalla):  # noqa: F811
    f = scenario
    login(client, f.alice)
    propose(client)
    body = edited(client, f.core_leg.pk, [proposal_piece()], waypoints=DRAWN).json()
    assert body["kind"] == "routed"
    # its control points are the proposal's waypoints, not what the client sent
    assert [[w["lon"], w["lat"]] for w in body["waypoints"]] == KANSAS


def test_another_users_proposal_is_expired_for_the_caller(client, scenario, valhalla):  # noqa: F811
    f = scenario
    login(client, f.bob)
    propose(client)
    login(client, f.alice)
    response = edited(client, f.core_leg.pk, [drawn_piece(), proposal_piece()])
    assert response.status_code == 409
    assert response.json()["expired"] == [1]
    with as_owner():
        assert Route.objects.filter(leg=f.core_leg).count() == 1


def test_expired_pieces_resent_as_drawn_keep_the_providers_credit(client, scenario):
    f = scenario
    login(client, f.alice)
    body = edited(client, f.core_leg.pk, [drawn_piece(LINE, engine="ors")]).json()
    assert body["kind"] == "hand_edited"
    assert body["engine"] == "ors"
    assert "openrouteservice" in body["attribution"]
    assert body["sources"] == [{"source": "drawn", "engine": "ors", "verified": False, "points": 3}]


def test_a_version_of_another_leg_is_refused(client, scenario):
    f = scenario
    with as_owner():
        other = RouteFactory(leg=f.bob_leg, created_by=f.bob)
    login(client, f.alice)
    piece = {"source": "version", "route_id": other.pk, "start": 0, "end": 1}
    response = edited(client, f.core_leg.pk, [piece])
    assert response.status_code == 422
    assert "unknown route version" in response.json()["detail"]


@pytest.mark.parametrize(
    "pieces",
    [
        [],
        [drawn_piece([[-97.2, 95.0], [-97.0, 37.0]])],
        [drawn_piece([[-197.2, 37.0], [-97.0, 37.0]])],
        [drawn_piece([[-97.2, 37.0, 3.0], [-97.0, 37.0]])],
        [drawn_piece([[-97.2, 37.0]])],  # one point is not a line
        [drawn_piece([[-97.2, 37.0]] * 10_001)],
        [drawn_piece([[-170.0, 0.0], [10.0, 0.0], [-170.0, 0.0]])],  # longer than any road
        [{"source": "drawn", "coordinates": DRAWN, "engine": "google"}],
        [{"source": "teleport", "coordinates": DRAWN}],
        [{"source": "version", "route_id": 0, "start": 0, "end": 1}],
    ],
)
def test_invalid_pieces_are_refused(client, scenario, pieces):
    f = scenario
    login(client, f.alice)
    assert edited(client, f.core_leg.pk, pieces).status_code == 422
    with as_owner():
        assert Route.objects.filter(leg=f.core_leg).count() == 1


def test_slices_outside_the_geometry_are_refused(client, scenario, valhalla):  # noqa: F811
    f = scenario
    login(client, f.alice)
    propose(client)
    assert edited(client, f.core_leg.pk, [proposal_piece(1, 3)]).status_code == 422
    assert edited(client, f.core_leg.pk, [proposal_piece(2, 1)]).status_code == 422
    version = {"source": "version", "route_id": f.route.pk, "start": 0, "end": 9}
    assert edited(client, f.core_leg.pk, [version]).status_code == 422


def test_invalid_control_points_are_refused(client, scenario):
    f = scenario
    login(client, f.alice)
    bad = [[-97.2, 37.0], [500.0, 37.0]]
    assert edited(client, f.core_leg.pk, [drawn_piece()], waypoints=bad).status_code == 422
