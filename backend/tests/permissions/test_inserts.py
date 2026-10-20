"""INSERT ... RETURNING (every ORM create) needs the new row to pass SELECT policies in the same
statement; SELECT policies therefore check the row's own columns first."""

import datetime as dt

import pytest
from django.contrib.gis.geos import Point

from travel.accounts.models import Person
from travel.core.rls import set_context
from travel.trips.models import Place, Purpose, Tag, Trip
from travel.vehicles.models import Vehicle, VehicleOwnership

pytestmark = pytest.mark.django_db


def test_member_creates_own_rows(family):
    alice = family.alice
    set_context(alice.pk)
    Person.objects.create(display_name="New friend", created_by=alice)
    Person.objects.create(display_name="Private", created_by=alice, visibility="private")
    Purpose.objects.create(owner=alice, name="Conference")
    Place.objects.create(owner=alice, name="Somewhere", point=Point(-97.3, 37.7, srid=4326))
    Tag.objects.create(owner=alice, name="new-tag")
    Trip.objects.create(
        owner=alice,
        title="t",
        start_date=dt.date(2021, 1, 1),
        end_date=dt.date(2021, 1, 2),
        visibility="private",
    )
    vehicle = Vehicle.objects.create(nickname="rental", created_by=alice, is_rental=True)
    VehicleOwnership.objects.create(
        vehicle=vehicle,
        outside_owner_name="Rental Co",
        outside_owner_kind="rental",
        created_by=alice,
    )
