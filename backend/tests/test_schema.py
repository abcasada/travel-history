"""Milestone 1.2: database-level guarantees from PLAN.md §5. These test constraints and
triggers directly, as the owner role (row-level security is covered in tests/permissions)."""

import datetime as dt

import pytest
from django.contrib.gis.geos import LineString, MultiLineString
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from tests.factories import (
    DENVER,
    TOPEKA,
    LegFactory,
    LocationPointFactory,
    PersonFactory,
    RawFileFactory,
    RouteFactory,
    TimelineSegmentFactory,
    TripFactory,
    UserFactory,
    VehicleFactory,
)
from travel.history.models import LocationPoint, PointSource, RawFile, TimelineSegment
from travel.media.models import Media
from travel.trips.models import Leg, Route, Trip
from travel.vehicles.models import Vehicle, VehicleOwnership

pytestmark = [pytest.mark.django_db, pytest.mark.as_owner]


def check_deferred():
    """Fire deferred constraint triggers now instead of at commit (tests never commit)."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


# --- Frozen routes -------------------------------------------------------------------------


def test_route_versions_cannot_be_updated():
    route = RouteFactory()
    route.geom = MultiLineString(LineString(TOPEKA, DENVER, srid=4326), srid=4326)
    with pytest.raises(IntegrityError, match="immutable"), transaction.atomic():
        route.save()


def test_route_update_is_rejected_even_for_metadata():
    route = RouteFactory()
    with pytest.raises(IntegrityError, match="immutable"), transaction.atomic():
        Route.objects.filter(pk=route.pk).update(note="changed")


def test_new_route_version_and_current_pointer():
    v1 = RouteFactory()
    v2 = RouteFactory(leg=v1.leg, version=2, kind=Route.Kind.HAND_EDITED)
    Leg.objects.filter(pk=v1.leg_id).update(current_route=v2)
    assert Leg.objects.get(pk=v1.leg_id).current_route_id == v2.pk
    with pytest.raises(IntegrityError), transaction.atomic():
        RouteFactory(leg=v1.leg, version=2)


# --- Raw data is append-only ----------------------------------------------------------------


def test_raw_files_are_immutable():
    raw = RawFileFactory()
    with pytest.raises(IntegrityError, match="immutable"), transaction.atomic():
        RawFile.objects.filter(pk=raw.pk).update(original_name="renamed.json")


def test_location_points_are_append_only():
    point = LocationPointFactory()
    with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
        LocationPoint.objects.filter(pk=point.pk).update(accuracy_m=5)


def test_duplicate_points_are_rejected_even_without_device():
    point = LocationPointFactory(source=PointSource.GOOGLE_RAW)
    with pytest.raises(IntegrityError), transaction.atomic():
        LocationPointFactory(owner=point.owner, ts=point.ts, source=PointSource.GOOGLE_RAW)


def test_segment_versions_only_allow_pointer_changes():
    old = TimelineSegmentFactory()
    new = TimelineSegmentFactory(
        owner=old.owner, lineage_id=old.lineage_id, version=2, is_current=False
    )
    # Allowed: flip the current-version pointer.
    TimelineSegment.objects.filter(pk=old.pk).update(is_current=False, superseded_by=new)
    TimelineSegment.objects.filter(pk=new.pk).update(is_current=True)
    # Not allowed: rewriting history.
    with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
        TimelineSegment.objects.filter(pk=old.pk).update(place_id="ChIJchanged")


def test_only_one_current_version_per_lineage():
    seg = TimelineSegmentFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        TimelineSegmentFactory(owner=seg.owner, lineage_id=seg.lineage_id, version=2)


# --- Trips and legs --------------------------------------------------------------------------


def test_trip_end_cannot_precede_start():
    with pytest.raises(IntegrityError), transaction.atomic():
        TripFactory(start_date=dt.date(2024, 5, 4), end_date=dt.date(2024, 5, 1))


def test_public_mode_required_exactly_when_public():
    with pytest.raises(IntegrityError), transaction.atomic():
        TripFactory(visibility="public", public_mode="")
    with pytest.raises(IntegrityError), transaction.atomic():
        TripFactory(visibility="family", public_mode="listed")
    TripFactory(visibility="public", public_mode="unlisted")


def test_leg_sequences_can_be_swapped_within_a_transaction():
    trip = TripFactory()
    a = LegFactory(trip=trip, sequence=1)
    b = LegFactory(trip=trip, sequence=2)
    with transaction.atomic():
        Leg.objects.filter(pk=a.pk).update(sequence=2)
        Leg.objects.filter(pk=b.pk).update(sequence=1)
    check_deferred()
    assert list(trip.legs.order_by("sequence").values_list("pk", flat=True)) == [b.pk, a.pk]


def test_public_slugs_are_unguessable_and_unique():
    slugs = {TripFactory().public_slug for _ in range(20)}
    assert len(slugs) == 20
    assert all(len(s) == 22 for s in slugs)


# --- Vehicles: exactly one owner at any time ------------------------------------------------


def test_vehicle_requires_an_owner():
    user = UserFactory()
    Vehicle.objects.create(nickname="orphan", created_by=user)
    with pytest.raises(IntegrityError, match="no owner"):
        check_deferred()


def test_ownership_periods_cannot_overlap():
    vehicle = VehicleFactory()
    first = vehicle.ownerships.get()
    VehicleOwnership.objects.filter(pk=first.pk).update(valid_to=dt.date(2020, 1, 1))
    with pytest.raises(IntegrityError), transaction.atomic():
        VehicleOwnership.objects.create(
            vehicle=vehicle,
            owner_person=PersonFactory(),
            created_by=vehicle.created_by,
            valid_from=dt.date(2019, 6, 1),
        )


def test_ownership_history_cannot_have_gaps():
    vehicle = VehicleFactory()
    VehicleOwnership.objects.filter(vehicle=vehicle).update(valid_to=dt.date(2020, 1, 1))
    VehicleOwnership.objects.create(
        vehicle=vehicle,
        outside_owner_name="Dealer",
        outside_owner_kind="dealer",
        created_by=vehicle.created_by,
        valid_from=dt.date(2020, 3, 1),
    )
    with pytest.raises(IntegrityError, match="gap"):
        check_deferred()


def test_contiguous_ownership_transfer_is_valid():
    vehicle = VehicleFactory()
    VehicleOwnership.objects.filter(vehicle=vehicle).update(valid_to=dt.date(2020, 1, 1))
    VehicleOwnership.objects.create(
        vehicle=vehicle,
        outside_owner_name="Rental Co",
        outside_owner_kind="rental",
        created_by=vehicle.created_by,
        valid_from=dt.date(2020, 1, 1),
    )
    check_deferred()
    assert vehicle.ownerships.count() == 2


def test_ownership_needs_exactly_one_kind_of_owner():
    vehicle = VehicleFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        VehicleOwnership.objects.create(
            vehicle=vehicle,
            owner_person=PersonFactory(),
            outside_owner_name="Also a dealer",
            created_by=vehicle.created_by,
            valid_from=dt.date(2030, 1, 1),
        )


def test_deleting_a_vehicle_with_history_is_allowed():
    vehicle = VehicleFactory()
    vehicle.delete()
    check_deferred()


# --- Photos ---------------------------------------------------------------------------------


def test_photo_limit_per_contributor_is_enforced():
    trip = TripFactory(photo_limit_per_contributor=2)
    for i in range(2):
        Media.objects.create(trip=trip, author=trip.owner, display_path=f"t/{i}.webp")
    with pytest.raises(IntegrityError, match="photo limit"), transaction.atomic():
        Media.objects.create(trip=trip, author=trip.owner, display_path="t/x.webp")
    # Another contributor has their own allowance.
    Media.objects.create(trip=trip, author=UserFactory(), display_path="t/other.webp")


def test_trip_model_has_no_point_columns():
    """Trips reference raw data by time range; they never copy points (PLAN.md §5.5)."""
    names = {f.name for f in Trip._meta.get_fields()}
    assert not any("point" in n for n in names)
    assert timezone.now()  # keep the import used


def test_public_snapshot_columns_are_exactly_the_allowlist():
    """Adding a column to the public snapshot must be a deliberate change (PLAN.md §6.5)."""
    from travel.public.models import PUBLIC_TRIP_FIELDS

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'public_publictripsnapshot'"
        )
        columns = {row[0] for row in cursor.fetchall()}
    assert columns == set(PUBLIC_TRIP_FIELDS)
