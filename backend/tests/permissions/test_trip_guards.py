"""Database rules behind the trips API (trips migration 0003, D-81), checked as `travel_app`
under each actor's RLS context. The permission matrix covers the main cases; these cover the
edges: references that must stay inside their trip, a hidden vehicle that is already on a leg,
and a contributor who is no longer a participant."""

import pytest
from django.contrib.gis.geos import Point
from django.db import DatabaseError, transaction

from tests.factories import RouteFactory
from tests.helpers import as_owner
from travel.core import policy
from travel.core.rls import set_context
from travel.trips.models import Leg, Place, Stop, Trip, TripParticipant

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
