"""Permission matrix (PLAN.md §6.3), checked twice per case:

1. SQL level - as the runtime role `travel_app` with the actor's RLS context, by actually
   reading/updating/inserting/deleting rows (row-level security + guard triggers).
2. App level - through travel.core.policy, which the API consults.

Both layers must give the expected answer. Every row of the matrix in PLAN.md §6.3 maps to one
or more actions below; when the matrix changes, this table changes with it.
"""

import datetime as dt

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import DatabaseError, transaction

from travel.accounts.models import AccessRequest, DeviceToken, Person, User
from travel.core import policy
from travel.core.rls import set_context
from travel.history.models import HomePeriod, LocationPoint, RawFile, TimelineSegment
from travel.trips.models import (
    Leg,
    LegParticipantOverride,
    Route,
    Trip,
    TripNote,
    TripParticipant,
)
from travel.vehicles.models import Vehicle, VehiclePrivate

pytestmark = pytest.mark.django_db

ACTORS = ("admin", "alice", "bob", "carol", "victor", "ivan", "anon")


# --- SQL probes (always rolled back) -------------------------------------------------------


class _Rollback(Exception):
    def __init__(self, value):
        self.value = value


def _rolled_back(fn):
    """Run fn in a savepoint that is always rolled back; database errors count as denied."""
    try:
        with transaction.atomic():
            raise _Rollback(fn())
    except _Rollback as done:
        return done.value
    except DatabaseError:
        return False


def sees(model, pk):
    return model.objects.filter(pk=pk).exists()


def updates(model, pk, **values):
    return _rolled_back(lambda: model.objects.filter(pk=pk).update(**values) == 1)


def deletes(model, pk):
    return _rolled_back(lambda: model.objects.filter(pk=pk)._raw_delete("default") > 0)


def inserts(build):
    return _rolled_back(lambda: build() is not None)


def uid(f, actor):
    """The acting user, or alice's id as a stand-in owner for anonymous attempts."""
    return actor.pk if actor else f.alice.pk


def person_of(f, actor):
    return actor.person if actor else f.bob.person


# --- Actions: name -> (sql probe, policy probe) --------------------------------------------


def _trip_actions():
    actions = {}
    for vis in ("private", "participants", "family", "public"):
        actions[f"view_trip:{vis}"] = (
            lambda f, a, v=vis: sees(Trip, f.trips[v].pk),
            lambda f, u, v=vis: policy.can_view_trip(u, f.trips[v]),
        )
        actions[f"edit_trip:{vis}"] = (
            lambda f, a, v=vis: updates(Trip, f.trips[v].pk, title="edited"),
            lambda f, u, v=vis: policy.can_edit_trip_core(u, f.trips[v]),
        )
    return actions


ACTIONS = {
    **_trip_actions(),
    "view_admin_private_trip": (
        lambda f, a: sees(Trip, f.admin_private_trip.pk),
        lambda f, u: policy.can_view_trip(u, f.admin_private_trip),
    ),
    "delete_trip:family": (
        lambda f, a: deletes(Trip, f.trips["family"].pk),
        lambda f, u: policy.can_delete_trip(u, f.trips["family"]),
    ),
    "create_trip": (
        lambda f, a: inserts(
            lambda: Trip.objects.create(
                owner_id=uid(f, a),
                title="new",
                start_date=dt.date(2020, 1, 1),
                end_date=dt.date(2020, 1, 2),
            )
        ),
        lambda f, u: policy.can_create(u),
    ),
    "add_note:family": (
        lambda f, a: inserts(
            lambda: TripNote.objects.create(trip=f.trips["family"], author_id=uid(f, a), body="n")
        ),
        lambda f, u: policy.can_contribute(u, f.trips["family"]),
    ),
    "add_note:participants": (
        lambda f, a: inserts(
            lambda: TripNote.objects.create(
                trip=f.trips["participants"], author_id=uid(f, a), body="n"
            )
        ),
        lambda f, u: policy.can_contribute(u, f.trips["participants"]),
    ),
    "edit_bobs_note": (
        lambda f, a: updates(TripNote, f.bob_note.pk, body="changed"),
        lambda f, u: policy.can_edit_contribution(u, f.bob_note),
    ),
    "delete_bobs_note": (
        lambda f, a: deletes(TripNote, f.bob_note.pk),
        lambda f, u: policy.can_edit_contribution(u, f.bob_note),
    ),
    "add_contribution_leg:family": (
        lambda f, a: inserts(
            lambda: Leg.objects.create(
                trip=f.trips["family"],
                sequence=90,
                mode="flight",
                author_id=uid(f, a),
                is_contribution=True,
                participant_scope="author",
            )
        ),
        lambda f, u: policy.can_contribute(u, f.trips["family"]),
    ),
    "add_core_leg:family": (
        lambda f, a: inserts(
            lambda: Leg.objects.create(
                trip=f.trips["family"], sequence=91, mode="drive", author_id=uid(f, a)
            )
        ),
        lambda f, u: policy.can_edit_trip_core(u, f.trips["family"]),
    ),
    "edit_core_leg": (
        lambda f, a: updates(Leg, f.core_leg.pk, mode="train"),
        lambda f, u: policy.can_edit_leg(u, f.core_leg),
    ),
    "edit_bobs_leg": (
        lambda f, a: updates(Leg, f.bob_leg.pk, mode="bus"),
        lambda f, u: policy.can_edit_leg(u, f.bob_leg),
    ),
    "delete_bobs_leg": (
        lambda f, a: deletes(Leg, f.bob_leg.pk),
        lambda f, u: policy.can_edit_leg(u, f.bob_leg),
    ),
    "add_route_version": (
        lambda f, a: inserts(
            lambda: Route.objects.create(
                leg=f.core_leg,
                version=2,
                geom=f.route.geom,
                kind="hand_edited",
                produced_at=f.now,
                created_by_id=uid(f, a),
                length_m=1.0,
            )
        ),
        lambda f, u: policy.can_edit_leg(u, f.core_leg),
    ),
    "update_route": (
        lambda f, a: updates(Route, f.route.pk, note="x"),
        lambda f, u: False,  # saved routes are frozen for everyone
    ),
    "set_own_leg_participation": (
        lambda f, a: inserts(
            lambda: LegParticipantOverride.objects.create(
                leg=f.core_leg, person=person_of(f, a), include=False, set_by_id=uid(f, a)
            )
        ),
        lambda f, u: (
            u.is_authenticated
            and policy.can_set_leg_participation(u, f.core_leg, f.person_by_user[u.pk])
        ),
    ),
    "set_kid_leg_participation": (
        lambda f, a: inserts(
            lambda: LegParticipantOverride.objects.create(
                leg=f.core_leg, person=f.kid, include=True, set_by_id=uid(f, a)
            )
        ),
        lambda f, u: policy.can_set_leg_participation(u, f.core_leg, f.kid),
    ),
    "set_bob_consent": (
        lambda f, a: updates(TripParticipant, f.bob_participation_pk, public_consent=True),
        lambda f, u: policy.can_set_public_consent(u, f.bob.person),
    ),
    "set_kid_consent": (
        lambda f, a: updates(TripParticipant, f.kid_participation_pk, public_consent=True),
        lambda f, u: policy.can_set_public_consent(u, f.kid),
    ),
    "view_alice_points": (
        lambda f, a: sees(LocationPoint, f.alice_point.pk),
        lambda f, u: policy.can_access_raw_history(u, f.alice.pk),
    ),
    "insert_point_for_alice": (
        lambda f, a: inserts(
            lambda: LocationPoint.objects.create(
                owner=f.alice, ts=f.now, geom=f.alice_point.geom, source="owntracks"
            )
        ),
        lambda f, u: policy.can_access_raw_history(u, f.alice.pk),
    ),
    "view_alice_segment": (
        lambda f, a: sees(TimelineSegment, f.alice_segment.pk),
        lambda f, u: policy.can_access_raw_history(u, f.alice.pk),
    ),
    "view_alice_rawfile": (
        lambda f, a: sees(RawFile, f.alice_raw.pk),
        lambda f, u: policy.can_access_raw_history(u, f.alice.pk),
    ),
    "view_alice_token": (
        lambda f, a: sees(DeviceToken, f.alice_token.pk),
        lambda f, u: policy.can_access_raw_history(u, f.alice.pk),
    ),
    "view_alice_home": (
        lambda f, a: sees(HomePeriod, f.alice_home.pk),
        lambda f, u: policy.can_view_home_period(u, f.alice_home),
    ),
    "view_alice_shared_home": (
        lambda f, a: sees(HomePeriod, f.alice_shared_home.pk),
        lambda f, u: policy.can_view_home_period(u, f.alice_shared_home),
    ),
    "edit_alice_shared_home": (
        lambda f, a: updates(HomePeriod, f.alice_shared_home.pk, label="x"),
        lambda f, u: policy.can_edit_home_period(u, f.alice_shared_home),
    ),
    "view_vehicle": (
        lambda f, a: sees(Vehicle, f.vehicle.pk),
        lambda f, u: policy.can_view_vehicle(u, f.vehicle),
    ),
    "view_hidden_vehicle": (
        lambda f, a: sees(Vehicle, f.hidden_vehicle.pk),
        lambda f, u: policy.can_view_vehicle(u, f.hidden_vehicle),
    ),
    "edit_vehicle": (
        lambda f, a: updates(Vehicle, f.vehicle.pk, color="red"),
        lambda f, u: policy.can_manage_vehicle(u, f.vehicle),
    ),
    "edit_hidden_vehicle": (
        lambda f, a: updates(Vehicle, f.hidden_vehicle.pk, color="red"),
        lambda f, u: policy.can_manage_vehicle(u, f.hidden_vehicle),
    ),
    "edit_kid_vehicle": (
        lambda f, a: updates(Vehicle, f.kid_vehicle.pk, color="red"),
        lambda f, u: policy.can_manage_vehicle(u, f.kid_vehicle),
    ),
    "edit_carol_entered_vehicle": (
        lambda f, a: updates(Vehicle, f.carol_entered_vehicle.pk, color="red"),
        lambda f, u: policy.can_manage_vehicle(u, f.carol_entered_vehicle),
    ),
    "view_plate": (
        lambda f, a: sees(VehiclePrivate, f.vehicle.pk),
        lambda f, u: policy.can_view_vehicle_private(u, f.vehicle),
    ),
    "view_access_request": (
        lambda f, a: sees(AccessRequest, f.request.pk),
        lambda f, u: policy.can_manage_access(u),
    ),
    "make_alice_admin": (
        lambda f, a: updates(User, f.alice.pk, role="admin"),
        lambda f, u: policy.can_change_role(u, f.alice),
    ),
    "view_kid": (lambda f, a: sees(Person, f.kid.pk), None),
    "view_alices_private_person": (lambda f, a: sees(Person, f.alices_private_person.pk), None),
}

T, F = True, False
# Columns: admin, alice, bob, carol, victor (viewer), ivan (inactive), anonymous
MATRIX = {
    "view_trip:private":           (F, T, F, F, F, F, F),
    "view_trip:participants":      (F, T, T, F, F, F, F),
    "view_trip:family":            (T, T, T, T, T, F, F),
    "view_trip:public":            (T, T, T, T, T, F, F),
    "view_admin_private_trip":     (T, F, F, F, F, F, F),
    "edit_trip:private":           (F, T, F, F, F, F, F),
    "edit_trip:participants":      (F, T, F, F, F, F, F),
    "edit_trip:family":            (T, T, F, F, F, F, F),
    "edit_trip:public":            (T, T, F, F, F, F, F),
    "delete_trip:family":          (F, T, F, F, F, F, F),
    "create_trip":                 (T, T, T, T, F, F, F),
    "add_note:family":             (F, T, T, F, F, F, F),
    "add_note:participants":       (F, T, T, F, F, F, F),
    "edit_bobs_note":              (F, F, T, F, F, F, F),
    "delete_bobs_note":            (F, F, T, F, F, F, F),
    "add_contribution_leg:family": (F, T, T, F, F, F, F),
    "add_core_leg:family":         (T, T, F, F, F, F, F),
    "edit_core_leg":               (T, T, F, F, F, F, F),
    "edit_bobs_leg":               (F, F, T, F, F, F, F),
    "delete_bobs_leg":             (F, F, T, F, F, F, F),
    "add_route_version":           (T, T, F, F, F, F, F),
    "update_route":                (F, F, F, F, F, F, F),
    "set_own_leg_participation":   (T, T, T, F, F, F, F),
    "set_kid_leg_participation":   (T, T, F, F, F, F, F),
    "set_bob_consent":             (F, F, T, F, F, F, F),
    "set_kid_consent":             (T, F, F, F, F, F, F),
    "view_alice_points":           (F, T, F, F, F, F, F),
    "insert_point_for_alice":      (F, T, F, F, F, F, F),
    "view_alice_segment":          (F, T, F, F, F, F, F),
    "view_alice_rawfile":          (F, T, F, F, F, F, F),
    "view_alice_token":            (F, T, F, F, F, F, F),
    "view_alice_home":             (F, T, F, F, F, F, F),
    "view_alice_shared_home":      (T, T, T, T, T, F, F),
    "edit_alice_shared_home":      (F, T, F, F, F, F, F),
    "view_vehicle":                (T, T, T, T, T, F, F),
    "view_hidden_vehicle":         (F, T, F, F, F, F, F),
    "edit_vehicle":                (T, T, F, F, F, F, F),
    "edit_hidden_vehicle":         (F, T, F, F, F, F, F),
    "edit_kid_vehicle":            (T, F, F, F, F, F, F),
    "edit_carol_entered_vehicle":  (T, T, F, F, F, F, F),
    "view_plate":                  (F, T, F, F, F, F, F),
    "view_access_request":         (T, F, F, F, F, F, F),
    "make_alice_admin":            (T, F, F, F, F, F, F),
    "view_kid":                    (T, T, T, T, T, F, F),
    "view_alices_private_person":  (F, T, F, F, F, F, F),
}  # fmt: skip

CASES = [
    pytest.param(action, actor, expected, id=f"{action}-{actor}")
    for action, row in MATRIX.items()
    for actor, expected in zip(ACTORS, row, strict=True)
]


def test_every_action_has_a_matrix_row():
    assert set(ACTIONS) == set(MATRIX)


@pytest.fixture
def scenario(family):
    from tests.helpers import as_owner

    with as_owner():
        family.kid_participation_pk = TripParticipant.objects.get(
            trip=family.trips["family"], person=family.kid
        ).pk
        family.person_by_user = {
            u.pk: u.person
            for u in (
                family.admin,
                family.alice,
                family.bob,
                family.carol,
                family.victor,
                family.ivan,
            )
        }
        family.bob_participation_pk = TripParticipant.objects.get(
            trip=family.trips["family"], person=family.bob.person
        ).pk
    return family


@pytest.mark.parametrize(("action", "actor_name", "expected"), CASES)
def test_permission_matrix(scenario, action, actor_name, expected):
    f = scenario
    actor = getattr(f, actor_name)
    sql_probe, policy_probe = ACTIONS[action]

    set_context(actor.pk if actor else None)
    assert sql_probe(f, actor) is expected, f"SQL/RLS layer: {action} by {actor_name}"

    if policy_probe is not None:
        user = actor if actor else AnonymousUser()
        if actor is not None:
            user.refresh_from_db()
        assert bool(policy_probe(f, user)) is expected, f"policy layer: {action} by {actor_name}"
