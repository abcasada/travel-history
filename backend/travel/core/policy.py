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
    from travel.trips.models import Leg, Purpose, Trip
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


def can_view_trip_sharing(user, trip: Trip) -> bool:
    """Public mode, unlisted-link slug, privacy zone: the people who may change them. The slug
    is a capability URL, so nobody else needs it (trips API, D-81)."""
    return can_edit_trip_core(user, trip)


def can_set_trip_purpose(user, trip: Trip, purpose: Purpose) -> bool:
    """Purposes are per user: a trip takes only its owner's (so another user's purpose names
    never surface on a trip). For a new trip, pass an unsaved Trip owned by the creator."""
    return can_edit_trip_core(user, trip) and purpose.owner_id == trip.owner_id


def can_delete_trip(user, trip: Trip) -> bool:
    return is_family(user) and trip.owner_id == user.pk  # PLAN.md D-17


def can_add_participant(user, trip: Trip, person: Person) -> bool:
    """Core editors add people they can see; adding someone can share the trip with them."""
    return can_edit_trip_core(user, trip) and can_view_person(user, person)


def can_remove_participant(user, trip: Trip) -> bool:
    return can_edit_trip_core(user, trip)


def can_set_participant_consent(user, trip: Trip, person: Person) -> bool:
    """A participant's public consent: their managing user decides (D-21, Q-7), Viewers
    included - it is a privacy choice about themselves, not a contribution."""
    return can_view_trip(user, trip) and can_set_public_consent(user, person)


def can_contribute(user, trip: Trip) -> bool:
    """Notes, photos, own legs, own tags, own GPS track: the owner or a participant (Members and
    the Admin only)."""
    if not can_create(user) or not can_view_trip(user, trip):
        return False
    return trip.owner_id == user.pk or is_trip_participant(user, trip)


def can_edit_contribution(user, obj) -> bool:
    """Notes, photos, tags, tracks, contributed legs: only their author."""
    return is_family(user) and obj.author_id == user.pk and can_view_trip(user, obj.trip)


def new_leg_kind(user, trip: Trip) -> str | None:
    """What a new leg by this user becomes: core editors add core legs; other contributors add
    their own legs (`is_contribution`, participant_scope author, D-22); anyone else: None."""
    if can_edit_trip_core(user, trip):
        return "core"
    if can_contribute(user, trip):
        return "contribution"
    return None


def can_edit_leg(user, leg: Leg) -> bool:
    if leg.is_contribution:
        return leg.author_id == user.pk and can_contribute(user, leg.trip)
    return can_edit_trip_core(user, leg.trip)


def can_delete_leg(user, leg: Leg) -> bool:
    """Same as editing: a contributor's leg only by its author while they may still
    contribute; core legs by core editors."""
    return can_edit_leg(user, leg)


def can_set_leg_participation(user, leg: Leg, person: Person) -> bool:
    """Core editors manage everyone's legs; participants set which legs they themselves were on.
    Either way only for people the user can see (a leg must not reveal a hidden person)."""
    if not can_view_person(user, person):
        return False
    if can_edit_trip_core(user, leg.trip):
        return True
    return manages_person(user, person) and can_contribute(user, leg.trip)


def can_set_public_consent(user, person: Person) -> bool:
    return manages_person(user, person)


# --- Accounts and people -------------------------------------------------------------------


def can_view_account(user, target: User) -> bool:
    """The full account row - email, OIDC issuer and subject, role: the account itself and the
    Admin only (D-72). Deactivated accounts see nothing, not even themselves (D-53)."""
    return is_family(user) and (target.pk == user.pk or is_admin(user))


def can_view_directory(user) -> bool:
    """Display names (and person link, active flag) of every account: the whole family (D-76)."""
    return is_family(user)


def can_view_person(user, person: Person) -> bool:
    """Mirror of app.can_view_person: family-visible people, people I created, my own person,
    anyone on a trip I can see (trip-level or a leg override), owners of vehicles I can see."""
    from travel.trips.models import LegParticipantOverride, TripParticipant
    from travel.vehicles.models import VehicleOwnership

    if not is_family(user):
        return False
    if (
        person.visibility == Person.Visibility.FAMILY
        or person.created_by_id == user.pk
        or person.pk == user.person_id
    ):
        return True
    trips = visible_trips(user)
    if TripParticipant.objects.filter(person_id=person.pk, trip__in=trips).exists():
        return True
    if LegParticipantOverride.objects.filter(person_id=person.pk, leg__trip__in=trips).exists():
        return True
    owned = VehicleOwnership.objects.filter(owner_person_id=person.pk).select_related("vehicle")
    return any(can_view_vehicle(user, o.vehicle) for o in owned)


def manages_person(user, person: Person) -> bool:
    """The linked account if the person has one, else whoever created the person."""
    from travel.accounts.models import UserDirectory

    if not is_family(user):
        return False
    linked = UserDirectory.objects.filter(person_id=person.pk).values_list("pk", flat=True).first()
    if linked is not None:
        return linked == user.pk
    return person.created_by_id == user.pk


# --- Vehicles ------------------------------------------------------------------------------


def vehicle_manager_id(vehicle: Vehicle, on: dt.date | None = None) -> int | None:
    """Current owner's account if the owner person has one, else the record's creator."""
    from travel.accounts.models import UserDirectory

    on = on or dt.date.today()
    current = vehicle.ownerships.filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=on),
        Q(valid_to__isnull=True) | Q(valid_to__gt=on),
        owner_person__isnull=False,
    ).values_list("owner_person_id", flat=True)
    for person_id in current:
        account = UserDirectory.objects.filter(person_id=person_id, is_active=True).values_list(
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


def can_use_vehicle(user, vehicle: Vehicle) -> bool:
    """Put a vehicle on a leg: any vehicle the user can see (a hidden one only by its manager)."""
    return can_create(user) and can_view_vehicle(user, vehicle)


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
