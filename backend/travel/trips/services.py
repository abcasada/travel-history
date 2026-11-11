"""Trips, legs and participants: the rules behind the trips API (PLAN.md §5.3, §6, §17).

Callers decide *whether* the user may act through travel.core.policy; these functions do the
work and validate the data. Row-level security and the guard triggers enforce the permission
rules again inside PostgreSQL, so a write the policy allowed but the database refuses surfaces
as a TripError (never a partial write): every write runs in its own savepoint.
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from typing import Any

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Exists, Max, OuterRef, Q, QuerySet
from django.utils import timezone

from travel.accounts.models import Person, UserDirectory
from travel.core import policy
from travel.core.choices import Visibility
from travel.geo.models import AircraftType, Airline, Airport
from travel.vehicles.models import Vehicle

from .models import Leg, LegParticipantOverride, Purpose, Trip, TripParticipant


class TripError(Exception):
    """A refused or invalid request, with the HTTP status the API should answer."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def invalid(message: str) -> TripError:
    return TripError(422, message)


@contextmanager
def guarded_write() -> Iterator[None]:
    """Run a write in a savepoint and turn a database refusal into a TripError."""
    try:
        with transaction.atomic():
            yield
    except IntegrityError as error:
        state = getattr(error.__cause__, "sqlstate", "")
        if state == "23505":
            raise TripError(409, "that already exists") from None
        raise invalid("the data breaks a database rule") from None
    except DatabaseError as error:
        if getattr(error.__cause__, "sqlstate", "") == "42501":  # RLS or a guard trigger
            raise TripError(403, "not allowed") from None
        raise


# --- Validation helpers ----------------------------------------------------------------------


@cache
def _zones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones())


def check_zone(name: str) -> str:
    if name and name not in _zones():
        raise invalid(f"unknown time zone {name!r}")
    return name


def check_dates(start: dt.date, end: dt.date) -> None:
    if end < start:
        raise invalid("end_date is before start_date")


def check_times(start: dt.datetime | None, end: dt.datetime | None) -> None:
    for value in (start, end):
        if value is not None and value.tzinfo is None:
            raise invalid("leg times need a UTC offset")
    if start is not None and end is not None and end < start:
        raise invalid("end_utc is before start_utc")


def _lookup(model, pk: int | None, what: str):
    """A referenced row the user can see (row-level security hides the rest), or 422. The same
    message for "missing" and "hidden", so the API is no oracle for other people's ids."""
    if pk is None:
        return None
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise invalid(f"unknown {what}")
    return obj


def visible_person(user, person_id: int) -> Person:
    """A person the user can see, or 404 (both layers: RLS hides the row, policy agrees)."""
    person = Person.objects.filter(pk=person_id).first()
    if person is None or not policy.can_view_person(user, person):
        raise TripError(404, "person not found")
    return person


# --- Trips -----------------------------------------------------------------------------------

TRIP_CORE_FIELDS = {
    "title",
    "start_date",
    "end_date",
    "date_precision",
    "notes",
    "photo_limit_per_contributor",
    "public_description",
    "public_show_times",
    "privacy_zone_enabled",
    "privacy_zone_radius_m",
}


def _apply_purpose(user, trip: Trip, purpose_id: int | None) -> None:
    purpose = _lookup(Purpose, purpose_id, "purpose")
    if purpose is not None and not policy.can_set_trip_purpose(user, trip, purpose):
        raise invalid("unknown purpose")  # another user's purpose: same answer as hidden
    trip.purpose = purpose


def _apply_visibility(trip: Trip, visibility: str | None, public_mode: str | None) -> None:
    if visibility is not None:
        trip.visibility = visibility
    if trip.visibility == Visibility.PUBLIC:
        # Unlisted is the narrower choice; listing on a profile has to be asked for.
        trip.public_mode = public_mode or trip.public_mode or Trip.PublicMode.UNLISTED
    elif public_mode:
        raise invalid("public_mode applies only to public trips")
    else:
        trip.public_mode = ""


def _apply_core(trip: Trip, data: dict[str, Any]) -> None:
    for field in TRIP_CORE_FIELDS & data.keys():
        if data[field] is None:
            raise invalid(f"{field} cannot be null")
        setattr(trip, field, data[field])


def create_trip(user, data: dict[str, Any]) -> Trip:
    trip = Trip(owner_id=user.pk, status=Trip.Status.CONFIRMED, source=Trip.Source.MANUAL)
    _apply_core(trip, data)
    check_dates(trip.start_date, trip.end_date)
    _apply_purpose(user, trip, data.get("purpose_id"))
    visibility = data.get("visibility")
    if visibility is None:
        # PLAN.md §6.2: the default comes from the purpose (Work -> private, else participants).
        visibility = trip.purpose.default_visibility if trip.purpose else Visibility.PARTICIPANTS
    _apply_visibility(trip, visibility, data.get("public_mode"))
    trip.edited_in_app_at = timezone.now()
    with guarded_write():
        trip.save()
    return trip


def update_trip(user, trip: Trip, data: dict[str, Any]) -> Trip:
    _apply_core(trip, data)
    check_dates(trip.start_date, trip.end_date)
    if "purpose_id" in data:
        _apply_purpose(user, trip, data["purpose_id"])
    if "visibility" in data or "public_mode" in data:
        wanted = data.get("visibility")
        if wanted is not None and not policy.can_set_trip_visibility(user, trip, wanted):
            raise TripError(403, "you would no longer see this trip; only its owner can do that")
        _apply_visibility(trip, wanted, data.get("public_mode"))
    trip.edited_in_app_at = timezone.now()
    with guarded_write():
        trip.save()
    return trip


def delete_trip(trip: Trip) -> None:
    """The owner deletes the trip; PostgreSQL removes its legs, routes, participants and
    everyone's contributions with it (DB-level cascades, PLAN.md D-50)."""
    with guarded_write():
        deleted, _ = Trip.objects.filter(pk=trip.pk).delete()
    if not deleted:
        raise TripError(403, "not allowed")


def touch(trip: Trip) -> None:
    """Record an in-app edit of the trip's core (rule 7: in-app edits beat imported changes)."""
    now = timezone.now()
    Trip.objects.filter(pk=trip.pk).update(edited_in_app_at=now, updated_at=now)


def filter_trips(
    qs: QuerySet[Trip],
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    visibility: str | None = None,
    status: str | None = None,
    person_id: int | None = None,
    text: str | None = None,
) -> QuerySet[Trip]:
    """Narrow a queryset of trips the user can already see (policy.visible_trips)."""
    if start is not None:
        qs = qs.filter(end_date__gte=start)
    if end is not None:
        qs = qs.filter(start_date__lte=end)
    if visibility:
        qs = qs.filter(visibility=visibility)
    if status:
        qs = qs.filter(status=status)
    if person_id is not None:
        qs = qs.filter(
            Exists(TripParticipant.objects.filter(trip=OuterRef("pk"), person_id=person_id))
            | Exists(
                LegParticipantOverride.objects.filter(
                    leg__trip=OuterRef("pk"), person_id=person_id, include=True
                )
            )
        )
    if text:
        qs = qs.filter(Q(title__icontains=text))
    return qs


# --- Legs ------------------------------------------------------------------------------------

LEG_PLAIN_FIELDS = {
    "mode",
    "start_utc",
    "start_tz",
    "end_utc",
    "end_tz",
    "time_precision",
    "origin_label",
    "destination_label",
    "flight_number",
    "aircraft_registration",
    "seat",
    "cabin_class",
}
LEG_BLANK_IF_NULL = {
    "start_tz",
    "end_tz",
    "origin_label",
    "destination_label",
    "flight_number",
    "aircraft_registration",
    "seat",
    "cabin_class",
}
LEG_REFERENCES = {
    "airline_id": (Airline, "airline"),
    "origin_airport_id": (Airport, "airport"),
    "destination_airport_id": (Airport, "airport"),
    "aircraft_type_id": (AircraftType, "aircraft type"),
}


def _apply_leg_fields(user, leg: Leg, data: dict[str, Any]) -> None:
    for field in LEG_PLAIN_FIELDS & data.keys():
        value = data[field]
        if value is None and field in LEG_BLANK_IF_NULL:
            value = ""
        if value is None and field in {"mode", "time_precision"}:
            raise invalid(f"{field} cannot be null")
        setattr(leg, field, value)
    check_zone(leg.start_tz)
    check_zone(leg.end_tz)
    check_times(leg.start_utc, leg.end_utc)
    for field, (model, what) in LEG_REFERENCES.items():
        if field in data:
            ref = _lookup(model, data[field], what)
            setattr(leg, field, ref.pk if ref else None)
    if "vehicle_id" in data:
        vehicle = _lookup(Vehicle, data["vehicle_id"], "vehicle")
        if vehicle is not None and not policy.can_use_vehicle(user, vehicle):
            raise invalid("unknown vehicle")  # hidden: same answer as missing
        leg.vehicle_id = vehicle.pk if vehicle else None
    if "participant_scope" in data and data["participant_scope"] is not None:
        if leg.is_contribution and data["participant_scope"] != Leg.ParticipantScope.AUTHOR:
            raise invalid("a contributed leg is always just its author's (D-22)")
        leg.participant_scope = data["participant_scope"]


def _next_sequence(trip: Trip) -> int:
    """Serialize leg creation per trip so two requests can't pick the same position (the unique
    sequence is checked only at commit)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('trips_leg.sequence:' || %s, 0))",
            [trip.pk],
        )
    current = Leg.objects.filter(trip=trip).aggregate(top=Max("sequence"))["top"]
    return (current or 0) + 1


def create_leg(user, trip: Trip, kind: str, data: dict[str, Any]) -> Leg:
    contribution = kind == "contribution"
    leg = Leg(
        trip=trip,
        author_id=user.pk,
        is_contribution=contribution,
        participant_scope=(
            Leg.ParticipantScope.AUTHOR if contribution else Leg.ParticipantScope.TRIP
        ),
    )
    _apply_leg_fields(user, leg, data)
    with guarded_write():
        leg.sequence = _next_sequence(trip)
        leg.save()
    if not contribution:
        touch(trip)
    return leg


def update_leg(user, leg: Leg, data: dict[str, Any]) -> Leg:
    _apply_leg_fields(user, leg, data)
    with guarded_write():
        leg.save()
    if not leg.is_contribution:
        touch(leg.trip)
    return leg


def delete_leg(leg: Leg) -> None:
    with guarded_write():
        deleted, _ = Leg.objects.filter(pk=leg.pk).delete()
    if not deleted:
        raise TripError(403, "not allowed")
    if not leg.is_contribution:
        touch(leg.trip)


# --- Participants ----------------------------------------------------------------------------


@dataclass
class Participation:
    """Who is on a trip: trip-level participants (with their consent) and, per leg, the
    effective participants (base set + includes - excludes, PLAN.md §5.3)."""

    trip_level: dict[int, TripParticipant]
    legs: dict[int, set[int]]


def author_people(author_ids: set[int]) -> dict[int, int | None]:
    """Each author's own person, read from the family directory (D-76)."""
    rows = UserDirectory.objects.filter(pk__in=author_ids).values_list("pk", "person_id")
    return dict(rows)


def participation(trip: Trip, legs: list[Leg]) -> Participation:
    trip_level = {p.person_id: p for p in TripParticipant.objects.filter(trip=trip)}
    overrides: dict[int, dict[int, bool]] = {}
    for o in LegParticipantOverride.objects.filter(leg__trip=trip):
        overrides.setdefault(o.leg_id, {})[o.person_id] = o.include
    authors = author_people({leg.author_id for leg in legs if leg.participant_scope == "author"})
    effective: dict[int, set[int]] = {}
    for leg in legs:
        people = set(_base_people(leg, set(trip_level), authors))
        for person_id, include in overrides.get(leg.pk, {}).items():
            (people.add if include else people.discard)(person_id)
        effective[leg.pk] = people
    return Participation(trip_level=trip_level, legs=effective)


def _base_people(leg: Leg, trip_people: set[int], authors: dict[int, int | None]) -> set[int]:
    if leg.participant_scope == Leg.ParticipantScope.AUTHOR:
        person_id = authors.get(leg.author_id)
        return {person_id} if person_id else set()
    return trip_people


def add_participant(user, trip: Trip, person: Person) -> TripParticipant:
    if TripParticipant.objects.filter(trip=trip, person=person).exists():
        raise TripError(409, "already a participant")
    with guarded_write():
        row = TripParticipant.objects.create(trip=trip, person=person, added_by_id=user.pk)
    touch(trip)
    return row


def remove_participant(trip: Trip, person: Person) -> None:
    """Take the person off the trip entirely: the trip-level row and their per-leg overrides,
    so a leftover leg include doesn't keep sharing the trip with them (D-81). Legs they
    contributed stay theirs (only the author deletes a contribution)."""
    with guarded_write():
        rows, _ = TripParticipant.objects.filter(trip=trip, person=person).delete()
        overrides, _ = LegParticipantOverride.objects.filter(leg__trip=trip, person=person).delete()
    if not rows and not overrides:
        raise TripError(404, "not a participant")
    touch(trip)


def set_consent(trip: Trip, person: Person, consent: bool) -> TripParticipant:
    row = TripParticipant.objects.filter(trip=trip, person=person).first()
    if row is None:
        raise TripError(404, "not a trip-level participant")
    row.public_consent = consent
    with guarded_write():
        updated = TripParticipant.objects.filter(pk=row.pk).update(public_consent=consent)
    if updated != 1:
        raise TripError(403, "not allowed")
    return row


def set_leg_participation(user, leg: Leg, person: Person, on_leg: bool) -> None:
    """Store only the difference from the leg's base set: an include or exclude override when
    the wish differs from the base, nothing when it matches."""
    trip_people = set(
        TripParticipant.objects.filter(trip_id=leg.trip_id).values_list("person_id", flat=True)
    )
    in_base = person.pk in _base_people(leg, trip_people, author_people({leg.author_id}))
    existing = LegParticipantOverride.objects.filter(leg=leg, person=person).first()
    with guarded_write():
        if on_leg == in_base:
            if existing is not None:
                LegParticipantOverride.objects.filter(pk=existing.pk).delete()
        elif existing is not None:
            LegParticipantOverride.objects.filter(pk=existing.pk).update(
                include=on_leg, set_by_id=user.pk
            )
        else:
            LegParticipantOverride.objects.create(
                leg=leg, person=person, include=on_leg, set_by_id=user.pk
            )
    if policy.can_edit_trip_core(user, leg.trip):
        touch(leg.trip)
