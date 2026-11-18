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
from django.db import DatabaseError, connection, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange

from tests.helpers import as_owner
from travel.accounts.models import AccessRequest, DeviceToken, Person, User, UserDirectory
from travel.core import policy
from travel.core.rls import set_context
from travel.flights.models import FlightRecord
from travel.history.models import HomePeriod, LocationPoint, RawFile, TimelineSegment
from travel.media.models import Media
from travel.routing.models import RouteRequestCache
from travel.trips.models import (
    Leg,
    LegParticipantOverride,
    Place,
    Route,
    Stop,
    Tag,
    TrackContribution,
    Trip,
    TripNote,
    TripParticipant,
    TripTag,
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


def _link_new_person(f, actor):
    person = Person.objects.create(display_name="Me", created_by_id=uid(f, actor))
    return User.objects.filter(pk=uid(f, actor)).update(person=person) == 1


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


def _trips_api_actions():
    """What the trips API (work-order item 6) adds: legs and participants as rows of their
    own, people and vehicles referenced from a trip, and the trip's own purpose and cover."""
    fam = "family"
    return {
        "view_core_leg": (
            lambda f, a: sees(Leg, f.core_leg.pk),
            lambda f, u: policy.can_view_trip(u, f.trips[fam]),
        ),
        "view_bob_participation:participants": (
            lambda f, a: sees(TripParticipant, f.bob_participations["participants"]),
            lambda f, u: policy.can_view_trip(u, f.trips["participants"]),
        ),
        "delete_core_leg": (
            lambda f, a: deletes(Leg, f.core_leg.pk),
            lambda f, u: policy.can_delete_leg(u, f.core_leg),
        ),
        "add_carol:family": (
            lambda f, a: inserts(
                lambda: TripParticipant.objects.create(
                    trip=f.trips[fam], person=f.carol.person, added_by_id=uid(f, a)
                )
            ),
            lambda f, u: policy.can_add_participant(u, f.trips[fam], f.carol.person),
        ),
        # A private person someone else created: a guessed id must not put their name on a trip.
        "add_alices_private_person:family": (
            lambda f, a: inserts(
                lambda: TripParticipant.objects.create(
                    trip=f.trips[fam], person=f.alices_private_person, added_by_id=uid(f, a)
                )
            ),
            lambda f, u: policy.can_add_participant(u, f.trips[fam], f.alices_private_person),
        ),
        "remove_bob:family": (
            lambda f, a: deletes(TripParticipant, f.bob_participation_pk),
            lambda f, u: policy.can_remove_participant(u, f.trips[fam]),
        ),
        # Viewers are read-only, but their own public consent is a privacy choice (§6.3).
        "set_victor_consent": (
            lambda f, a: updates(TripParticipant, f.victor_participation_pk, public_consent=True),
            lambda f, u: policy.can_set_participant_consent(u, f.trips[fam], f.victor.person),
        ),
        "include_private_person_on_leg": (
            lambda f, a: inserts(
                lambda: LegParticipantOverride.objects.create(
                    leg=f.core_leg,
                    person=f.alices_private_person,
                    include=True,
                    set_by_id=uid(f, a),
                )
            ),
            lambda f, u: policy.can_set_leg_participation(u, f.core_leg, f.alices_private_person),
        ),
        "use_vehicle_on_core_leg": (
            lambda f, a: updates(Leg, f.core_leg.pk, vehicle=f.vehicle),
            lambda f, u: (
                policy.can_edit_leg(u, f.core_leg) and policy.can_use_vehicle(u, f.vehicle)
            ),
        ),
        "use_hidden_vehicle_on_core_leg": (
            lambda f, a: updates(Leg, f.core_leg.pk, vehicle=f.hidden_vehicle),
            lambda f, u: (
                policy.can_edit_leg(u, f.core_leg) and policy.can_use_vehicle(u, f.hidden_vehicle)
            ),
        ),
        "use_hidden_vehicle_on_bobs_leg": (
            lambda f, a: updates(Leg, f.bob_leg.pk, vehicle=f.hidden_vehicle),
            lambda f, u: (
                policy.can_edit_leg(u, f.bob_leg) and policy.can_use_vehicle(u, f.hidden_vehicle)
            ),
        ),
        "make_trip_private:family": (
            lambda f, a: updates(Trip, f.trips[fam].pk, visibility="private"),
            lambda f, u: policy.can_set_trip_visibility(u, f.trips[fam], "private"),
        ),
        "set_own_purpose:family": (
            lambda f, a: updates(Trip, f.trips[fam].pk, purpose=f.alice_purpose),
            lambda f, u: policy.can_set_trip_purpose(u, f.trips[fam], f.alice_purpose),
        ),
        "set_foreign_purpose:family": (
            lambda f, a: updates(Trip, f.trips[fam].pk, purpose=f.bob_purpose),
            lambda f, u: policy.can_set_trip_purpose(u, f.trips[fam], f.bob_purpose),
        ),
        # Covers are set by the photo work (T31); the database rule exists already.
        "set_cover_own_photo:family": (
            lambda f, a: updates(Trip, f.trips[fam].pk, cover_media=f.bob_photo),
            None,
        ),
        "set_cover_other_trips_photo:family": (
            lambda f, a: updates(Trip, f.trips[fam].pk, cover_media=f.alice_private_photo),
            None,
        ),
    }


def without_bob(f, probe):
    """Run probe after Alice removed Bob from the family trip (Q-16), in a savepoint that is
    always rolled back. Bob still sees the trip (family visibility) and his contributions."""

    def run():
        with as_owner():
            TripParticipant.objects.filter(pk=f.bob_participation_pk).delete()
        return probe()

    return _rolled_back(run)


def _new_place(f, a):
    return Place.objects.create(owner_id=uid(f, a), name="new", point=f.alice_point.geom)


def _reorder(f, leg_ids):
    with connection.cursor() as cursor:
        cursor.execute("SELECT app.reorder_legs(%s, %s::bigint[])", [f.trips["family"].pk, leg_ids])
    return True


def _contribution_actions():
    """What item 13 adds: contributions (notes, tracks, own tags, photos) follow the leg rule -
    their author changes them only while still able to contribute - and the trip owner may
    delete what someone who left the trip contributed (Q-16). Plus stops and leg order."""
    fam = "family"
    return {
        "edit_bobs_note_after_removal": (
            lambda f, a: without_bob(f, lambda: updates(TripNote, f.bob_note.pk, body="x")),
            lambda f, u: without_bob(f, lambda: policy.can_edit_contribution(u, f.bob_note)),
        ),
        "delete_bobs_note_after_removal": (
            lambda f, a: without_bob(f, lambda: deletes(TripNote, f.bob_note.pk)),
            lambda f, u: without_bob(f, lambda: policy.can_delete_contribution(u, f.bob_note)),
        ),
        "edit_bobs_track": (
            lambda f, a: updates(TrackContribution, f.bob_track.pk, public_consent=True),
            lambda f, u: policy.can_edit_contribution(u, f.bob_track),
        ),
        "delete_bobs_track": (
            lambda f, a: deletes(TrackContribution, f.bob_track.pk),
            lambda f, u: policy.can_delete_contribution(u, f.bob_track),
        ),
        "edit_bobs_track_after_removal": (
            lambda f, a: without_bob(
                f, lambda: updates(TrackContribution, f.bob_track.pk, public_consent=True)
            ),
            lambda f, u: without_bob(f, lambda: policy.can_edit_contribution(u, f.bob_track)),
        ),
        "delete_bobs_track_after_removal": (
            lambda f, a: without_bob(f, lambda: deletes(TrackContribution, f.bob_track.pk)),
            lambda f, u: without_bob(f, lambda: policy.can_delete_contribution(u, f.bob_track)),
        ),
        "edit_bobs_leg_after_removal": (
            lambda f, a: without_bob(f, lambda: updates(Leg, f.bob_leg.pk, mode="bus")),
            lambda f, u: without_bob(f, lambda: policy.can_edit_leg(u, f.bob_leg)),
        ),
        "delete_bobs_leg_after_removal": (
            lambda f, a: without_bob(f, lambda: deletes(Leg, f.bob_leg.pk)),
            lambda f, u: without_bob(f, lambda: policy.can_delete_leg(u, f.bob_leg)),
        ),
        "remove_bobs_tag": (
            lambda f, a: deletes(TripTag, f.bob_triptag.pk),
            lambda f, u: policy.can_delete_contribution(u, f.bob_triptag),
        ),
        "remove_bobs_tag_after_removal": (
            lambda f, a: without_bob(f, lambda: deletes(TripTag, f.bob_triptag.pk)),
            lambda f, u: without_bob(f, lambda: policy.can_delete_contribution(u, f.bob_triptag)),
        ),
        "edit_bobs_photo": (
            lambda f, a: updates(Media, f.bob_photo.pk, caption="x"),
            lambda f, u: policy.can_edit_contribution(u, f.bob_photo),
        ),
        "delete_bobs_photo_after_removal": (
            lambda f, a: without_bob(f, lambda: deletes(Media, f.bob_photo.pk)),
            lambda f, u: without_bob(f, lambda: policy.can_delete_contribution(u, f.bob_photo)),
        ),
        "add_track:family": (
            lambda f, a: inserts(
                lambda: TrackContribution.objects.create(
                    trip=f.trips[fam],
                    author_id=uid(f, a),
                    time_range=DateTimeTZRange(f.now - dt.timedelta(hours=1), f.now),
                )
            ),
            lambda f, u: policy.can_contribute(u, f.trips[fam]),
        ),
        "tag_family_trip_with_own_tag": (
            lambda f, a: inserts(
                lambda: TripTag.objects.create(
                    trip=f.trips[fam],
                    tag=Tag.objects.create(owner_id=uid(f, a), name="mine"),
                    author_id=uid(f, a),
                )
            ),
            lambda f, u: policy.can_create_tag(u) and policy.can_contribute(u, f.trips[fam]),
        ),
        "tag_family_trip_with_alices_tag": (
            lambda f, a: inserts(
                lambda: TripTag.objects.create(
                    trip=f.trips[fam], tag=f.alice_tag, author_id=uid(f, a)
                )
            ),
            lambda f, u: policy.can_tag_trip(u, f.trips[fam], f.alice_tag),
        ),
        "add_stop_at_new_place:family": (
            lambda f, a: inserts(
                lambda: Stop.objects.create(
                    trip=f.trips[fam], place=_new_place(f, a), kind="visit", author_id=uid(f, a)
                )
            ),
            lambda f, u: policy.can_create(u) and policy.can_edit_stops(u, f.trips[fam]),
        ),
        # A place of Alice's on no trip (it could be her home): only she may put it on a trip.
        "add_stop_at_alices_private_place:family": (
            lambda f, a: inserts(
                lambda: Stop.objects.create(
                    trip=f.trips[fam],
                    place=f.alice_private_place,
                    kind="visit",
                    author_id=uid(f, a),
                )
            ),
            lambda f, u: (
                policy.can_edit_stops(u, f.trips[fam])
                and policy.can_use_place(u, f.trips[fam], f.alice_private_place)
            ),
        ),
        "add_stop_at_the_trips_place:family": (
            lambda f, a: inserts(
                lambda: Stop.objects.create(
                    trip=f.trips[fam],
                    place_id=f.family_stop.place_id,
                    kind="visit",
                    author_id=uid(f, a),
                )
            ),
            lambda f, u: (
                policy.can_edit_stops(u, f.trips[fam])
                and policy.can_use_place(u, f.trips[fam], f.family_stop.place)
            ),
        ),
        "edit_family_stop": (
            lambda f, a: updates(Stop, f.family_stop.pk, kind="destination"),
            lambda f, u: policy.can_edit_stops(u, f.trips[fam]),
        ),
        "reorder_legs:family": (
            lambda f, a: _rolled_back(lambda: _reorder(f, [f.bob_leg.pk, f.core_leg.pk])),
            lambda f, u: policy.can_reorder_legs(u, f.trips[fam]),
        ),
    }


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
        lambda f, u: policy.can_save_route_version(u, f.core_leg),
    ),
    "save_route_version_on_bobs_leg": (
        lambda f, a: inserts(
            lambda: Route.objects.create(
                leg=f.bob_leg,
                version=1,
                geom=f.route.geom,
                kind="routed",
                produced_at=f.now,
                created_by_id=uid(f, a),
                length_m=1.0,
            )
        ),
        lambda f, u: policy.can_save_route_version(u, f.bob_leg),
    ),
    # Routing proposals (work-order item 25): a per-user cache of drawn waypoints.
    "propose_route": (
        lambda f, a: inserts(
            lambda: RouteRequestCache.objects.create(
                owner_id=uid(f, a),
                key="d" * 64,
                response={},
                created_at=f.now,
                expires_at=f.now,
            )
        ),
        lambda f, u: policy.can_propose_route(u),
    ),
    "view_alice_route_cache": (lambda f, a: sees(RouteRequestCache, f.alice_route_cache.pk), None),
    "delete_alice_route_cache": (
        lambda f, a: deletes(RouteRequestCache, f.alice_route_cache.pk),
        None,
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
    # Imported flights (work-order item 10) are raw history: own only.
    "view_alice_flight": (
        lambda f, a: sees(FlightRecord, f.alice_flight.pk),
        lambda f, u: policy.can_access_raw_history(u, f.alice.pk),
    ),
    "edit_alice_flight": (
        lambda f, a: updates(FlightRecord, f.alice_flight.pk, notes="changed"),
        lambda f, u: policy.can_access_raw_history(u, f.alice.pk),
    ),
    "delete_alice_flight": (
        lambda f, a: deletes(FlightRecord, f.alice_flight.pk),
        lambda f, u: policy.can_access_raw_history(u, f.alice.pk),
    ),
    "import_own_flight": (
        lambda f, a: inserts(
            lambda: FlightRecord.objects.create(
                owner_id=uid(f, a),
                row_key="n" * 64,
                content_hash="n" * 64,
                row_number=2,
                status=FlightRecord.Status.RESOLVED,
            )
        ),
        lambda f, u: policy.can_import(u),
    ),
    "view_alice_token": (
        lambda f, a: sees(DeviceToken, f.alice_token.pk),
        lambda f, u: policy.can_access_raw_history(u, f.alice.pk),
    ),
    # Device tokens and tracker ingestion (work-order item 7). Tracker requests act as the
    # token's owner, so "ingest with a token" is an insert in that user's context.
    "create_own_token": (
        lambda f, a: inserts(
            lambda: DeviceToken.objects.create(
                user_id=uid(f, a),
                name="new",
                kind="overland",
                token_prefix="trk_new",
                token_hash="c" * 64,
            )
        ),
        lambda f, u: policy.can_create_device_token(u),
    ),
    "revoke_alice_token": (
        lambda f, a: updates(DeviceToken, f.alice_token.pk, revoked_at=f.now),
        lambda f, u: policy.can_revoke_device_token(u, f.alice_token),
    ),
    "unrevoke_alice_token": (
        lambda f, a: updates(DeviceToken, f.alice_revoked_token.pk, revoked_at=None),
        None,
    ),
    "insert_own_point": (
        lambda f, a: inserts(
            lambda: LocationPoint.objects.create(
                owner_id=uid(f, a), ts=f.now, geom=f.alice_point.geom, source="gpx"
            )
        ),
        lambda f, u: policy.can_import(u),
    ),
    "ingest_with_alice_token": (
        lambda f, a: inserts(
            lambda: LocationPoint.objects.create(
                owner_id=uid(f, a),
                ts=f.now,
                geom=f.alice_point.geom,
                source="owntracks",
                device=f.alice_token,
            )
        ),
        lambda f, u: policy.can_ingest_points(u, f.alice_token),
    ),
    "ingest_with_alice_revoked_token": (
        lambda f, a: inserts(
            lambda: LocationPoint.objects.create(
                owner_id=uid(f, a),
                ts=f.now,
                geom=f.alice_point.geom,
                source="owntracks",
                device=f.alice_revoked_token,
            )
        ),
        lambda f, u: policy.can_ingest_points(u, f.alice_revoked_token),
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
    # Account privacy (D-72, D-76): the account row (email, OIDC subject, role) is for the
    # account itself and the Admin; the family reads names through the directory view.
    "view_alice_account": (
        lambda f, a: sees(User, f.alice.pk),
        lambda f, u: policy.can_view_account(u, f.alice),
    ),
    "view_ivan_account": (
        lambda f, a: sees(User, f.ivan.pk),
        lambda f, u: policy.can_view_account(u, f.ivan),
    ),
    "view_alice_name": (
        lambda f, a: sees(UserDirectory, f.alice.pk),
        lambda f, u: policy.can_view_directory(u),
    ),
    "view_ivan_name": (
        lambda f, a: sees(UserDirectory, f.ivan.pk),
        lambda f, u: policy.can_view_directory(u),
    ),
    "view_kid": (lambda f, a: sees(Person, f.kid.pk), None),
    "view_alices_private_person": (lambda f, a: sees(Person, f.alices_private_person.pk), None),
    # People (work-order item 20): adding a traveller, and making oneself one. Linking an
    # account to an existing person needs the Admin or that person's managing user.
    "create_person": (
        lambda f, a: inserts(
            lambda: Person.objects.create(display_name="New person", created_by_id=uid(f, a))
        ),
        lambda f, u: policy.can_create_person(u),
    ),
    "link_own_new_person": (lambda f, a: _rolled_back(lambda: _link_new_person(f, a)), None),
    "link_own_account_to_kid": (
        lambda f, a: updates(User, uid(f, a), person=f.kid.pk),
        None,
    ),
    **_trips_api_actions(),
    **_contribution_actions(),
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
    "save_route_version_on_bobs_leg": (F, F, T, F, F, F, F),
    "propose_route":               (T, T, T, T, F, F, F),
    "view_alice_route_cache":      (F, T, F, F, F, F, F),
    "delete_alice_route_cache":    (F, T, F, F, F, F, F),
    "set_own_leg_participation":   (T, T, T, F, F, F, F),
    "set_kid_leg_participation":   (T, T, F, F, F, F, F),
    "set_bob_consent":             (F, F, T, F, F, F, F),
    "set_kid_consent":             (T, F, F, F, F, F, F),
    "view_alice_points":           (F, T, F, F, F, F, F),
    "insert_point_for_alice":      (F, T, F, F, F, F, F),
    "view_alice_segment":          (F, T, F, F, F, F, F),
    "view_alice_rawfile":          (F, T, F, F, F, F, F),
    "view_alice_flight":           (F, T, F, F, F, F, F),
    "edit_alice_flight":           (F, T, F, F, F, F, F),
    "delete_alice_flight":         (F, T, F, F, F, F, F),
    "import_own_flight":           (T, T, T, T, F, F, F),
    "view_alice_token":            (F, T, F, F, F, F, F),
    "create_own_token":            (T, T, T, T, F, F, F),
    "revoke_alice_token":          (F, T, F, F, F, F, F),
    "unrevoke_alice_token":        (F, F, F, F, F, F, F),
    "insert_own_point":            (T, T, T, T, F, F, F),
    "ingest_with_alice_token":     (F, T, F, F, F, F, F),
    "ingest_with_alice_revoked_token": (F, F, F, F, F, F, F),
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
    "view_alice_account":          (T, T, F, F, F, F, F),
    "view_ivan_account":           (T, F, F, F, F, F, F),
    "view_alice_name":             (T, T, T, T, T, F, F),
    "view_ivan_name":              (T, T, T, T, T, F, F),
    "view_kid":                    (T, T, T, T, T, F, F),
    "view_alices_private_person":  (F, T, F, F, F, F, F),
    "create_person":               (T, T, T, T, F, F, F),
    "link_own_new_person":         (T, T, T, T, F, F, F),
    "link_own_account_to_kid":     (T, F, F, F, F, F, F),
    # Trips API (work-order item 6)
    "view_core_leg":                        (T, T, T, T, T, F, F),
    "view_bob_participation:participants":  (F, T, T, F, F, F, F),
    "delete_core_leg":                      (T, T, F, F, F, F, F),
    "add_carol:family":                     (T, T, F, F, F, F, F),
    "add_alices_private_person:family":     (F, T, F, F, F, F, F),
    "remove_bob:family":                    (T, T, F, F, F, F, F),
    "set_victor_consent":                   (F, F, F, F, T, F, F),
    "include_private_person_on_leg":        (F, T, F, F, F, F, F),
    "use_vehicle_on_core_leg":              (T, T, F, F, F, F, F),
    "use_hidden_vehicle_on_core_leg":       (F, T, F, F, F, F, F),
    "use_hidden_vehicle_on_bobs_leg":       (F, F, F, F, F, F, F),
    "make_trip_private:family":             (F, T, F, F, F, F, F),
    "set_own_purpose:family":               (T, T, F, F, F, F, F),
    "set_foreign_purpose:family":           (F, F, F, F, F, F, F),
    "set_cover_own_photo:family":           (T, T, F, F, F, F, F),
    "set_cover_other_trips_photo:family":   (F, F, F, F, F, F, F),
    # Rest of the trips API (work-order item 13): contributions, Q-16, stops, leg order
    "edit_bobs_note_after_removal":             (F, F, F, F, F, F, F),
    "delete_bobs_note_after_removal":           (F, T, F, F, F, F, F),
    "edit_bobs_track":                          (F, F, T, F, F, F, F),
    "delete_bobs_track":                        (F, F, T, F, F, F, F),
    "edit_bobs_track_after_removal":            (F, F, F, F, F, F, F),
    "delete_bobs_track_after_removal":          (F, T, F, F, F, F, F),
    "edit_bobs_leg_after_removal":              (F, F, F, F, F, F, F),
    "delete_bobs_leg_after_removal":            (F, T, F, F, F, F, F),
    "remove_bobs_tag":                          (F, F, T, F, F, F, F),
    "remove_bobs_tag_after_removal":            (F, T, F, F, F, F, F),
    "edit_bobs_photo":                          (F, F, T, F, F, F, F),
    "delete_bobs_photo_after_removal":          (F, T, F, F, F, F, F),
    "add_track:family":                         (F, T, T, F, F, F, F),
    "tag_family_trip_with_own_tag":             (F, T, T, F, F, F, F),
    "tag_family_trip_with_alices_tag":          (F, T, F, F, F, F, F),
    "add_stop_at_new_place:family":             (T, T, F, F, F, F, F),
    "add_stop_at_alices_private_place:family":  (F, T, F, F, F, F, F),
    "add_stop_at_the_trips_place:family":       (T, T, F, F, F, F, F),
    "edit_family_stop":                         (T, T, F, F, F, F, F),
    "reorder_legs:family":                      (T, T, F, F, F, F, F),
}  # fmt: skip

CASES = [
    pytest.param(action, actor, expected, id=f"{action}-{actor}")
    for action, row in MATRIX.items()
    for actor, expected in zip(ACTORS, row, strict=True)
]


def test_every_action_has_a_matrix_row():
    assert set(ACTIONS) == set(MATRIX)


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
            # As the owner: a deactivated account cannot read its own row (D-53), and the
            # policy layer must still refuse a stale object for it.
            with as_owner():
                user.refresh_from_db()
        assert bool(policy_probe(f, user)) is expected, f"policy layer: {action} by {actor_name}"
