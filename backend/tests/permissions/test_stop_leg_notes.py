"""Stop and leg notes (work-order item 14b): private free text on each stop and leg, edited by
whoever may edit that stop or leg and read by whoever can see the trip, like `Trip.notes`. No
rule changed, so these check the existing stop and leg rules carry the new field at the API and
at the SQL/RLS layer (as travel_app), and that the notes stay out of the map overview."""

import pytest
from django.db import DatabaseError, transaction

from tests.helpers import as_owner
from tests.permissions.test_trips_api import ACTORS, API, as_actor, call, login, trip_path
from tests.permissions.test_trips_api_rest import remove_bob
from travel.core.rls import set_context
from travel.trips.models import Leg, Stop

pytestmark = pytest.mark.django_db

R = (401, 401)  # ivan (deactivated) and anonymous
NOTE = {"notes": "Synthetic note: breakfast till 10"}

# name -> (path(f), expected PATCH status per actor in ACTORS order)
EDITS = {
    # Stops are the trip's core itinerary: owner and Admin only.
    "stop": (lambda f: f"{API}/stops/{f.family_stop.pk}", (200, 200, 403, 403, 403, *R)),
    # A core leg: core editors.
    "core_leg": (lambda f: f"{API}/legs/{f.core_leg.pk}", (200, 200, 403, 403, 403, *R)),
    # A contributed leg: only its author, while they may contribute (not even the owner).
    "bob_leg": (lambda f: f"{API}/legs/{f.bob_leg.pk}", (403, 403, 200, 403, 403, *R)),
}
PARAMS = [
    pytest.param(name, actor, status, id=f"{name}-{actor}")
    for name, (_, row) in EDITS.items()
    for actor, status in zip(ACTORS, row, strict=True)
]


@pytest.mark.parametrize(("name", "actor", "expected"), PARAMS)
def test_who_edits_notes(client, scenario, name, actor, expected):
    f = scenario
    path, _ = EDITS[name]
    response = call(as_actor(client, f, actor), "PATCH", path(f), NOTE)
    assert response.status_code == expected, response.content[:300]
    if expected == 200:
        assert response.json()["notes"] == NOTE["notes"]


@pytest.mark.parametrize("actor", ["admin", "alice", "bob", "carol", "victor"])
def test_everyone_who_sees_the_trip_reads_the_notes(client, scenario, actor):
    f = scenario
    with as_owner():
        Stop.objects.filter(pk=f.family_stop.pk).update(notes="Synthetic stop note")
        Leg.objects.filter(pk=f.core_leg.pk).update(notes="Synthetic leg note")
    as_actor(client, f, actor)
    detail = call(client, "GET", trip_path(f, "family")).json()
    stop = next(s for s in detail["stops"] if s["id"] == f.family_stop.pk)
    leg = next(g for g in detail["legs"] if g["id"] == f.core_leg.pk)
    assert (stop["notes"], leg["notes"]) == ("Synthetic stop note", "Synthetic leg note")
    stops = call(client, "GET", trip_path(f, "family", "/stops")).json()
    assert next(s for s in stops if s["id"] == f.family_stop.pk)["notes"] == "Synthetic stop note"
    got = call(client, "GET", f"{API}/legs/{f.core_leg.pk}").json()
    assert got["notes"] == "Synthetic leg note"


def test_hidden_trips_notes_stay_hidden(client, scenario):
    f = scenario
    with as_owner():
        leg = Leg.objects.create(
            trip=f.trips["private"], sequence=1, mode="car", author=f.alice, notes="Secret"
        )
    login(client, f.carol)
    assert call(client, "GET", f"{API}/legs/{leg.pk}").status_code == 404
    assert call(client, "PATCH", f"{API}/legs/{leg.pk}", NOTE).status_code == 404


def test_removed_participant_can_no_longer_edit_notes_on_their_leg(client, scenario):
    f = scenario
    remove_bob(f)
    login(client, f.bob)
    assert call(client, "PATCH", f"{API}/legs/{f.bob_leg.pk}", NOTE).status_code == 403
    with as_owner():
        assert Leg.objects.get(pk=f.bob_leg.pk).notes == ""


def test_notes_set_on_create_cleared_by_null_and_limited_in_length(client, scenario):
    f = scenario
    login(client, f.alice)
    created = call(
        client,
        "POST",
        trip_path(f, "family", "/stops"),
        {"kind": "visit", "place_id": f.family_stop.place_id, **NOTE},
    )
    assert created.status_code == 201, created.content
    assert created.json()["notes"] == NOTE["notes"]
    leg = call(client, "POST", trip_path(f, "family", "/legs"), {"mode": "walk", **NOTE})
    assert leg.status_code == 201 and leg.json()["notes"] == NOTE["notes"]
    for path in (f"{API}/stops/{created.json()['id']}", f"{API}/legs/{leg.json()['id']}"):
        # A patch that leaves notes out keeps them; null clears them.
        other = {"tz": "UTC"} if "/stops/" in path else {"seat": "1A"}
        kept = call(client, "PATCH", path, other)
        assert (kept.status_code, kept.json()["notes"]) == (200, NOTE["notes"])
        cleared = call(client, "PATCH", path, {"notes": None})
        assert (cleared.status_code, cleared.json()["notes"]) == (200, "")
        too_long = call(client, "PATCH", path, {"notes": "x" * 20_001})
        assert too_long.status_code == 422


def test_notes_never_reach_the_map_overview(client, scenario):
    f = scenario
    with as_owner():
        Stop.objects.filter(pk=f.family_stop.pk).update(notes="Synthetic sentinel stop note")
        Leg.objects.filter(pk=f.core_leg.pk).update(notes="Synthetic sentinel leg note")
    login(client, f.alice)
    response = call(client, "GET", f"{API}/trips/map")
    assert response.status_code == 200
    assert b"sentinel" not in response.content


def _sql_update(model, pk, user_id) -> bool:
    try:
        with transaction.atomic():
            set_context(user_id)
            changed = model.objects.filter(pk=pk).update(notes="edited") == 1
            transaction.set_rollback(True)
            return changed
    except DatabaseError:
        return False


@pytest.mark.parametrize(
    ("actor", "stop", "core_leg", "bob_leg"),
    [
        ("admin", True, True, False),
        ("alice", True, True, False),
        ("bob", False, False, True),
        ("carol", False, False, False),
        ("victor", False, False, False),
    ],
)
def test_rls_allows_note_edits_only_to_the_rows_editors(scenario, actor, stop, core_leg, bob_leg):
    """As travel_app: RLS is row-level, so the notes columns follow the stop and leg rules."""
    f = scenario
    user_id = getattr(f, actor).pk
    assert _sql_update(Stop, f.family_stop.pk, user_id) is stop
    assert _sql_update(Leg, f.core_leg.pk, user_id) is core_leg
    assert _sql_update(Leg, f.bob_leg.pk, user_id) is bob_leg
