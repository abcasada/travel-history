"""Synthetic test data. Coordinates are generic public places (city centres, airports), never
anyone's real locations."""

import datetime as dt
import uuid

import factory
from django.contrib.gis.geos import LineString, MultiLineString, Point
from django.utils import timezone

from travel.accounts.models import Person, Role, User
from travel.history.models import LocationPoint, PointSource, RawFile, TimelineSegment
from travel.trips.models import Leg, Route, Trip, TripParticipant
from travel.vehicles.models import Vehicle, VehicleOwnership

# A few synthetic reference points (public landmarks / city centres).
WICHITA = Point(-97.3375, 37.6922, srid=4326)
TOPEKA = Point(-95.6890, 39.0473, srid=4326)
DENVER = Point(-104.9903, 39.7392, srid=4326)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.test")
    display_name = factory.Sequence(lambda n: f"Test User {n}")
    role = Role.MEMBER
    oidc_issuer = "https://idp.example.test/"
    oidc_sub = factory.Sequence(lambda n: f"sub-{n}")


class PersonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Person

    display_name = factory.Sequence(lambda n: f"Person {n}")
    created_by = factory.SubFactory(UserFactory)


def user_with_person(**kwargs) -> User:
    user = UserFactory(**kwargs)
    user.person = PersonFactory(created_by=user, display_name=user.display_name)
    user.save(update_fields=["person"])
    return user


class TripFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Trip

    owner = factory.SubFactory(UserFactory)
    title = factory.Sequence(lambda n: f"Synthetic trip {n}")
    start_date = dt.date(2024, 5, 1)
    end_date = dt.date(2024, 5, 4)


class LegFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Leg

    trip = factory.SubFactory(TripFactory)
    sequence = factory.Sequence(lambda n: n + 1)
    mode = "drive"
    author = factory.LazyAttribute(lambda o: o.trip.owner)
    start_utc = factory.LazyFunction(lambda: timezone.now() - dt.timedelta(hours=5))
    end_utc = factory.LazyFunction(lambda: timezone.now() - dt.timedelta(hours=2))
    start_tz = "America/Chicago"
    end_tz = "America/Chicago"


class RouteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Route

    leg = factory.SubFactory(LegFactory)
    version = 1
    geom = factory.LazyFunction(
        lambda: MultiLineString(LineString(WICHITA, TOPEKA, srid=4326), srid=4326)
    )
    kind = Route.Kind.ROUTED
    engine = "valhalla"
    produced_at = factory.LazyFunction(timezone.now)
    created_by = factory.LazyAttribute(lambda o: o.leg.author)
    length_m = 220_000.0


class ParticipantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TripParticipant

    trip = factory.SubFactory(TripFactory)
    person = factory.SubFactory(PersonFactory)
    added_by = factory.LazyAttribute(lambda o: o.trip.owner)


class VehicleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Vehicle
        skip_postgeneration_save = True

    nickname = factory.Sequence(lambda n: f"Car {n}")
    year = 2012
    make = "Honda"
    model = "Accord"
    created_by = factory.SubFactory(UserFactory)

    @factory.post_generation
    def owner(self, create, extracted, **kwargs):
        """Every vehicle needs an ownership period (deferred trigger checks this)."""
        if not create:
            return
        person = extracted or PersonFactory(created_by=self.created_by)
        VehicleOwnership.objects.create(
            vehicle=self, owner_person=person, created_by=self.created_by
        )


class RawFileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RawFile

    owner = factory.SubFactory(UserFactory)
    original_name = "Timeline.json"
    size_bytes = 1000
    sha256 = factory.Sequence(lambda n: f"{n:064x}")
    storage_path = factory.LazyAttribute(lambda o: f"{o.owner.pk}/{o.sha256}.json.zst")
    compressed_size = 200


class LocationPointFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LocationPoint

    owner = factory.SubFactory(UserFactory)
    ts = factory.Sequence(lambda n: timezone.now() - dt.timedelta(minutes=n))
    geom = WICHITA
    source = PointSource.OWNTRACKS


class TimelineSegmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TimelineSegment

    owner = factory.SubFactory(UserFactory)
    lineage_id = factory.LazyFunction(uuid.uuid4)
    kind = TimelineSegment.Kind.VISIT
    start_utc = factory.LazyFunction(lambda: timezone.now() - dt.timedelta(hours=3))
    end_utc = factory.LazyFunction(lambda: timezone.now() - dt.timedelta(hours=1))
    geom = WICHITA
    data = factory.LazyFunction(lambda: {"synthetic": True})
    fingerprint = factory.Sequence(lambda n: f"{n:064x}")
