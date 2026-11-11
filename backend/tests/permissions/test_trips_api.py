"""Trips API (work-order item 6): every endpoint for every actor of the synthetic family
(tests/permissions/conftest.py), through real requests - middleware, authentication, RLS.

A trip the caller can't see answers 404, a visible trip they may not change answers 403, and
signed-out or deactivated callers get 401. The SQL/RLS and policy layers are checked case by
case in test_matrix.py; this file checks that the API asks them and shows no more than allowed.
"""

import json

import pytest

from tests.factories import LegFactory
from tests.helpers import as_owner
from travel.trips.models import Leg, LegParticipantOverride, Purpose, Trip, TripParticipant

pytestmark = pytest.mark.django_db

ACTORS = ("admin", "alice", "bob", "carol", "victor", "ivan", "anon")
API = "/api/v1"


def login(client, user):
    with as_owner():
        client.force_login(user)


def call(client, method: str, path: str, body=None):
    data = json.dumps(body) if body is not None else ""
    return client.generic(method, path, data, content_type="application/json")


def as_actor(client, f, actor: str):
    if actor != "anon":
        login(client, getattr(f, actor))
    return client


def trip_path(f, vis: str, suffix: str = "") -> str:
    return f"{API}/trips/{f.trips[vis].pk}{suffix}"


NEW_TRIP = {"title": "New synthetic trip", "start_date": "2023-03-01", "end_date": "2023-03-03"}

# name -> (method, path(f), body(f) or None, expected status per actor in ACTORS order)
CASES = {
    # --- reads
    "list_trips": ("GET", lambda f: f"{API}/trips", None, (200, 200, 200, 200, 200, 401, 401)),
    "get_trip:private": (
        "GET", lambda f: trip_path(f, "private"), None, (404, 200, 404, 404, 404, 401, 401)
    ),
    "get_trip:participants": (
        "GET", lambda f: trip_path(f, "participants"), None, (404, 200, 200, 404, 404, 401, 401)
    ),
    "get_trip:family": (
        "GET", lambda f: trip_path(f, "family"), None, (200, 200, 200, 200, 200, 401, 401)
    ),
    "get_trip:public": (
        "GET", lambda f: trip_path(f, "public"), None, (200, 200, 200, 200, 200, 401, 401)
    ),
    "get_admin_private_trip": (
        "GET",
        lambda f: f"{API}/trips/{f.admin_private_trip.pk}",
        None,
        (200, 404, 404, 404, 404, 401, 401),
    ),
    "list_legs:participants": (
        "GET",
        lambda f: trip_path(f, "participants", "/legs"),
        None,
        (404, 200, 200, 404, 404, 401, 401),
    ),
    "list_legs:family": (
        "GET", lambda f: trip_path(f, "family", "/legs"), None, (200, 200, 200, 200, 200, 401, 401)
    ),
    "get_core_leg": (
        "GET", lambda f: f"{API}/legs/{f.core_leg.pk}", None, (200, 200, 200, 200, 200, 401, 401)
    ),
    "list_participants:participants": (
        "GET",
        lambda f: trip_path(f, "participants", "/participants"),
        None,
        (404, 200, 200, 404, 404, 401, 401),
    ),
    "list_participants:family": (
        "GET",
        lambda f: trip_path(f, "family", "/participants"),
        None,
        (200, 200, 200, 200, 200, 401, 401),
    ),
    # --- trips
    "create_trip": (
        "POST", lambda f: f"{API}/trips", lambda f: NEW_TRIP, (201, 201, 201, 201, 403, 401, 401)
    ),
    "create_trip_with_alices_purpose": (
        "POST",
        lambda f: f"{API}/trips",
        lambda f: {**NEW_TRIP, "purpose_id": f.alice_purpose.pk},
        (422, 201, 422, 422, 403, 401, 401),
    ),
    "edit_trip:private": (
        "PATCH",
        lambda f: trip_path(f, "private"),
        lambda f: {"title": "edited"},
        (404, 200, 404, 404, 404, 401, 401),
    ),
    "edit_trip:participants": (
        "PATCH",
        lambda f: trip_path(f, "participants"),
        lambda f: {"title": "edited"},
        (404, 200, 403, 404, 404, 401, 401),
    ),
    "edit_trip:family": (
        "PATCH",
        lambda f: trip_path(f, "family"),
        lambda f: {"title": "edited", "visibility": "public"},
        (200, 200, 403, 403, 403, 401, 401),
    ),
    # The Admin can't make a trip invisible to themselves (RLS checks the updated row).
    "make_trip_private:family": (
        "PATCH",
        lambda f: trip_path(f, "family"),
        lambda f: {"visibility": "private"},
        (403, 200, 403, 403, 403, 401, 401),
    ),
    "edit_trip:public": (
        "PATCH",
        lambda f: trip_path(f, "public"),
        lambda f: {"title": "edited"},
        (200, 200, 403, 403, 403, 401, 401),
    ),
    "set_own_purpose:family": (
        "PATCH",
        lambda f: trip_path(f, "family"),
        lambda f: {"purpose_id": f.alice_purpose.pk},
        # The Admin can't see Alice's unused purpose (purposes are their owner's).
        (422, 200, 403, 403, 403, 401, 401),
    ),
    "set_foreign_purpose:family": (
        "PATCH",
        lambda f: trip_path(f, "family"),
        lambda f: {"purpose_id": f.bob_purpose.pk},
        (422, 422, 403, 403, 403, 401, 401),
    ),
    "delete_trip:family": (
        "DELETE", lambda f: trip_path(f, "family"), None, (403, 204, 403, 403, 403, 401, 401)
    ),
    "delete_trip:private": (
        "DELETE", lambda f: trip_path(f, "private"), None, (404, 204, 404, 404, 404, 401, 401)
    ),
    "delete_admin_private_trip": (
        "DELETE",
        lambda f: f"{API}/trips/{f.admin_private_trip.pk}",
        None,
        (204, 404, 404, 404, 404, 401, 401),
    ),
    # --- legs
    "add_leg:private": (
        "POST",
        lambda f: trip_path(f, "private", "/legs"),
        lambda f: {"mode": "drive"},
        (404, 201, 404, 404, 404, 401, 401),
    ),
    "add_leg:participants": (
        "POST",
        lambda f: trip_path(f, "participants", "/legs"),
        lambda f: {"mode": "drive"},
        (404, 201, 201, 404, 404, 401, 401),
    ),
    "add_leg:family": (
        "POST",
        lambda f: trip_path(f, "family", "/legs"),
        lambda f: {"mode": "flight"},
        # Victor is a participant, but Viewers are read-only (Q-6).
        (201, 201, 201, 403, 403, 401, 401),
    ),
    "edit_core_leg": (
        "PATCH",
        lambda f: f"{API}/legs/{f.core_leg.pk}",
        lambda f: {"mode": "train"},
        (200, 200, 403, 403, 403, 401, 401),
    ),
    "edit_bobs_leg": (
        "PATCH",
        lambda f: f"{API}/legs/{f.bob_leg.pk}",
        lambda f: {"mode": "bus"},
        (403, 403, 200, 403, 403, 401, 401),
    ),
    "delete_core_leg": (
        "DELETE", lambda f: f"{API}/legs/{f.core_leg.pk}", None, (204, 204, 403, 403, 403, 401, 401)
    ),
    "delete_bobs_leg": (
        "DELETE", lambda f: f"{API}/legs/{f.bob_leg.pk}", None, (403, 403, 204, 403, 403, 401, 401)
    ),
    "use_vehicle_on_core_leg": (
        "PATCH",
        lambda f: f"{API}/legs/{f.core_leg.pk}",
        lambda f: {"vehicle_id": f.vehicle.pk},
        (200, 200, 403, 403, 403, 401, 401),
    ),
    "use_hidden_vehicle_on_core_leg": (
        "PATCH",
        lambda f: f"{API}/legs/{f.core_leg.pk}",
        lambda f: {"vehicle_id": f.hidden_vehicle.pk},
        (422, 200, 403, 403, 403, 401, 401),
    ),
    "use_hidden_vehicle_on_bobs_leg": (
        "PATCH",
        lambda f: f"{API}/legs/{f.bob_leg.pk}",
        lambda f: {"vehicle_id": f.hidden_vehicle.pk},
        (403, 403, 422, 403, 403, 401, 401),
    ),
    "set_own_leg_participation": (
        "PUT",
        lambda f: f"{API}/legs/{f.core_leg.pk}/my-participation",
        lambda f: {"on_leg": False},
        (200, 200, 200, 403, 403, 401, 401),
    ),
    "set_kid_leg_participation": (
        "PUT",
        lambda f: f"{API}/legs/{f.core_leg.pk}/participants/{f.kid.pk}",
        lambda f: {"on_leg": False},
        (200, 200, 403, 403, 403, 401, 401),
    ),
    "include_private_person_on_leg": (
        "PUT",
        lambda f: f"{API}/legs/{f.core_leg.pk}/participants/{f.alices_private_person.pk}",
        lambda f: {"on_leg": True},
        (404, 200, 404, 404, 404, 401, 401),
    ),
    # --- participants
    "add_carol:family": (
        "POST",
        lambda f: trip_path(f, "family", "/participants"),
        lambda f: {"person_id": f.carol.person_id},
        (201, 201, 403, 403, 403, 401, 401),
    ),
    "add_carol:participants": (
        "POST",
        lambda f: trip_path(f, "participants", "/participants"),
        lambda f: {"person_id": f.carol.person_id},
        (404, 201, 403, 404, 404, 401, 401),
    ),
    "add_alices_private_person:family": (
        "POST",
        lambda f: trip_path(f, "family", "/participants"),
        lambda f: {"person_id": f.alices_private_person.pk},
        (404, 201, 403, 403, 403, 401, 401),
    ),
    "add_bob_again:family": (
        "POST",
        lambda f: trip_path(f, "family", "/participants"),
        lambda f: {"person_id": f.bob.person_id},
        (409, 409, 403, 403, 403, 401, 401),
    ),
    "remove_bob:family": (
        "DELETE",
        lambda f: trip_path(f, "family", f"/participants/{f.bob.person_id}"),
        None,
        (204, 204, 403, 403, 403, 401, 401),
    ),
    "remove_carol:family": (
        "DELETE",
        lambda f: trip_path(f, "family", f"/participants/{f.carol.person_id}"),
        None,
        (404, 404, 403, 403, 403, 401, 401),
    ),
    "set_bob_consent": (
        "PUT",
        lambda f: trip_path(f, "family", f"/participants/{f.bob.person_id}/consent"),
        lambda f: {"public_consent": True},
        (403, 403, 200, 403, 403, 401, 401),
    ),
    "set_kid_consent": (
        "PUT",
        lambda f: trip_path(f, "family", f"/participants/{f.kid.pk}/consent"),
        lambda f: {"public_consent": True},
        (200, 403, 403, 403, 403, 401, 401),
    ),
    "set_victor_consent": (
        "PUT",
        lambda f: trip_path(f, "family", f"/participants/{f.victor.person_id}/consent"),
        lambda f: {"public_consent": True},
        (403, 403, 403, 403, 200, 401, 401),
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
    response = call(as_actor(client, f, actor), method, path(f), body(f) if body else None)
    assert response.status_code == expected, response.content[:300]
    if expected < 300 and response.content:
        assert_no_identity(f, response.content)


# --- What each actor sees ---------------------------------------------------------------------


def identity_strings(f) -> list[str]:
    users = (f.admin, f.alice, f.bob, f.carol, f.victor, f.ivan)
    return [s for u in users for s in (u.email, u.oidc_sub)] + [f.alice.oidc_issuer]


def assert_no_identity(f, content: bytes):
    """D-72: other accounts appear by id and display name only - and these endpoints never
    show anyone's email or OIDC identity, not even the caller's own."""
    text = content.decode()
    for value in identity_strings(f):
        assert value not in text


VISIBLE_TRIPS = {
    "admin": {"family", "public", "admin_private"},
    "alice": {"private", "participants", "family", "public"},
    "bob": {"participants", "family", "public"},
    "carol": {"family", "public"},
    "victor": {"family", "public"},
}


@pytest.mark.parametrize("actor", sorted(VISIBLE_TRIPS))
def test_list_shows_exactly_the_visible_trips(client, scenario, actor):
    f = scenario
    ids = {vis: t.pk for vis, t in f.trips.items()} | {"admin_private": f.admin_private_trip.pk}
    body = call(as_actor(client, f, actor), "GET", f"{API}/trips").json()
    assert {t["id"] for t in body["items"]} == {ids[k] for k in VISIBLE_TRIPS[actor]}
    assert body["count"] == len(VISIBLE_TRIPS[actor])
    alice_trip = next(t for t in body["items"] if t["id"] == f.trips["family"].pk)
    assert alice_trip["owner"] == {"id": f.alice.pk, "display_name": "Alice"}
    assert alice_trip["is_owner"] is (actor == "alice")


@pytest.mark.parametrize("actor", ["admin", "alice", "bob", "carol", "victor"])
def test_detail_shows_people_by_name_and_sharing_only_to_editors(client, scenario, actor):
    f = scenario
    body = call(as_actor(client, f, actor), "GET", trip_path(f, "family")).json()
    assert (body["sharing"] is not None) is (actor in ("admin", "alice"))
    assert body["access"]["edit"] is (actor in ("admin", "alice"))
    assert body["access"]["delete"] is (actor == "alice")
    assert body["access"]["add_leg"] == {
        "admin": "core",
        "alice": "core",
        "bob": "contribution",
    }.get(actor)
    names = {p["person"]["display_name"] for p in body["participants"]}
    assert names == {"Bob", "Victor", "Kid", "Ivan"}
    me = [p for p in body["participants"] if p["is_me"]]
    assert [p["person"]["id"] for p in me] == (
        [getattr(f, actor).person_id] if actor in ("bob", "victor") else []
    )
    consent = {p["person"]["display_name"]: p["can_set_consent"] for p in body["participants"]}
    assert consent == {
        "Bob": actor == "bob",
        "Victor": actor == "victor",
        "Kid": actor == "admin",
        "Ivan": False,
    }
    legs = {leg["id"]: leg for leg in body["legs"]}
    assert legs[f.bob_leg.pk]["author"] == {"id": f.bob.pk, "display_name": "Bob"}
    assert legs[f.bob_leg.pk]["can_edit"] is (actor == "bob")
    assert legs[f.core_leg.pk]["can_edit"] is (actor in ("admin", "alice"))
    assert_no_identity(f, json.dumps(body).encode())


@pytest.mark.parametrize("actor", ["admin", "alice", "bob", "carol", "victor"])
def test_hidden_vehicle_on_a_leg_shows_only_to_its_manager(client, scenario, actor):
    f = scenario
    with as_owner():
        Leg.objects.filter(pk=f.core_leg.pk).update(vehicle=f.hidden_vehicle)
    leg = call(as_actor(client, f, actor), "GET", f"{API}/legs/{f.core_leg.pk}").json()
    if actor == "alice":
        assert leg["vehicle"] == {"id": f.hidden_vehicle.pk, "label": "Hidden"}
    else:
        assert leg["vehicle"] is None


def test_admin_edits_a_leg_without_touching_alices_hidden_vehicle(client, scenario):
    f = scenario
    with as_owner():
        Leg.objects.filter(pk=f.core_leg.pk).update(vehicle=f.hidden_vehicle)
    login(client, f.admin)
    response = call(client, "PATCH", f"{API}/legs/{f.core_leg.pk}", {"origin_label": "Depot"})
    assert response.status_code == 200
    assert response.json()["vehicle"] is None
    with as_owner():
        assert Leg.objects.get(pk=f.core_leg.pk).vehicle_id == f.hidden_vehicle.pk


def test_private_person_on_a_trip_is_shown_to_the_trips_viewers(client, scenario):
    """§6.4: a person is visible to anyone who can see a trip they're on."""
    f = scenario
    login(client, f.alice)
    added = call(
        client,
        "POST",
        trip_path(f, "family", "/participants"),
        {"person_id": f.alices_private_person.pk},
    )
    assert added.status_code == 201
    login(client, f.carol)
    people = call(client, "GET", trip_path(f, "family", "/participants")).json()
    assert "Alice's coworker" in {p["person"]["display_name"] for p in people}


def test_leg_include_shares_a_participants_trip_until_removed(client, scenario):
    """Effective participation: being added to one leg shares the trip (§6.2); removing the
    person from the trip removes that leg include as well (D-81)."""
    f = scenario
    with as_owner():
        leg = LegFactory(trip=f.trips["participants"], author=f.alice, sequence=1)
    login(client, f.carol)
    assert call(client, "GET", trip_path(f, "participants")).status_code == 404

    login(client, f.alice)
    put = call(
        client, "PUT", f"{API}/legs/{leg.pk}/participants/{f.carol.person_id}", {"on_leg": True}
    )
    assert put.status_code == 200
    assert f.carol.person_id in put.json()["participant_ids"]

    login(client, f.carol)
    trip = call(client, "GET", trip_path(f, "participants")).json()
    carol = next(p for p in trip["participants"] if p["is_me"])
    assert (carol["on_trip"], carol["leg_ids"]) == (False, [leg.pk])
    assert trip["access"]["add_leg"] == "contribution"

    login(client, f.alice)
    removed = call(
        client, "DELETE", trip_path(f, "participants", f"/participants/{f.carol.person_id}")
    )
    assert removed.status_code == 204
    login(client, f.carol)
    assert call(client, "GET", trip_path(f, "participants")).status_code == 404


def test_viewer_on_a_participants_trip_reads_and_sets_only_own_consent(client, scenario):
    f = scenario
    with as_owner():
        TripParticipant.objects.create(
            trip=f.trips["participants"], person=f.victor.person, added_by=f.alice
        )
    login(client, f.victor)
    assert call(client, "GET", trip_path(f, "participants")).status_code == 200
    add_leg = call(client, "POST", trip_path(f, "participants", "/legs"), {"mode": "walk"})
    assert add_leg.status_code == 403
    consent = call(
        client,
        "PUT",
        trip_path(f, "participants", f"/participants/{f.victor.person_id}/consent"),
        {"public_consent": True},
    )
    assert consent.status_code == 200
    assert consent.json()["public_consent"] is True


# --- Writes do what they say -------------------------------------------------------------------


def test_participant_adds_own_leg_and_owner_adds_core_leg(client, scenario):
    f = scenario
    login(client, f.bob)
    bob = call(client, "POST", trip_path(f, "family", "/legs"), {"mode": "flight"}).json()
    assert (bob["is_contribution"], bob["participant_scope"]) == (True, "author")
    assert bob["author"] == {"id": f.bob.pk, "display_name": "Bob"}
    assert bob["participant_ids"] == [f.bob.person_id]
    widened = call(client, "PATCH", f"{API}/legs/{bob['id']}", {"participant_scope": "trip"})
    assert widened.status_code == 422

    login(client, f.alice)
    alice = call(client, "POST", trip_path(f, "family", "/legs"), {"mode": "drive"}).json()
    assert (alice["is_contribution"], alice["participant_scope"]) == (False, "trip")
    assert alice["sequence"] == bob["sequence"] + 1
    assert f.bob.person_id in alice["participant_ids"]


def test_own_leg_participation_is_stored_as_an_override(client, scenario):
    f = scenario
    login(client, f.bob)
    off = call(client, "PUT", f"{API}/legs/{f.core_leg.pk}/my-participation", {"on_leg": False})
    assert off.status_code == 200
    assert f.bob.person_id not in off.json()["participant_ids"]
    with as_owner():
        override = LegParticipantOverride.objects.get(leg=f.core_leg, person=f.bob.person)
        assert (override.include, override.set_by_id) == (False, f.bob.pk)
    back = call(client, "PUT", f"{API}/legs/{f.core_leg.pk}/my-participation", {"on_leg": True})
    assert f.bob.person_id in back.json()["participant_ids"]
    with as_owner():
        assert not LegParticipantOverride.objects.filter(
            leg=f.core_leg, person=f.bob.person
        ).exists()


def test_create_trip_defaults(client, scenario):
    f = scenario
    with as_owner():
        work = Purpose.objects.create(owner=f.alice, name="Work", default_visibility="private")
    login(client, f.alice)
    plain = call(client, "POST", f"{API}/trips", NEW_TRIP).json()
    assert (plain["visibility"], plain["status"], plain["source"]) == (
        "participants",
        "confirmed",
        "manual",
    )
    assert plain["owner"]["id"] == f.alice.pk
    assert plain["sharing"]["public_mode"] == ""
    assert plain["edited_in_app_at"] is not None
    worktrip = call(client, "POST", f"{API}/trips", {**NEW_TRIP, "purpose_id": work.pk}).json()
    assert worktrip["visibility"] == "private"
    assert worktrip["purpose"] == {"id": work.pk, "name": "Work"}
    public = call(client, "POST", f"{API}/trips", {**NEW_TRIP, "visibility": "public"}).json()
    assert public["sharing"]["public_mode"] == "unlisted"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({**NEW_TRIP, "end_date": "2023-02-01"}, 422),
        ({**NEW_TRIP, "title": ""}, 422),
        ({**NEW_TRIP, "public_mode": "listed"}, 422),
        ({**NEW_TRIP, "visibility": "secret"}, 422),
        ({**NEW_TRIP, "notes": None}, 422),
    ],
)
def test_create_trip_validation(client, scenario, body, status):
    login(client, scenario.alice)
    assert call(client, "POST", f"{API}/trips", body).status_code == status


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"mode": "drive", "start_tz": "Mars/Olympus"}, 422),
        ({"mode": "drive", "start_utc": "2024-05-01T10:00:00"}, 422),
        (
            {
                "mode": "drive",
                "start_utc": "2024-05-01T10:00:00Z",
                "end_utc": "2024-05-01T09:00:00Z",
            },
            422,
        ),
        ({"mode": "teleport"}, 422),
        ({"mode": "flight", "airline_id": 999999}, 422),
        (
            {
                "mode": "drive",
                "start_utc": "2024-05-01T10:00:00-05:00",
                "start_tz": "America/Chicago",
            },
            201,
        ),
    ],
)
def test_create_leg_validation(client, scenario, body, status):
    login(client, scenario.alice)
    response = call(client, "POST", trip_path(scenario, "family", "/legs"), body)
    assert response.status_code == status, response.content[:300]


def test_owner_edits_visibility_and_records_the_in_app_edit(client, scenario):
    f = scenario
    login(client, f.alice)
    response = call(
        client, "PATCH", trip_path(f, "family"), {"visibility": "public", "public_mode": "listed"}
    )
    assert response.status_code == 200
    with as_owner():
        trip = Trip.objects.get(pk=f.trips["family"].pk)
    assert (trip.visibility, trip.public_mode) == ("public", "listed")
    assert trip.edited_in_app_at is not None
    back = call(client, "PATCH", trip_path(f, "family"), {"visibility": "participants"})
    assert back.json()["sharing"]["public_mode"] == ""
    login(client, f.carol)
    assert call(client, "GET", trip_path(f, "family")).status_code == 404


def test_owner_delete_removes_legs_and_participants(client, scenario):
    f = scenario
    login(client, f.alice)
    assert call(client, "DELETE", trip_path(f, "family")).status_code == 204
    with as_owner():
        assert not Trip.objects.filter(pk=f.trips["family"].pk).exists()
        assert not Leg.objects.filter(trip_id=f.trips["family"].pk).exists()
        assert not TripParticipant.objects.filter(trip_id=f.trips["family"].pk).exists()


def test_list_filters_stay_within_visible_trips(client, scenario):
    f = scenario
    login(client, f.carol)
    # Bob is on all four of Alice's trips; Carol sees only the two she may see.
    body = call(client, "GET", f"{API}/trips?person={f.bob.person_id}").json()
    assert {t["id"] for t in body["items"]} == {f.trips["family"].pk, f.trips["public"].pk}
    assert call(client, "GET", f"{API}/trips?visibility=private").json()["count"] == 0
