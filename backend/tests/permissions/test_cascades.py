"""Deletes cascade inside PostgreSQL (DB_CASCADE / DB_SET_NULL), so an owner deleting a trip also
removes other people's contributions on it, while nobody can delete those contributions
directly (PLAN.md §6.3)."""

import pytest

from tests.helpers import as_owner
from travel.core.rls import set_context
from travel.media.models import Media
from travel.trips.models import Leg, Route, Trip, TripNote

pytestmark = pytest.mark.django_db


def test_owner_deletes_trip_including_others_contributions(family):
    trip = family.trips["family"]
    set_context(family.alice.pk)
    Trip.objects.filter(pk=trip.pk).delete()
    with as_owner():
        assert not Trip.objects.filter(pk=trip.pk).exists()
        assert not TripNote.objects.filter(pk=family.bob_note.pk).exists()
        assert not Media.objects.filter(pk=family.bob_photo.pk).exists()
        assert not Leg.objects.filter(pk=family.bob_leg.pk).exists()
        assert not Route.objects.filter(pk=family.route.pk).exists()


def test_owner_deletes_core_leg_without_touching_others_photos(family):
    with as_owner():
        Media.objects.filter(pk=family.bob_photo.pk).update(leg=family.core_leg)
    set_context(family.alice.pk)
    Leg.objects.filter(pk=family.core_leg.pk).delete()
    with as_owner():
        photo = Media.objects.get(pk=family.bob_photo.pk)
        assert photo.leg_id is None  # unlinked by the database, still Bob's
        assert photo.author_id == family.bob.pk


def test_participant_cannot_delete_the_trip(family):
    set_context(family.bob.pk)
    deleted, _ = Trip.objects.filter(pk=family.trips["family"].pk).delete()
    assert deleted == 0
