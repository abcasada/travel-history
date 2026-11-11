"""Trips, legs and participants API (PLAN.md §17; work-order item 6, the core of T18).

Permission rules (PLAN.md §6.2-§6.3) are decided in travel.core.policy and enforced again by
row-level security, which also limits every query below to rows the caller may see. A trip the
caller cannot see answers 404 (its existence is not revealed); a visible trip the caller may not
change answers 403. Other users appear only through the family directory: id and display name,
never email or OIDC identity (D-72, D-76).
"""

import datetime as dt
from typing import Any, Literal

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status
from ninja.errors import HttpError
from pydantic import AwareDatetime

from travel.accounts.models import Person, UserDirectory
from travel.core import policy
from travel.core.choices import DatePrecision, TravelMode, Visibility
from travel.vehicles.models import Vehicle

from . import services
from .models import CabinClass, Leg, Trip
from .services import TripError

router = Router(tags=["trips"])


# --- Output schemas ---------------------------------------------------------------------------


class UserRef(Schema):
    """Another account as the family sees it (the directory, D-76)."""

    id: int
    display_name: str


class PersonRef(Schema):
    id: int
    display_name: str


class PurposeRef(Schema):
    id: int
    name: str


class VehicleRef(Schema):
    id: int
    label: str


class TripAccessOut(Schema):
    """What the caller may do with this trip (the UI hides what it can't do)."""

    edit: bool
    delete: bool
    contribute: bool
    add_leg: Literal["core", "contribution"] | None


class TripSharingOut(Schema):
    """Public-page settings; only for those who may change them (owner, or the Admin)."""

    public_mode: str
    public_slug: str
    public_description: str
    public_show_times: bool
    privacy_zone_enabled: bool
    privacy_zone_radius_m: int


class TripOut(Schema):
    id: int
    title: str
    start_date: dt.date
    end_date: dt.date
    date_precision: str
    status: str
    visibility: str
    source: str
    locked: bool
    needs_review: bool
    purpose: PurposeRef | None
    owner: UserRef
    is_owner: bool
    cover_media_id: int | None
    created_at: dt.datetime
    updated_at: dt.datetime


class TripPageOut(Schema):
    count: int
    items: list[TripOut]


class LegOut(Schema):
    id: int
    trip_id: int
    sequence: int
    mode: str
    start_utc: dt.datetime | None
    start_tz: str
    end_utc: dt.datetime | None
    end_tz: str
    time_precision: str
    origin_label: str
    destination_label: str
    origin_stop_id: int | None
    destination_stop_id: int | None
    vehicle: VehicleRef | None = Field(
        description="null when the leg has no vehicle or the caller can't see it (hidden)"
    )
    author: UserRef
    is_contribution: bool
    participant_scope: str
    current_route_id: int | None
    distance_m: float | None
    airline_id: int | None
    flight_number: str
    origin_airport_id: int | None
    destination_airport_id: int | None
    aircraft_type_id: int | None
    aircraft_registration: str
    seat: str
    cabin_class: str
    participant_ids: list[int] = Field(description="people effectively on this leg")
    can_edit: bool


class ParticipantOut(Schema):
    person: PersonRef
    on_trip: bool = Field(description="a trip-level participant (else only on some legs)")
    public_consent: bool | None = Field(description="null unless on_trip")
    leg_ids: list[int]
    is_me: bool
    can_set_consent: bool


class TripDetailOut(TripOut):
    notes: str
    photo_limit_per_contributor: int
    edited_in_app_at: dt.datetime | None
    sharing: TripSharingOut | None
    access: TripAccessOut
    participants: list[ParticipantOut]
    legs: list[LegOut]


# --- Input schemas ----------------------------------------------------------------------------


class TripIn(Schema):
    title: str = Field(min_length=1, max_length=200)
    start_date: dt.date
    end_date: dt.date
    date_precision: DatePrecision | None = None
    purpose_id: int | None = None
    visibility: Visibility | None = Field(
        None, description="default: the purpose's default visibility, else participants"
    )
    public_mode: Trip.PublicMode | None = Field(None, description="public trips only")
    notes: str | None = None
    public_description: str | None = None
    public_show_times: bool | None = None
    privacy_zone_enabled: bool | None = None
    privacy_zone_radius_m: int | None = Field(None, ge=0, le=50_000)
    photo_limit_per_contributor: int | None = Field(None, ge=0, le=1000)


class TripPatchIn(Schema):
    """Only the fields sent are changed."""

    title: str | None = Field(None, min_length=1, max_length=200)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    date_precision: DatePrecision | None = None
    purpose_id: int | None = None
    visibility: Visibility | None = None
    public_mode: Trip.PublicMode | None = None
    notes: str | None = None
    public_description: str | None = None
    public_show_times: bool | None = None
    privacy_zone_enabled: bool | None = None
    privacy_zone_radius_m: int | None = Field(None, ge=0, le=50_000)
    photo_limit_per_contributor: int | None = Field(None, ge=0, le=1000)


class TripListIn(Schema):
    start: dt.date | None = Field(None, alias="from", description="trips ending on or after")
    end: dt.date | None = Field(None, alias="to", description="trips starting on or before")
    visibility: Visibility | None = None
    status: Trip.Status | None = None
    person: int | None = Field(None, description="trips this person is on")
    q: str | None = Field(None, max_length=200, description="text in the title")
    limit: int = Field(100, ge=1, le=500)
    offset: int = Field(0, ge=0)


class LegFieldsIn(Schema):
    start_utc: AwareDatetime | None = None
    start_tz: str | None = Field(None, max_length=64, description="IANA zone name")
    end_utc: AwareDatetime | None = None
    end_tz: str | None = Field(None, max_length=64, description="IANA zone name")
    time_precision: DatePrecision | None = None
    origin_label: str | None = Field(None, max_length=200)
    destination_label: str | None = Field(None, max_length=200)
    vehicle_id: int | None = Field(None, description="a vehicle the caller can see")
    participant_scope: Leg.ParticipantScope | None = Field(
        None, description="core legs only; a contributed leg is always 'author'"
    )
    airline_id: int | None = None
    flight_number: str | None = Field(None, max_length=16)
    origin_airport_id: int | None = None
    destination_airport_id: int | None = None
    aircraft_type_id: int | None = None
    aircraft_registration: str | None = Field(None, max_length=16)
    seat: str | None = Field(None, max_length=8)
    cabin_class: CabinClass | None = None


class LegIn(LegFieldsIn):
    mode: TravelMode


class LegPatchIn(LegFieldsIn):
    """Only the fields sent are changed."""

    mode: TravelMode | None = None


class ParticipantIn(Schema):
    person_id: int


class ConsentIn(Schema):
    public_consent: bool


class LegParticipationIn(Schema):
    on_leg: bool


# --- Lookups (both layers: row-level security hides rows, policy agrees) ---------------------


def _fail(error: TripError):
    raise HttpError(error.status, error.message)


def _trip(request: HttpRequest, trip_id: int) -> Trip:
    trip = policy.visible_trips(request.user).select_related("purpose").filter(pk=trip_id).first()
    if trip is None or not policy.can_view_trip(request.user, trip):
        raise HttpError(404, "trip not found")
    return trip


def _leg(request: HttpRequest, leg_id: int) -> Leg:
    leg = Leg.objects.select_related("trip", "trip__purpose").filter(pk=leg_id).first()
    if leg is None or not policy.can_view_trip(request.user, leg.trip):
        raise HttpError(404, "leg not found")
    return leg


def _person(request: HttpRequest, person_id: int) -> Person:
    try:
        return services.visible_person(request.user, person_id)
    except TripError as error:
        _fail(error)


def _changes(payload: Schema) -> dict[str, Any]:
    return payload.model_dump(exclude_unset=True)


# --- Presenters --------------------------------------------------------------------------------


def _directory(user_ids: set[int]) -> dict[int, dict]:
    rows = UserDirectory.objects.filter(pk__in=user_ids).values("id", "display_name")
    found = {row["id"]: row for row in rows}
    return {uid: found.get(uid, {"id": uid, "display_name": ""}) for uid in user_ids}


def _trip_summary(user, trip: Trip, owners: dict[int, dict]) -> dict:
    purpose = trip.purpose  # row-level security leaves it None if the caller can't see it
    return {
        "id": trip.pk,
        "title": trip.title,
        "start_date": trip.start_date,
        "end_date": trip.end_date,
        "date_precision": trip.date_precision,
        "status": trip.status,
        "visibility": trip.visibility,
        "source": trip.source,
        "locked": trip.locked,
        "needs_review": trip.needs_review,
        "purpose": {"id": purpose.pk, "name": purpose.name} if purpose else None,
        "owner": owners[trip.owner_id],
        "is_owner": trip.owner_id == user.pk,
        "cover_media_id": trip.cover_media_id,
        "created_at": trip.created_at,
        "updated_at": trip.updated_at,
    }


def _visible_vehicles(user, vehicle_ids: set[int]) -> dict[int, dict]:
    vehicles = Vehicle.objects.filter(pk__in=vehicle_ids)
    return {
        v.pk: {"id": v.pk, "label": str(v)} for v in vehicles if policy.can_view_vehicle(user, v)
    }


def _visible_people(user, person_ids: set[int]) -> dict[int, Person]:
    people = Person.objects.filter(pk__in=person_ids)
    return {p.pk: p for p in people if policy.can_view_person(user, p)}


class _TripView:
    """Everything shown about one trip's legs and people, loaded once."""

    def __init__(self, user, trip: Trip):
        self.user = user
        self.trip = trip
        self.legs = list(Leg.objects.filter(trip=trip).order_by("sequence", "pk"))
        for leg in self.legs:
            leg.trip = trip
        self.part = services.participation(trip, self.legs)
        everyone = set(self.part.trip_level).union(*self.part.legs.values())
        self.people = _visible_people(user, everyone)
        self.vehicles = _visible_vehicles(user, {g.vehicle_id for g in self.legs if g.vehicle_id})
        self.authors = _directory({g.author_id for g in self.legs})

    def leg(self, leg: Leg) -> dict:
        return {
            **{
                field: getattr(leg, field)
                for field in (
                    "id",
                    "trip_id",
                    "sequence",
                    "mode",
                    "start_utc",
                    "start_tz",
                    "end_utc",
                    "end_tz",
                    "time_precision",
                    "origin_label",
                    "destination_label",
                    "origin_stop_id",
                    "destination_stop_id",
                    "is_contribution",
                    "participant_scope",
                    "current_route_id",
                    "distance_m",
                    "airline_id",
                    "flight_number",
                    "origin_airport_id",
                    "destination_airport_id",
                    "aircraft_type_id",
                    "aircraft_registration",
                    "seat",
                    "cabin_class",
                )
            },
            "vehicle": self.vehicles.get(leg.vehicle_id) if leg.vehicle_id else None,
            "author": self.authors[leg.author_id],
            "participant_ids": sorted(p for p in self.part.legs[leg.pk] if p in self.people),
            "can_edit": policy.can_edit_leg(self.user, leg),
        }

    def participants(self) -> list[dict]:
        rows = []
        for person_id, person in self.people.items():
            row = self.part.trip_level.get(person_id)
            rows.append(
                {
                    "person": {"id": person.pk, "display_name": person.display_name},
                    "on_trip": row is not None,
                    "public_consent": row.public_consent if row else None,
                    "leg_ids": [g.pk for g in self.legs if person_id in self.part.legs[g.pk]],
                    "is_me": person_id == self.user.person_id,
                    "can_set_consent": row is not None
                    and policy.can_set_participant_consent(self.user, self.trip, person),
                    "_order": (row is None, row.pk if row else 0, person.display_name),
                }
            )
        rows.sort(key=lambda r: r.pop("_order"))
        return rows

    def participant(self, person_id: int) -> dict:
        for row in self.participants():
            if row["person"]["id"] == person_id:
                return row
        raise HttpError(404, "not a participant")

    def leg_by_id(self, leg_id: int) -> dict:
        return self.leg(next(g for g in self.legs if g.pk == leg_id))

    def detail(self) -> dict:
        user, trip = self.user, self.trip
        sharing = None
        if policy.can_view_trip_sharing(user, trip):
            sharing = {
                field: getattr(trip, field)
                for field in (
                    "public_mode",
                    "public_slug",
                    "public_description",
                    "public_show_times",
                    "privacy_zone_enabled",
                    "privacy_zone_radius_m",
                )
            }
        return {
            **_trip_summary(user, trip, _directory({trip.owner_id})),
            "notes": trip.notes,
            "photo_limit_per_contributor": trip.photo_limit_per_contributor,
            "edited_in_app_at": trip.edited_in_app_at,
            "sharing": sharing,
            "access": {
                "edit": policy.can_edit_trip_core(user, trip),
                "delete": policy.can_delete_trip(user, trip),
                "contribute": policy.can_contribute(user, trip),
                "add_leg": policy.new_leg_kind(user, trip),
            },
            "participants": self.participants(),
            "legs": [self.leg(g) for g in self.legs],
        }


# --- Trips -----------------------------------------------------------------------------------


@router.get("/trips", response=TripPageOut, operation_id="listTrips")
def list_trips(request, params: Query[TripListIn]):
    """Trips the caller can see (PLAN.md §6.2), newest first."""
    qs = services.filter_trips(
        policy.visible_trips(request.user).select_related("purpose"),
        start=params.start,
        end=params.end,
        visibility=params.visibility,
        status=params.status,
        person_id=params.person,
        text=params.q,
    )
    count = qs.count()
    page = list(qs.order_by("-start_date", "-pk")[params.offset : params.offset + params.limit])
    owners = _directory({t.owner_id for t in page})
    return {"count": count, "items": [_trip_summary(request.user, t, owners) for t in page]}


@router.post("/trips", response={201: TripDetailOut}, operation_id="createTrip")
def create_trip(request, payload: TripIn):
    """Members and the Admin create trips they own; Viewers are read-only (D-27)."""
    if not policy.can_create(request.user):
        raise HttpError(403, "your role cannot create trips")
    try:
        trip = services.create_trip(request.user, _changes(payload))
    except TripError as error:
        _fail(error)
    return Status(201, _TripView(request.user, trip).detail())


@router.get("/trips/{trip_id}", response=TripDetailOut, operation_id="getTrip")
def get_trip(request, trip_id: int):
    return _TripView(request.user, _trip(request, trip_id)).detail()


@router.patch("/trips/{trip_id}", response=TripDetailOut, operation_id="updateTrip")
def update_trip(request, trip_id: int, payload: TripPatchIn):
    """Trip core (title, dates, purpose, visibility, sharing): the owner, or the Admin."""
    trip = _trip(request, trip_id)
    if not policy.can_edit_trip_core(request.user, trip):
        raise HttpError(403, "only the trip's owner (or the Admin) can edit it")
    try:
        trip = services.update_trip(request.user, trip, _changes(payload))
    except TripError as error:
        _fail(error)
    return _TripView(request.user, trip).detail()


@router.delete("/trips/{trip_id}", response={204: None}, operation_id="deleteTrip")
def delete_trip(request, trip_id: int):
    """Only the owner deletes a trip, with everyone's contributions on it (D-17)."""
    trip = _trip(request, trip_id)
    if not policy.can_delete_trip(request.user, trip):
        raise HttpError(403, "only the trip's owner can delete it")
    try:
        services.delete_trip(trip)
    except TripError as error:
        _fail(error)
    return Status(204, None)


# --- Legs ------------------------------------------------------------------------------------


@router.get("/trips/{trip_id}/legs", response=list[LegOut], operation_id="listLegs")
def list_legs(request, trip_id: int):
    view = _TripView(request.user, _trip(request, trip_id))
    return [view.leg(g) for g in view.legs]


@router.post("/trips/{trip_id}/legs", response={201: LegOut}, operation_id="createLeg")
def create_leg(request, trip_id: int, payload: LegIn):
    """Core editors add core legs; participants (Members) add their own legs, which only they
    edit and which count just them as travelers unless they add others (D-22)."""
    trip = _trip(request, trip_id)
    kind = policy.new_leg_kind(request.user, trip)
    if kind is None:
        raise HttpError(403, "you cannot add legs to this trip")
    try:
        leg = services.create_leg(request.user, trip, kind, _changes(payload))
    except TripError as error:
        _fail(error)
    return Status(201, _TripView(request.user, trip).leg_by_id(leg.pk))


@router.get("/legs/{leg_id}", response=LegOut, operation_id="getLeg")
def get_leg(request, leg_id: int):
    leg = _leg(request, leg_id)
    return _TripView(request.user, leg.trip).leg_by_id(leg.pk)


@router.patch("/legs/{leg_id}", response=LegOut, operation_id="updateLeg")
def update_leg(request, leg_id: int, payload: LegPatchIn):
    leg = _leg(request, leg_id)
    if not policy.can_edit_leg(request.user, leg):
        raise HttpError(403, "you cannot edit this leg")
    try:
        services.update_leg(request.user, leg, _changes(payload))
    except TripError as error:
        _fail(error)
    return _TripView(request.user, leg.trip).leg_by_id(leg.pk)


@router.delete("/legs/{leg_id}", response={204: None}, operation_id="deleteLeg")
def delete_leg(request, leg_id: int):
    leg = _leg(request, leg_id)
    if not policy.can_delete_leg(request.user, leg):
        raise HttpError(403, "you cannot delete this leg")
    try:
        services.delete_leg(leg)
    except TripError as error:
        _fail(error)
    return Status(204, None)


def _set_leg_participation(request, leg: Leg, person: Person, on_leg: bool):
    if not policy.can_set_leg_participation(request.user, leg, person):
        raise HttpError(403, "you cannot change who was on this leg")
    try:
        services.set_leg_participation(request.user, leg, person, on_leg)
    except TripError as error:
        _fail(error)
    return _TripView(request.user, leg.trip).leg_by_id(leg.pk)


@router.put(
    "/legs/{leg_id}/participants/{person_id}",
    response=LegOut,
    operation_id="setLegParticipation",
)
def set_leg_participation(request, leg_id: int, person_id: int, payload: LegParticipationIn):
    """Whether a person was on this leg. Core editors set it for anyone they can see; a
    participant sets it for themselves and people they manage."""
    leg = _leg(request, leg_id)
    return _set_leg_participation(request, leg, _person(request, person_id), payload.on_leg)


@router.put(
    "/legs/{leg_id}/my-participation", response=LegOut, operation_id="setMyLegParticipation"
)
def set_my_leg_participation(request, leg_id: int, payload: LegParticipationIn):
    leg = _leg(request, leg_id)
    if request.user.person_id is None:
        raise HttpError(409, "your account is not linked to a person")
    return _set_leg_participation(
        request, leg, _person(request, request.user.person_id), payload.on_leg
    )


# --- Participants ----------------------------------------------------------------------------


@router.get(
    "/trips/{trip_id}/participants",
    response=list[ParticipantOut],
    operation_id="listParticipants",
)
def list_participants(request, trip_id: int):
    """Everyone on the trip: trip-level participants first, then people only on some legs."""
    return _TripView(request.user, _trip(request, trip_id)).participants()


@router.post(
    "/trips/{trip_id}/participants",
    response={201: ParticipantOut},
    operation_id="addParticipant",
)
def add_participant(request, trip_id: int, payload: ParticipantIn):
    """Core editors add people they can see. On a 'participants' trip this shares the trip
    with that person's account."""
    trip = _trip(request, trip_id)
    # Refuse non-editors before looking the person up, so they learn nothing about it.
    if not policy.can_edit_trip_core(request.user, trip):
        raise HttpError(403, "only the trip's owner (or the Admin) can add participants")
    person = _person(request, payload.person_id)
    if not policy.can_add_participant(request.user, trip, person):
        raise HttpError(403, "you cannot add this person")
    try:
        services.add_participant(request.user, trip, person)
    except TripError as error:
        _fail(error)
    return Status(201, _TripView(request.user, trip).participant(person.pk))


@router.delete(
    "/trips/{trip_id}/participants/{person_id}",
    response={204: None},
    operation_id="removeParticipant",
)
def remove_participant(request, trip_id: int, person_id: int):
    """Takes the person off the trip and off every leg override (D-81)."""
    trip = _trip(request, trip_id)
    if not policy.can_remove_participant(request.user, trip):
        raise HttpError(403, "only the trip's owner (or the Admin) can remove participants")
    person = _person(request, person_id)
    try:
        services.remove_participant(trip, person)
    except TripError as error:
        _fail(error)
    return Status(204, None)


@router.put(
    "/trips/{trip_id}/participants/{person_id}/consent",
    response=ParticipantOut,
    operation_id="setParticipantConsent",
)
def set_participant_consent(request, trip_id: int, person_id: int, payload: ConsentIn):
    """Public consent for a participant's name, notes, photos and legs (§6.6): decided by the
    participant, or for a person without an account by their managing user (D-21)."""
    trip = _trip(request, trip_id)
    person = _person(request, person_id)
    if not policy.can_set_participant_consent(request.user, trip, person):
        raise HttpError(403, "only this participant (or their managing user) decides")
    try:
        services.set_consent(trip, person, payload.public_consent)
    except TripError as error:
        _fail(error)
    return _TripView(request.user, trip).participant(person.pk)
