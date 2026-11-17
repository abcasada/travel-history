"""Database rules behind the trips API (trips migration 0003, D-81), checked as `travel_app`
under each actor's RLS context. The permission matrix covers the main cases; these cover the
edges: references that must stay inside their trip, a hidden vehicle that is already on a leg,
and a contributor who is no longer a participant. Item 13 (trips migration 0004) adds stops'
places, photo references, the leg-order function and Q-16."""

import pytest
from django.contrib.gis.geos import Point
from django.db import DatabaseError, connection, transaction

from tests.factories import RouteFactory
from tests.helpers import as_owner
from travel.core import policy
from travel.core.rls import set_context
from travel.media.models import Media
from travel.trips.models import (
    Leg,
    LegParticipantOverride,
    Place,
    Stop,
    TrackContribution,
    Trip,
    TripNote,
    TripParticipant,
    TripTag,
)

pytestmark = pytest.mark.django_db


def refused(fn) -> bool:
    try:
        with transaction.atomic():
            fn()
    except DatabaseError:
        return True
    return False


@pytest.fixture
def private_stop(scenario):
    """A stop on Alice's private trip (another trip than the family trip's legs)."""
    f = scenario
    with as_owner():
        place = Place.objects.create(owner=f.alice, name="Synthetic place", point=Point(0, 0))
        return Stop.objects.create(
            trip=f.trips["private"], place=place, kind="lodging", author=f.alice
        )


def test_new_trip_takes_only_the_owners_purpose(scenario):
    f = scenario
    set_context(f.bob.pk)

    def create(purpose):
        Trip.objects.create(
            owner=f.bob,
            title="t",
            start_date="2020-01-01",
            end_date="2020-01-02",
            purpose=purpose,
        )

    assert refused(lambda: create(f.alice_purpose))
    assert not refused(lambda: create(f.bob_purpose))


def test_owner_role_obeys_the_reference_rules_too(scenario):
    """Purpose and cover are integrity rules, not permissions: no role is exempt."""
    f = scenario
    with as_owner():
        assert refused(
            lambda: Trip.objects.filter(pk=f.trips["family"].pk).update(purpose=f.bob_purpose)
        )
        assert refused(
            lambda: Trip.objects.filter(pk=f.trips["family"].pk).update(
                cover_media=f.alice_private_photo
            )
        )


def test_leg_stops_must_belong_to_the_legs_trip(scenario, private_stop):
    f = scenario
    set_context(f.alice.pk)
    for field in ("origin_stop", "destination_stop"):
        assert refused(
            lambda fd=field: Leg.objects.filter(pk=f.core_leg.pk).update(**{fd: private_stop})
        )
    with as_owner():
        own = Stop.objects.create(
            trip=f.trips["family"], place=private_stop.place, kind="visit", author=f.alice
        )
    assert Leg.objects.filter(pk=f.core_leg.pk).update(origin_stop=own) == 1


def test_current_route_must_be_one_of_the_legs_versions(scenario):
    f = scenario
    with as_owner():
        other = RouteFactory(leg=f.bob_leg, created_by=f.bob)
    set_context(f.alice.pk)
    assert refused(lambda: Leg.objects.filter(pk=f.core_leg.pk).update(current_route=other))
    assert Leg.objects.filter(pk=f.core_leg.pk).update(current_route=f.route) == 1


def test_a_hidden_vehicle_already_on_a_leg_does_not_block_other_edits(scenario):
    """Alice put her hidden car on the core leg; the Admin (who cannot see that car) can still
    edit the leg, but cannot put the car on another leg."""
    f = scenario
    with as_owner():
        Leg.objects.filter(pk=f.core_leg.pk).update(vehicle=f.hidden_vehicle)
    set_context(f.admin.pk)
    leg = Leg.objects.get(pk=f.core_leg.pk)
    leg.origin_label = "edited by the Admin"
    leg.save()  # saves every column, vehicle_id included (unchanged)
    assert refused(
        lambda: Leg.objects.create(
            trip=f.trips["family"],
            sequence=50,
            mode="drive",
            author=f.admin,
            vehicle=f.hidden_vehicle,
        )
    )


def test_owner_role_may_set_any_vehicle(scenario):
    f = scenario
    with as_owner():
        assert Leg.objects.filter(pk=f.bob_leg.pk).update(vehicle=f.hidden_vehicle) == 1


def test_removed_participant_can_no_longer_edit_or_delete_their_leg(scenario):
    """Bob contributed a leg, then Alice removed him. The family trip is still visible to him,
    but deleting his leg now needs the same right as editing it (§6.3: 'Member - other')."""
    f = scenario
    with as_owner():
        TripParticipant.objects.filter(pk=f.bob_participation_pk).delete()
    set_context(f.bob.pk)
    assert Leg.objects.filter(pk=f.bob_leg.pk).exists()
    assert Leg.objects.filter(pk=f.bob_leg.pk).update(mode="bus") == 0
    assert Leg.objects.filter(pk=f.bob_leg.pk)._raw_delete("default") == 0
    with as_owner():
        f.bob.refresh_from_db()
        leg = Leg.objects.select_related("trip").get(pk=f.bob_leg.pk)
    assert not policy.can_delete_leg(f.bob, leg)


def test_contributor_still_deletes_own_leg_while_participating(scenario):
    f = scenario
    set_context(f.bob.pk)
    assert Leg.objects.filter(pk=f.bob_leg.pk)._raw_delete("default") == 1


# --- Work-order item 13 (trips migration 0004, D-89) ------------------------------------------


def sql(query: str, params=()):
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchone()[0]


def test_a_stops_place_is_the_editors_own_or_already_on_the_trip(scenario):
    """A guessed place id (a place can be a home address) must not land on a trip others read."""
    f = scenario
    set_context(f.admin.pk)

    def add(place_id):
        Stop.objects.create(trip=f.trips["family"], place_id=place_id, kind="visit", author=f.admin)

    assert refused(lambda: add(f.alice_private_place.pk))
    assert not refused(lambda: add(f.family_stop.place_id))
    own = Place.objects.create(owner=f.admin, name="Admin's", point=Point(0, 0))
    assert not refused(lambda: add(own.pk))
    # Moving an existing stop to the hidden place is refused too; other edits are not.
    assert refused(
        lambda: Stop.objects.filter(pk=f.family_stop.pk).update(place=f.alice_private_place)
    )
    assert Stop.objects.filter(pk=f.family_stop.pk).update(kind="destination") == 1
    with as_owner():  # imports and the owner role are exempt
        assert Stop.objects.filter(pk=f.family_stop.pk).update(place=f.alice_private_place) == 1


def test_stop_and_photo_references_stay_inside_their_trip(scenario):
    f = scenario
    with as_owner():
        other_leg = Leg.objects.create(
            trip=f.trips["public"], sequence=1, mode="drive", author=f.alice
        )
        other_stop = Stop.objects.create(
            trip=f.trips["public"], place=f.alice_private_place, kind="visit", author=f.alice
        )
    set_context(f.alice.pk)
    assert refused(lambda: Stop.objects.filter(pk=f.family_stop.pk).update(leg=other_leg))
    assert Stop.objects.filter(pk=f.family_stop.pk).update(leg=f.core_leg) == 1
    set_context(f.bob.pk)
    assert refused(lambda: Media.objects.filter(pk=f.bob_photo.pk).update(leg=other_leg))
    assert refused(lambda: Media.objects.filter(pk=f.bob_photo.pk).update(stop=other_stop))
    assert Media.objects.filter(pk=f.bob_photo.pk).update(stop=f.family_stop) == 1
    with as_owner():  # an integrity rule: no role is exempt
        assert refused(lambda: Media.objects.filter(pk=f.bob_photo.pk).update(leg=other_leg))
        assert refused(lambda: Stop.objects.filter(pk=f.family_stop.pk).update(leg=other_leg))


def test_an_author_cannot_move_a_photo_to_a_trip_they_cannot_contribute_to(scenario):
    f = scenario
    set_context(f.bob.pk)
    assert refused(
        lambda: Media.objects.filter(pk=f.bob_photo.pk).update(trip=f.admin_private_trip)
    )
    assert Media.objects.filter(pk=f.bob_photo.pk).update(trip=f.trips["public"]) == 1


def test_reorder_legs_function(scenario):
    f = scenario
    fam = f.trips["family"].pk
    order = [f.bob_leg.pk, f.core_leg.pk]
    for actor in (f.bob, f.carol, f.victor, None):
        set_context(actor.pk if actor else None)
        assert refused(lambda: sql("SELECT app.reorder_legs(%s, %s::bigint[])", [fam, order]))
    set_context(f.alice.pk)
    for wrong in ([f.core_leg.pk], [f.core_leg.pk, f.core_leg.pk], [*order, 999_999]):
        assert refused(lambda w=wrong: sql("SELECT app.reorder_legs(%s, %s::bigint[])", [fam, w]))
    with as_owner():
        before = {g.pk: g for g in Leg.objects.filter(trip_id=fam)}
    sql("SELECT app.reorder_legs(%s, %s::bigint[])", [fam, order])
    with as_owner():
        after = {g.pk: g for g in Leg.objects.filter(trip_id=fam)}
    assert [after[pk].sequence for pk in order] == [1, 2]
    for pk, leg in after.items():
        assert (leg.author_id, leg.is_contribution, leg.mode) == (
            before[pk].author_id,
            before[pk].is_contribution,
            before[pk].mode,
        )


def test_new_helpers_answer_nothing_about_trips_the_caller_cannot_see(scenario):
    f = scenario
    private = f.trips["private"].pk
    set_context(f.carol.pk)
    assert sql("SELECT app.is_person_on_trip(%s, %s)", [private, f.bob.person_id]) is False
    assert sql("SELECT app.can_use_place(%s, %s)", [f.alice_private_place.pk, private]) is False
    set_context(f.alice.pk)
    assert sql("SELECT app.is_person_on_trip(%s, %s)", [private, f.bob.person_id]) is True
    set_context(None)
    assert sql("SELECT app.user_person(%s)", [f.bob.pk]) is None
    set_context(f.ivan.pk)
    assert sql("SELECT app.user_person(%s)", [f.bob.pk]) is None


def test_owner_deletes_a_removed_participants_contributions_as_travel_app(scenario):
    """Q-16, at the database level: once Bob is off the trip, Alice may delete his rows; while
    he is on it (or on one of its legs), she may not."""
    f = scenario
    set_context(f.alice.pk)
    assert TripNote.objects.filter(pk=f.bob_note.pk)._raw_delete("default") == 0
    with as_owner():
        TripParticipant.objects.filter(pk=f.bob_participation_pk).delete()
        LegParticipantOverride.objects.create(
            leg=f.core_leg, person=f.bob.person, include=True, set_by=f.alice
        )
    assert TripNote.objects.filter(pk=f.bob_note.pk)._raw_delete("default") == 0
    with as_owner():
        LegParticipantOverride.objects.filter(leg=f.core_leg, person=f.bob.person).delete()
    for model, pk in (
        (TripNote, f.bob_note.pk),
        (TrackContribution, f.bob_track.pk),
        (TripTag, f.bob_triptag.pk),
        (Media, f.bob_photo.pk),
        (Leg, f.bob_leg.pk),
    ):
        assert model.objects.filter(pk=pk)._raw_delete("default") == 1, model.__name__


def test_an_author_without_a_person_counts_as_off_the_trip(scenario):
    """An account not linked to a person can't be a participant; its contributions on someone
    else's trip are the owner's to delete."""
    f = scenario
    with as_owner():
        f.carol.person = None
        f.carol.save(update_fields=["person"])
        note = TripNote.objects.create(trip=f.trips["family"], author=f.carol, body="n")
    set_context(f.alice.pk)
    assert TripNote.objects.filter(pk=note.pk)._raw_delete("default") == 1
