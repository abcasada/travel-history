"""Read endpoints added for the catalog UI (work-order item 20): people (the participant
picker), creating a traveller and one's own person, the trip map, and airport search - every
endpoint for every actor of the synthetic family (tests/permissions/conftest.py).

Same conventions as test_trips_api.py: 401 signed out or deactivated, 403 for a role that may
not act, 404 for what the caller can't see. The SQL layer for creating and linking a person is
in test_matrix.py (`create_person`, `link_own_new_person`).
"""

import pytest
from django.contrib.gis.geos import Point

from tests.factories import UserFactory
from tests.helpers import as_owner
from tests.permissions.test_trips_api import (
    ACTORS,
    API,
    VISIBLE_TRIPS,
    as_actor,
    assert_no_identity,
    call,
    login,
)
from travel.accounts.models import Person, User
from travel.geo.models import Airport
from travel.trips.models import Leg, Place, Stop

pytestmark = pytest.mark.django_db

R = (401, 401)  # ivan (deactivated) and anonymous

CASES = {
    "list_persons": ("GET", f"{API}/persons", None, (200, 200, 200, 200, 200, *R)),
    "create_person": (
        "POST", f"{API}/persons", {"display_name": "Synthetic friend"},
        (201, 201, 201, 201, 403, *R),
    ),
    # Everyone in the family fixture already has a person.
    "create_my_person": ("POST", f"{API}/me/person", None, (409, 409, 409, 409, 403, *R)),
    "trip_map": ("GET", f"{API}/trips/map", None, (200, 200, 200, 200, 200, *R)),
    "search_airports": (
        "GET", f"{API}/reference/airports?q=SYN", None, (200, 200, 200, 200, 200, *R)
    ),
}  # fmt: skip

PARAMS = [
    pytest.param(name, actor, status, id=f"{name}-{actor}")
    for name, (_, _, _, row) in CASES.items()
    for actor, status in zip(ACTORS, row, strict=True)
]


@pytest.mark.parametrize(("name", "actor", "expected"), PARAMS)
def test_api_matrix(client, scenario, name, actor, expected):
    f = scenario
    method, path, body, _ = CASES[name]
    response = call(as_actor(client, f, actor), method, path, body)
    assert response.status_code == expected, response.content[:300]
    if expected < 300 and response.content:
        assert_no_identity(f, response.content)


# --- People ----------------------------------------------------------------------------------


def names(response) -> set[str]:
    return {p["display_name"] for p in response.json()}


def test_people_follow_person_visibility(client, scenario):
    f = scenario
    family_people = {"Admin", "Alice", "Bob", "Carol", "Victor", "Ivan", "Kid"}
    alice = names(call(as_actor(client, f, "alice"), "GET", f"{API}/persons"))
    assert alice == family_people | {"Alice's coworker"}
    carol = names(call(as_actor(client, f, "carol"), "GET", f"{API}/persons"))
    assert carol == family_people


def test_people_say_who_is_me_and_who_I_manage(client, scenario):
    f = scenario
    rows = call(as_actor(client, f, "admin"), "GET", f"{API}/persons").json()
    assert rows[0]["display_name"] == "Admin" and rows[0]["is_me"]
    by_name = {p["display_name"]: p for p in rows}
    assert by_name["Kid"]["can_edit"] and not by_name["Kid"]["has_account"]
    assert by_name["Alice"]["has_account"] and not by_name["Alice"]["can_edit"]
    assert not any(p["is_me"] for p in rows[1:])


def test_created_person_is_managed_by_its_creator(client, scenario):
    f = scenario
    response = call(
        as_actor(client, f, "bob"),
        "POST",
        f"{API}/persons",
        {"display_name": "  Synthetic niece ", "visibility": "private"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["display_name"] == "Synthetic niece"
    assert body["can_edit"] and not body["has_account"] and not body["is_me"]
    # Private: Bob sees her, Carol doesn't.
    assert "Synthetic niece" in names(call(client, "GET", f"{API}/persons"))
    carol = names(call(as_actor(client, f, "carol"), "GET", f"{API}/persons"))
    assert "Synthetic niece" not in carol


@pytest.mark.parametrize(
    "body",
    [{"display_name": ""}, {"display_name": "x" * 151}, {"display_name": "A", "visibility": "public"}],
)
def test_person_validation(client, scenario, body):
    response = call(as_actor(client, scenario, "alice"), "POST", f"{API}/persons", body)
    assert response.status_code == 422


def test_an_account_without_a_person_creates_and_links_its_own_once(client, scenario):
    with as_owner():
        newcomer = UserFactory(display_name="Synthetic newcomer")
    login(client, newcomer)
    first = call(client, "POST", f"{API}/me/person")
    assert first.status_code == 201
    person_id = first.json()["person_id"]
    assert person_id is not None
    with as_owner():
        assert User.objects.get(pk=newcomer.pk).person_id == person_id
        person = Person.objects.get(pk=person_id)
        assert (person.display_name, person.created_by_id) == ("Synthetic newcomer", newcomer.pk)
    assert call(client, "POST", f"{API}/me/person").status_code == 409
    mine = [p for p in call(client, "GET", f"{API}/persons").json() if p["is_me"]]
    assert [(p["id"], p["has_account"], p["can_edit"]) for p in mine] == [(person_id, True, True)]


def test_a_viewer_without_a_person_cannot_create_one(client, scenario):
    with as_owner():
        viewer = UserFactory(role="viewer")
    login(client, viewer)
    assert call(client, "POST", f"{API}/me/person").status_code == 403
    with as_owner():
        assert User.objects.get(pk=viewer.pk).person_id is None


# --- Trip map --------------------------------------------------------------------------------


def add_route_stops(f):
    """Two stops on the family trip and a leg between them; a stop on the private trip."""
    with as_owner():
        fam = f.trips["family"]
        start = Stop.objects.create(
            trip=fam,
            kind="waypoint",
            author=f.alice,
            place=Place.objects.create(
                owner=f.alice, name="Synthetic Start", point=Point(-97.0, 38.0, srid=4326)
            ),
        )
        end = Stop.objects.create(
            trip=fam,
            kind="destination",
            author=f.alice,
            place=Place.objects.create(
                owner=f.alice, name="Synthetic End", point=Point(-96.0, 39.0, srid=4326)
            ),
        )
        Leg.objects.filter(pk=f.core_leg.pk).update(origin_stop=start, destination_stop=end)
        Stop.objects.create(
            trip=f.trips["private"],
            kind="lodging",
            author=f.alice,
            place=Place.objects.create(
                owner=f.alice, name="Synthetic Hideaway", point=Point(-95.0, 37.0, srid=4326)
            ),
        )


def trip_keys(f) -> dict[int, str]:
    keys = {trip.pk: vis for vis, trip in f.trips.items()}
    keys[f.admin_private_trip.pk] = "admin_private"
    return keys


@pytest.mark.parametrize("actor", ["admin", "alice", "bob", "carol", "victor"])
def test_trip_map_shows_only_visible_trips_and_their_stops(client, scenario, actor):
    f = scenario
    add_route_stops(f)
    body = call(as_actor(client, f, actor), "GET", f"{API}/trips/map").json()
    keys = trip_keys(f)
    assert {keys[t["id"]] for t in body["trips"]} == VISIBLE_TRIPS[actor]
    stop_names = {s["name"] for s in body["stops"]}
    assert ("Synthetic Hideaway" in stop_names) == (actor == "alice")
    assert {"Synthetic Start", "Synthetic End", "Synthetic Inn"} <= stop_names
    assert {keys[s["trip_id"]] for s in body["stops"]} <= VISIBLE_TRIPS[actor]
    legs = {g["id"]: g for g in body["legs"]}
    # Only legs with both end points are drawn; this one is a straight line until routed.
    assert set(legs) == {f.core_leg.pk}
    assert legs[f.core_leg.pk]["coordinates"] == [[-97.0, 38.0], [-96.0, 39.0]]
    assert legs[f.core_leg.pk]["routed"] is False
    assert body["truncated"] is False


def test_trip_map_uses_the_list_filters(client, scenario):
    f = scenario
    add_route_stops(f)
    as_actor(client, f, "alice")
    by_tag = call(client, "GET", f"{API}/trips/map?tag={f.bob_tag.pk}").json()
    assert [t["id"] for t in by_tag["trips"]] == [f.trips["family"].pk]
    boxed = call(client, "GET", f"{API}/trips/map?bbox=-95.5,36.5,-94.5,37.5").json()
    assert [t["id"] for t in boxed["trips"]] == [f.trips["private"].pk]
    assert [s["name"] for s in boxed["stops"]] == ["Synthetic Hideaway"]
    assert call(client, "GET", f"{API}/trips/map?bbox=nonsense").status_code == 422


def test_flight_legs_fall_back_to_their_airports(client, scenario):
    f = scenario
    with as_owner():
        ict = Airport.objects.create(
            ident="KSYA", type="large_airport", name="Synthetic A", point=Point(-97.4, 37.6)
        )
        den = Airport.objects.create(
            ident="KSYB", type="large_airport", name="Synthetic B", point=Point(-104.7, 39.9)
        )
        Leg.objects.filter(pk=f.core_leg.pk).update(
            mode="flight", origin_airport=ict, destination_airport=den
        )
    body = call(as_actor(client, f, "carol"), "GET", f"{API}/trips/map").json()
    leg = next(g for g in body["legs"] if g["id"] == f.core_leg.pk)
    assert leg["mode"] == "flight"
    assert leg["coordinates"] == [[-97.4, 37.6], [-104.7, 39.9]]


# --- Airport search ---------------------------------------------------------------------------


def test_airport_search_by_code_then_name(client, scenario):
    f = scenario
    with as_owner():
        Airport.objects.create(
            ident="KSYN", iata_code="SYN", icao_code="KSYN", type="large_airport",
            name="Synthetic International", municipality="Synthville", scheduled_service=True,
            point=Point(-97.0, 37.0),
        )
        Airport.objects.create(
            ident="XS01", type="small_airport", name="Synthetic Strip SYN",
            municipality="Elsewhere", point=Point(-98.0, 38.0),
        )
        Airport.objects.create(
            ident="XS02", type="closed", name="Closed Synthetic Field SYN", point=Point(0, 0)
        )
    as_actor(client, f, "victor")
    rows = call(client, "GET", f"{API}/reference/airports?q=syn").json()
    assert [r["ident"] for r in rows] == ["KSYN", "XS01"]
    assert rows[0]["lon"] == -97.0 and rows[0]["iata_code"] == "SYN"
    by_city = call(client, "GET", f"{API}/reference/airports?q=synthv").json()
    assert [r["ident"] for r in by_city] == ["KSYN"]
    assert call(client, "GET", f"{API}/reference/airports?q=s").status_code == 422
