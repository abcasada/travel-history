"""A small synthetic family used by the permission-matrix tests (PLAN.md §6.3).

admin   Admin; manages `kid` (a person without an account)
alice   Member; owns one trip per visibility, vehicles, raw history, home periods
bob     Member; participant on all of alice's trips; adds contributions
carol   Member; family, not a participant anywhere
victor  Viewer; participant on alice's family trip (viewers still cannot contribute)
ivan    Member, deactivated
"""

import copy
import datetime as dt
import sys
from types import SimpleNamespace

import pytest
from django.db import connection, transaction
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
from travel.accounts.models import AccessRequest, DeviceToken, Person, Role, User
from travel.history.models import HomePeriod, LocationPoint, RawFile, TimelineSegment
from travel.media.models import Media
from travel.trips.models import (
    Leg,
    LegParticipantOverride,
    Purpose,
    Route,
    Tag,
    Trip,
    TripNote,
    TripParticipant,
    TripTag,
)
from travel.vehicles.models import Vehicle, VehicleOwnership, VehiclePrivate


@pytest.fixture
def family(db):
    return build_family()


def build_family() -> SimpleNamespace:
    """Create the synthetic family as the owner role. Callers provide the transaction."""
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
        f.alice_private_photo = Media.objects.create(
            trip=f.trips["private"], author=f.alice, display_path="x/alice.webp"
        )
        f.alice_purpose = Purpose.objects.create(owner=f.alice, name="Vacation")
        f.bob_purpose = Purpose.objects.create(owner=f.bob, name="Bob's own purpose")
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


# --- One family per test module (T46) ------------------------------------------------------


def _add_scenario_details(family):
    with as_owner():
        fam = family.trips["family"]
        family.kid_participation_pk = TripParticipant.objects.get(trip=fam, person=family.kid).pk
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
            trip=fam, person=family.bob.person
        ).pk
        family.victor_participation_pk = TripParticipant.objects.get(
            trip=fam, person=family.victor.person
        ).pk
        family.bob_participations = {
            vis: TripParticipant.objects.get(trip=trip, person=family.bob.person).pk
            for vis, trip in family.trips.items()
        }
    return family


def _row_counts():
    tables = (
        Trip, TripParticipant, TripNote, Leg, LegParticipantOverride, Route, LocationPoint,
        TimelineSegment, RawFile, HomePeriod, Vehicle, VehiclePrivate, Person, User,
        DeviceToken, AccessRequest, Purpose, Media, TripTag,
    )  # fmt: skip
    # One round trip per case: SELECT (SELECT count(*) FROM a), (SELECT count(*) FROM b), ...
    # Table names come from model metadata, never from input.
    names = [connection.ops.quote_name(m._meta.db_table) for m in tables]
    sql = "SELECT " + ", ".join(f"(SELECT count(*) FROM {name})" for name in names)  # noqa: S608
    with as_owner(), connection.cursor() as cursor:
        cursor.execute(sql)
        return dict(zip((m.__name__ for m in tables), cursor.fetchone(), strict=True))


@pytest.fixture(scope="module")
def shared_scenario(django_db_setup, django_db_blocker):
    """Build the family once per module instead of once per case (T46).

    The rows live in an outer transaction that is rolled back after the module. Each case still
    runs in its own savepoint (pytest-django's `db` fixture), which is rolled back after the case,
    so nothing one case writes is visible to the next: the same isolation as a fresh fixture.
    """
    with django_db_blocker.unblock():
        outer = transaction.atomic()
        outer.__enter__()
        try:
            family = _add_scenario_details(build_family())
            family.row_counts = _row_counts()
        except BaseException:
            outer.__exit__(*sys.exc_info())
            raise
    yield family
    with django_db_blocker.unblock():
        transaction.set_rollback(True)
        outer.__exit__(None, None, None)


@pytest.fixture
def scenario(shared_scenario, db):
    # Every case must start from exactly the rows the family was built with.
    assert _row_counts() == shared_scenario.row_counts, "a previous case leaked rows"
    # A private copy, so a case can't leak Python-side state (cached relations, refreshed
    # fields) into later cases either.
    return copy.deepcopy(shared_scenario)
