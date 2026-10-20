"""A small synthetic family used by the permission-matrix tests (PLAN.md §6.3).

admin   Admin; manages `kid` (a person without an account)
alice   Member; owns one trip per visibility, vehicles, raw history, home periods
bob     Member; participant on all of alice's trips; adds contributions
carol   Member; family, not a participant anywhere
victor  Viewer; participant on alice's family trip (viewers still cannot contribute)
ivan    Member, deactivated
"""

import datetime as dt
from types import SimpleNamespace

import pytest
from django.utils import timezone

from tests.factories import (
    LegFactory,
    LocationPointFactory,
    ParticipantFactory,
    PersonFactory,
    RawFileFactory,
    RouteFactory,
    TimelineSegmentFactory,
    TripFactory,
    user_with_person,
)
from tests.helpers import as_owner
from travel.accounts.models import AccessRequest, DeviceToken, Person, Role
from travel.history.models import HomePeriod
from travel.media.models import Media
from travel.trips.models import Leg, LegParticipantOverride, Tag, TripNote, TripTag
from travel.vehicles.models import Vehicle, VehicleOwnership, VehiclePrivate


@pytest.fixture
def family(db):
    with as_owner():
        f = SimpleNamespace()
        f.admin = user_with_person(role=Role.ADMIN, display_name="Admin")
        f.alice = user_with_person(display_name="Alice")
        f.bob = user_with_person(display_name="Bob")
        f.carol = user_with_person(display_name="Carol")
        f.victor = user_with_person(role=Role.VIEWER, display_name="Victor")
        f.ivan = user_with_person(display_name="Ivan", is_active=False)
        f.anon = None
        f.kid = PersonFactory(created_by=f.admin, display_name="Kid")
        f.alices_private_person = PersonFactory(
            created_by=f.alice,
            display_name="Alice's coworker",
            visibility=Person.Visibility.PRIVATE,
        )

        f.trips = {}
        for vis in ("private", "participants", "family", "public"):
            trip = TripFactory(
                owner=f.alice, visibility=vis, public_mode="unlisted" if vis == "public" else ""
            )
            ParticipantFactory(trip=trip, person=f.bob.person, added_by=f.alice)
            f.trips[vis] = trip
        fam = f.trips["family"]
        ParticipantFactory(trip=fam, person=f.victor.person, added_by=f.alice)
        ParticipantFactory(trip=fam, person=f.kid, added_by=f.alice)
        ParticipantFactory(trip=fam, person=f.ivan.person, added_by=f.alice)
        f.admin_private_trip = TripFactory(owner=f.admin, visibility="private")

        f.core_leg = LegFactory(trip=fam, author=f.alice, sequence=1)
        f.route = RouteFactory(leg=f.core_leg, created_by=f.alice)
        f.bob_leg = LegFactory(
            trip=fam,
            author=f.bob,
            sequence=2,
            is_contribution=True,
            participant_scope=Leg.ParticipantScope.AUTHOR,
        )
        f.bob_note = TripNote.objects.create(trip=fam, author=f.bob, body="Bob's note")
        f.alice_note = TripNote.objects.create(trip=fam, author=f.alice, body="Alice's note")
        f.bob_photo = Media.objects.create(trip=fam, author=f.bob, display_path="x/bob.webp")
        f.bob_tag = Tag.objects.create(owner=f.bob, name="bob-tag")
        f.alice_tag = Tag.objects.create(owner=f.alice, name="alice-tag")
        f.bob_triptag = TripTag.objects.create(trip=fam, tag=f.bob_tag, author=f.bob)

        f.vehicle = Vehicle.objects.create(nickname="Alice's car", created_by=f.alice)
        VehicleOwnership.objects.create(
            vehicle=f.vehicle, owner_person=f.alice.person, created_by=f.alice
        )
        VehiclePrivate.objects.create(vehicle=f.vehicle, plate="SYN1234", plate_last4="1234")
        f.hidden_vehicle = Vehicle.objects.create(
            nickname="Hidden", created_by=f.alice, hidden=True
        )
        VehicleOwnership.objects.create(
            vehicle=f.hidden_vehicle, owner_person=f.alice.person, created_by=f.alice
        )
        f.kid_vehicle = Vehicle.objects.create(nickname="Kid's bike", created_by=f.admin)
        VehicleOwnership.objects.create(
            vehicle=f.kid_vehicle, owner_person=f.kid, created_by=f.admin
        )
        # Entered by carol but owned by alice (who has an account) -> alice manages it.
        f.carol_entered_vehicle = Vehicle.objects.create(
            nickname="Entered by Carol", created_by=f.carol
        )
        VehicleOwnership.objects.create(
            vehicle=f.carol_entered_vehicle,
            owner_person=f.alice.person,
            created_by=f.carol,
            valid_from=dt.date(2000, 1, 1),
        )

        f.alice_point = LocationPointFactory(owner=f.alice)
        f.bob_point = LocationPointFactory(owner=f.bob)
        f.alice_segment = TimelineSegmentFactory(owner=f.alice)
        f.alice_raw = RawFileFactory(owner=f.alice)
        f.alice_home = HomePeriod.objects.create(
            person=f.alice.person, managed_by=f.alice, address="1 Synthetic St"
        )
        f.alice_shared_home = HomePeriod.objects.create(
            person=f.alice.person,
            managed_by=f.alice,
            address="2 Synthetic St",
            shared_with_family=True,
        )
        f.alice_token = DeviceToken.objects.create(
            user=f.alice,
            name="phone",
            kind="owntracks",
            token_prefix="trk_abc",
            token_hash="a" * 64,
        )
        f.request = AccessRequest.objects.create(
            name="Synthetic Cousin", email="cousin@example.test", relationship="cousin"
        )
        f.override_bob_core = LegParticipantOverride(
            leg=f.core_leg, person=f.bob.person, include=False, set_by=f.bob
        )
        f.now = timezone.now()
    return f
