"""App-level permission rules (PLAN.md §6). The single place views/API consult before acting.

PostgreSQL row-level security enforces the same rules independently (core migration 0002); the
permission-matrix tests assert that both layers agree. Functions take the acting user (possibly
anonymous) and model instances. They run inside the request's RLS context, so lookups only see
rows the user may see - which is consistent with the rules, never more permissive.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from django.db.models import Exists, OuterRef, Q, QuerySet

from travel.accounts.models import Person, Role
from travel.core.choices import Visibility

if TYPE_CHECKING:
    from travel.accounts.models import User
    from travel.history.models import HomePeriod
    from travel.trips.models import Leg, Trip
    from travel.vehicles.models import Vehicle


# --- Who is acting -------------------------------------------------------------------------


def is_family(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active)


def is_admin(user) -> bool:
    return is_family(user) and user.role == Role.ADMIN


def can_create(user) -> bool:
    """Members and the Admin own data; Viewers are read-only (PLAN.md D-27)."""
    return is_family(user) and user.role in (Role.ADMIN, Role.MEMBER)


# --- Trips ---------------------------------------------------------------------------------


def is_trip_participant(user, trip: Trip) -> bool:
    from travel.trips.models import LegParticipantOverride, TripParticipant

    if not is_family(user) or user.person_id is None:
        return False
    return (
        TripParticipant.objects.filter(trip_id=trip.pk, person_id=user.person_id).exists()
        or LegParticipantOverride.objects.filter(
            leg__trip_id=trip.pk, person_id=user.person_id, include=True
        ).exists()
    )


def can_view_trip(user, trip: Trip) -> bool:
    if not is_family(user):
        return False
    if trip.owner_id == user.pk or trip.visibility in (Visibility.FAMILY, Visibility.PUBLIC):
        return True
    return trip.visibility == Visibility.PARTICIPANTS and is_trip_participant(user, trip)


def visible_trips(user) -> QuerySet[Trip]:
    """Queryset form of can_view_trip (the API's starting point for any trip listing)."""
    from travel.trips.models import LegParticipantOverride, Trip, TripParticipant

    if not is_family(user):
        return Trip.objects.none()
    participates = Q()
    if user.person_id is not None:
        participates = Exists(
            TripParticipant.objects.filter(trip=OuterRef("pk"), person_id=user.person_id)
        ) | Exists(
            LegParticipantOverride.objects.filter(
                leg__trip=OuterRef("pk"), person_id=user.person_id, include=True
            )
        )
    condition = Q(owner_id=user.pk) | Q(visibility__in=[Visibility.FAMILY, Visibility.PUBLIC])
    if user.person_id is not None:
        condition |= Q(visibility=Visibility.PARTICIPANTS) & participates
    return Trip.objects.filter(condition)


def can_edit_trip_core(user, trip: Trip) -> bool:
    """Owner, or the Admin on any trip the Admin can see."""
    if not is_family(user):
        return False
    return trip.owner_id == user.pk or (is_admin(user) and can_view_trip(user, trip))


def can_delete_trip(user, trip: Trip) -> bool:
    return is_family(user) and trip.owner_id == user.pk  # PLAN.md D-17


def can_contribute(user, trip: Trip) -> bool:
    """Notes, photos, own legs, own tags, own GPS track: the owner or a participant (Members and
    the Admin only)."""
    if not can_create(user) or not can_view_trip(user, trip):
        return False
    return trip.owner_id == user.pk or is_trip_participant(user, trip)


def can_edit_contribution(user, obj) -> bool:
    """Notes, photos, tags, tracks, contributed legs: only their author."""
    return is_family(user) and obj.author_id == user.pk and can_view_trip(user, obj.trip)


def can_edit_leg(user, leg: Leg) -> bool:
    if leg.is_contribution:
        return leg.author_id == user.pk and can_contribute(user, leg.trip)
    return can_edit_trip_core(user, leg.trip)


def can_set_leg_participation(user, leg: Leg, person: Person) -> bool:
    """Core editors manage everyone's legs; participants set which legs they themselves were on."""
    if can_edit_trip_core(user, leg.trip):
        return True
    return manages_person(user, person) and can_contribute(user, leg.trip)


def can_set_public_consent(user, person: Person) -> bool:
    return manages_person(user, person)


# --- People --------------------------------------------------------------------------------


def manages_person(user, person: Person) -> bool:
    """The linked account if the person has one, else whoever created the person."""
    from travel.accounts.models import User

    if not is_family(user):
        return False
    linked = User.objects.filter(person_id=person.pk).values_list("pk", flat=True).first()
    if linked is not None:
        return linked == user.pk
    return person.created_by_id == user.pk


# --- Vehicles ------------------------------------------------------------------------------


def vehicle_manager_id(vehicle: Vehicle, on: dt.date | None = None) -> int | None:
    """Current owner's account if the owner person has one, else the record's creator."""
    from travel.accounts.models import User

    on = on or dt.date.today()
    current = vehicle.ownerships.filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=on),
        Q(valid_to__isnull=True) | Q(valid_to__gt=on),
        owner_person__isnull=False,
    ).values_list("owner_person_id", flat=True)
    for person_id in current:
        account = User.objects.filter(person_id=person_id, is_active=True).values_list(
            "pk", flat=True
        )
        if account:
            return account[0]
    return vehicle.created_by_id


def can_view_vehicle(user, vehicle: Vehicle) -> bool:
    if not is_family(user):
        return False
    return (
        not vehicle.hidden
        or vehicle.created_by_id == user.pk
        or vehicle_manager_id(vehicle) == user.pk
    )


def can_manage_vehicle(user, vehicle: Vehicle) -> bool:
    if not is_family(user):
        return False
    return vehicle_manager_id(vehicle) == user.pk or (
        is_admin(user) and can_view_vehicle(user, vehicle)
    )


def can_view_vehicle_private(user, vehicle: Vehicle) -> bool:
    """Plate and VIN: the managing user only (not even the Admin)."""
    return is_family(user) and vehicle_manager_id(vehicle) == user.pk


# --- Raw history and homes -----------------------------------------------------------------


def can_access_raw_history(user, owner_id: int) -> bool:
    """Raw points, segments, imports, coverage: only their owner, never the Admin."""
    return is_family(user) and owner_id == user.pk


def can_import(user) -> bool:
    return can_create(user)


def can_view_home_period(user, period: HomePeriod) -> bool:
    return is_family(user) and (period.managed_by_id == user.pk or period.shared_with_family)


def can_edit_home_period(user, period: HomePeriod) -> bool:
    return is_family(user) and period.managed_by_id == user.pk


# --- Administration ------------------------------------------------------------------------


def can_manage_access(user) -> bool:
    """Access requests, allowlist, invites, roles."""
    return is_admin(user)


def can_change_role(user, target: User) -> bool:
    """The Admin changes other users' roles; not their own (no accidental lock-out)."""
    return is_admin(user) and target.pk != user.pk
