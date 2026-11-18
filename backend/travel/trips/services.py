"""Trips, legs and participants: the rules behind the trips API (PLAN.md §5.3, §6, §17).

Callers decide *whether* the user may act through travel.core.policy; these functions do the
work and validate the data. Row-level security and the guard triggers enforce the permission
rules again inside PostgreSQL, so a write the policy allowed but the database refuses surfaces
as a TripError (never a partial write): every write runs in its own savepoint.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import zoneinfo
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from typing import Any

from django.contrib.gis.geos import Point, Polygon
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.db.models import Exists, Max, OuterRef, Q, QuerySet
from django.utils import timezone

from travel.accounts.models import Person, UserDirectory
from travel.core import policy
from travel.core.choices import Visibility
from travel.geo.models import AircraftType, Airline, Airport
from travel.media.models import Media
from travel.vehicles.models import Vehicle

from .models import (
    Leg,
    LegParticipantOverride,
    Place,
    Purpose,
    Stop,
    Tag,
    TrackContribution,
    Trip,
    TripNote,
    TripParticipant,
    TripTag,
)


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


def parse_bbox(value: str) -> list[Polygon]:
    """`minLon,minLat,maxLon,maxLat` in WGS84. A box across the antimeridian (minLon > maxLon)
    becomes two boxes."""
    try:
        west, south, east, north = (float(part) for part in value.split(","))
    except ValueError:
        raise invalid("bbox must be minLon,minLat,maxLon,maxLat") from None
    if not all(math.isfinite(v) for v in (west, south, east, north)):
        raise invalid("bbox must be minLon,minLat,maxLon,maxLat")
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90):
        raise invalid("bbox is outside -180..180, -90..90 or has minLat > maxLat")
    boxes = [(west, south, east, north)]
    if west > east:
        boxes = [(west, south, 180.0, north), (-180.0, south, east, north)]
    polygons = []
    for box in boxes:
        polygon = Polygon.from_bbox(box)
        polygon.srid = 4326
        polygons.append(polygon)
    return polygons


def _in_boxes(boxes: list[Polygon]) -> Q:
    """Trips with something inside the boxes: a leg's current route, a leg's airport, or a
    stop's place. Each lookup runs under row-level security like the trip itself."""
    on_leg = Q()
    at_stop = Q()
    for box in boxes:
        on_leg |= Q(current_route__geom__intersects=box)
        on_leg |= Q(origin_airport__point__intersects=box)
        on_leg |= Q(destination_airport__point__intersects=box)
        at_stop |= Q(place__point__intersects=box)
    return Q(Exists(Leg.objects.filter(on_leg, trip=OuterRef("pk")))) | Q(
        Exists(Stop.objects.filter(at_stop, trip=OuterRef("pk")))
    )


def visible_vehicle_ids(user, vehicle_ids: list[int]) -> list[int]:
    """The ones the user can see. A filter on a hidden vehicle must not reveal which visible
    trips use it (the leg shows no vehicle to them), so it matches nothing, like a missing id."""
    vehicles = Vehicle.objects.filter(pk__in=vehicle_ids)
    return [v.pk for v in vehicles if policy.can_view_vehicle(user, v)]


def filter_trips(
    qs: QuerySet[Trip],
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    visibility: str | None = None,
    status: str | None = None,
    person_id: int | None = None,
    text: str | None = None,
    purpose_ids: list[int] | None = None,
    tag_ids: list[int] | None = None,
    vehicle_ids: list[int] | None = None,
    modes: list[str] | None = None,
    bbox: str | None = None,
) -> QuerySet[Trip]:
    """Narrow a queryset of trips the user can already see (policy.visible_trips). Each list
    filter matches any of its values; different filters must all match. `vehicle_ids` must
    already be limited to visible vehicles (visible_vehicle_ids); an empty list matches none."""
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
    if purpose_ids:
        qs = qs.filter(purpose_id__in=purpose_ids)
    if tag_ids:
        qs = qs.filter(Exists(TripTag.objects.filter(trip=OuterRef("pk"), tag_id__in=tag_ids)))
    if vehicle_ids is not None:
        qs = qs.filter(Exists(Leg.objects.filter(trip=OuterRef("pk"), vehicle_id__in=vehicle_ids)))
    if modes:
        qs = qs.filter(Exists(Leg.objects.filter(trip=OuterRef("pk"), mode__in=modes)))
    if bbox:
        qs = qs.filter(_in_boxes(parse_bbox(bbox)))
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
    for field in ("origin_stop_id", "destination_stop_id"):
        if field in data:
            # A stop of the same trip (row-level security hides others' trips' stops; a stop of
            # another visible trip gets the same answer). A trigger checks the trip again.
            stop = _lookup(Stop, data[field], "stop")
            if stop is not None and stop.trip_id != leg.trip_id:
                raise invalid("unknown stop")
            setattr(leg, field, stop.pk if stop else None)
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


def remove_participant_if_present(trip: Trip, person: Person) -> bool:
    try:
        remove_participant(trip, person)
    except TripError as error:
        if error.status == 404:
            return False
        raise
    return True


# --- Leg order -------------------------------------------------------------------------------


def reorder_legs(trip: Trip, leg_ids: list[int]) -> None:
    """Renumber every leg of the trip in the given order (1, 2, ...). Contributed legs are
    otherwise only their author's to change, so this goes through app.reorder_legs, which
    checks the caller is a core editor and changes nothing but the order."""
    current = set(Leg.objects.filter(trip=trip).values_list("pk", flat=True))
    if len(leg_ids) != len(set(leg_ids)) or set(leg_ids) != current:
        raise invalid("list every leg of the trip exactly once")
    with guarded_write(), connection.cursor() as cursor:
        cursor.execute("SELECT app.reorder_legs(%s, %s::bigint[])", [trip.pk, leg_ids])
    touch(trip)


# --- Contributions: shared helpers -----------------------------------------------------------


def delete_row(model, pk: int) -> None:
    """Delete one row the policy allowed; row-level security decides again (0 rows: refused)."""
    with guarded_write():
        deleted, _ = model.objects.filter(pk=pk).delete()
    if not deleted:
        raise TripError(403, "not allowed")


def _save(obj) -> None:
    with guarded_write():
        obj.save()


def _require(data: dict[str, Any], fields: set[str]) -> None:
    for field in fields & data.keys():
        if data[field] is None:
            raise invalid(f"{field} cannot be null")


# --- Tags ------------------------------------------------------------------------------------

COLOR = re.compile(r"^(#[0-9a-fA-F]{6})?$")


def _apply_tag(tag: Tag, data: dict[str, Any]) -> None:
    _require(data, {"name", "color"})
    if "name" in data:
        tag.name = data["name"].strip()
        if not tag.name:
            raise invalid("name cannot be blank")
    if "color" in data:
        if not COLOR.match(data["color"]):
            raise invalid("color must be #rrggbb or empty")
        tag.color = data["color"]


def create_tag(user, data: dict[str, Any]) -> Tag:
    tag = Tag(owner_id=user.pk)
    _apply_tag(tag, data)
    _save(tag)
    return tag


def update_tag(tag: Tag, data: dict[str, Any]) -> Tag:
    _apply_tag(tag, data)
    _save(tag)
    return tag


def own_tag(user, *, tag_id: int | None = None, name: str | None = None) -> Tag:
    """One of the user's own tags by id (422 for anyone else's, as for a missing one), or by
    name, created if the user has none by that name yet (names are case-insensitive)."""
    if tag_id is not None:
        tag = Tag.objects.filter(pk=tag_id, owner_id=user.pk).first()
        if tag is None:
            raise invalid("unknown tag")
        return tag
    name = (name or "").strip()
    if not name:
        raise invalid("give a tag_id or a name")
    existing = Tag.objects.filter(owner_id=user.pk, name__iexact=name).first()
    return existing or create_tag(user, {"name": name})


def tag_trip(user, trip: Trip, tag: Tag) -> TripTag:
    if TripTag.objects.filter(trip=trip, tag=tag).exists():
        raise TripError(409, "the trip already has this tag")
    with guarded_write():
        return TripTag.objects.create(trip=trip, tag=tag, author_id=user.pk)


# --- Notes -----------------------------------------------------------------------------------


def add_note(user, trip: Trip, data: dict[str, Any]) -> TripNote:
    _require(data, {"body", "public_consent"})
    note = TripNote(trip=trip, author_id=user.pk, **data)
    _save(note)
    return note


def update_note(note: TripNote, data: dict[str, Any]) -> TripNote:
    _require(data, {"body", "public_consent"})
    for field, value in data.items():
        setattr(note, field, value)
    _save(note)
    return note


# --- GPS tracks ------------------------------------------------------------------------------

MAX_TRACK = dt.timedelta(days=366)


def _track_range(start: dt.datetime | None, end: dt.datetime | None) -> DateTimeTZRange:
    if start is None or end is None:
        raise invalid("a track needs start_utc and end_utc")
    check_times(start, end)
    if end == start:
        raise invalid("end_utc must be after start_utc")
    if end - start > MAX_TRACK:
        raise invalid("a track spans at most 366 days")
    return DateTimeTZRange(start, end, "[)")


def add_track(user, trip: Trip, data: dict[str, Any]) -> TrackContribution:
    """A time range of the author's own raw points (§5.3: trips reference raw data, never copy
    it). The geometry is built later from those points (map matching, T22)."""
    track = TrackContribution(
        trip=trip,
        author_id=user.pk,
        time_range=_track_range(data.get("start_utc"), data.get("end_utc")),
        public_consent=bool(data.get("public_consent") or False),
    )
    _save(track)
    return track


def update_track(track: TrackContribution, data: dict[str, Any]) -> TrackContribution:
    _require(data, {"public_consent"})
    if "start_utc" in data or "end_utc" in data:
        if track.route_id is not None:
            # Its route was built from the old range; saved routes are never recomputed (rule 5).
            raise TripError(409, "this track already has a route; delete it and add a new one")
        start = data.get("start_utc", track.time_range.lower)
        end = data.get("end_utc", track.time_range.upper)
        track.time_range = _track_range(start, end)
    if "public_consent" in data:
        track.public_consent = data["public_consent"]
    _save(track)
    return track


# --- Stops -----------------------------------------------------------------------------------


def _new_place(user, data: dict[str, Any]) -> Place:
    place = Place(
        owner_id=user.pk,
        name=data.get("name") or "",
        address=data.get("address") or "",
        point=Point(data["lon"], data["lat"], srid=4326),
        source=Place.Source.MANUAL,
    )
    _save(place)
    return place


def _apply_stop(user, stop: Stop, data: dict[str, Any]) -> None:
    _require(data, {"kind"})
    for field in {"kind", "arrive_utc", "depart_utc"} & data.keys():
        setattr(stop, field, data[field])
    if "tz" in data:
        stop.tz = data["tz"] or ""
    check_zone(stop.tz)
    if stop.arrive_utc and stop.depart_utc and stop.depart_utc < stop.arrive_utc:
        raise invalid("depart_utc is before arrive_utc")
    if "leg_id" in data:
        leg = None
        if data["leg_id"] is not None:
            leg = Leg.objects.filter(pk=data["leg_id"], trip_id=stop.trip_id).first()
            if leg is None:
                raise invalid("unknown leg")
        stop.leg = leg
    if data.get("place_id") is not None and data.get("place") is not None:
        raise invalid("give either place_id or place")
    if data.get("place_id") is not None:
        place = _lookup(Place, data["place_id"], "place")
        if not policy.can_use_place(user, stop.trip, place):
            raise invalid("unknown place")  # someone else's place: same answer as missing
        stop.place = place
    elif data.get("place") is not None:
        stop.place = _new_place(user, data["place"])
    elif stop.place_id is None:
        raise invalid("a stop needs a place_id or a new place")


def create_stop(user, trip: Trip, data: dict[str, Any]) -> Stop:
    stop = Stop(trip=trip, author_id=user.pk)
    with guarded_write():
        _apply_stop(user, stop, data)
        stop.save()
    touch(trip)
    return stop


def update_stop(user, stop: Stop, data: dict[str, Any]) -> Stop:
    with guarded_write():
        _apply_stop(user, stop, data)
        stop.save()
    touch(stop.trip)
    return stop


def delete_stop(stop: Stop) -> None:
    """Legs and photos that pointed at the stop keep going without it (SET NULL)."""
    delete_row(Stop, stop.pk)
    touch(stop.trip)


# --- Photos (metadata only; uploads and files are T31) ---------------------------------------


def update_media(media: Media, data: dict[str, Any]) -> Media:
    _require(data, {"caption", "public_consent"})
    for field in {"caption", "public_consent"} & data.keys():
        setattr(media, field, data[field])
    if "leg_id" in data:
        if (
            data["leg_id"] is not None
            and not Leg.objects.filter(pk=data["leg_id"], trip_id=media.trip_id).exists()
        ):
            raise invalid("unknown leg")
        media.leg_id = data["leg_id"]
    if "stop_id" in data:
        if (
            data["stop_id"] is not None
            and not Stop.objects.filter(pk=data["stop_id"], trip_id=media.trip_id).exists()
        ):
            raise invalid("unknown stop")
        media.stop_id = data["stop_id"]
    _save(media)
    return media


# --- Bulk edit -------------------------------------------------------------------------------


class BulkRefused(TripError):
    """Some trips may not take the change: nothing was written."""

    def __init__(self, refused: list[dict[str, Any]]):
        super().__init__(403, "nothing was changed: some trips can't take this edit")
        self.refused = refused


def _bulk_refusal(user, trip: Trip, data: dict[str, Any], purpose, tags, adds) -> str | None:
    changes_core = (
        "purpose_id" in data
        or data.get("visibility") is not None
        or bool(data.get("add_person_ids"))
        or bool(data.get("remove_person_ids"))
    )
    if changes_core and not policy.can_edit_trip_core(user, trip):
        return "only the trip's owner (or the Admin) can change this"
    if purpose is not None and not policy.can_set_trip_purpose(user, trip, purpose):
        return "the purpose belongs to another user than the trip's owner"
    visibility = data.get("visibility")
    if visibility is not None and not policy.can_set_trip_visibility(user, trip, visibility):
        return "you would no longer see this trip; only its owner can do that"
    if any(not policy.can_add_participant(user, trip, person) for person in adds):
        return "you cannot add this person"
    if (data.get("add_tag_ids") or data.get("remove_tag_ids")) and not all(
        policy.can_tag_trip(user, trip, tag) for tag in tags
    ):
        return "only the trip's owner and participants (Members) can tag it"
    return None


def bulk_edit(user, trips: list[Trip], data: dict[str, Any]) -> None:
    """Purpose, visibility, participants and the user's own tags for many trips at once
    (§17 `POST /trips/bulk`). All or nothing: if any trip may not take the change, nothing is
    written and every refused trip is listed. Adding something already there, or removing
    something absent, is not an error."""
    purpose = None
    if data.get("purpose_id") is not None:
        purpose = _lookup(Purpose, data["purpose_id"], "purpose")
    tag_ids = set(data.get("add_tag_ids") or []) | set(data.get("remove_tag_ids") or [])
    tags = {t.pk: t for t in Tag.objects.filter(pk__in=tag_ids, owner_id=user.pk)}
    if set(tags) != tag_ids:
        raise invalid("unknown tag")
    adds = [visible_person(user, pid) for pid in dict.fromkeys(data.get("add_person_ids") or [])]
    removes = [
        visible_person(user, pid) for pid in dict.fromkeys(data.get("remove_person_ids") or [])
    ]
    refused = []
    for trip in trips:
        reason = _bulk_refusal(user, trip, data, purpose, list(tags.values()), adds)
        if reason:
            refused.append({"trip_id": trip.pk, "reason": reason})
    if refused:
        raise BulkRefused(refused)
    core = {k: data[k] for k in ("purpose_id", "visibility") if k in data}
    if data.get("visibility") is None:
        core.pop("visibility", None)
    with transaction.atomic():  # one savepoint for all trips: a refusal undoes every change
        for trip in trips:
            try:
                _bulk_apply(user, trip, data, core, adds, removes, tags)
            except TripError as error:
                raise TripError(error.status, f"trip {trip.pk}: {error.message}") from None


def _bulk_apply(user, trip, data, core, adds, removes, tags) -> None:
    if core:
        update_trip(user, trip, dict(core))
    on_trip = set(TripParticipant.objects.filter(trip=trip).values_list("person_id", flat=True))
    for person in adds:
        if person.pk not in on_trip:
            add_participant(user, trip, person)
    for person in removes:
        remove_participant_if_present(trip, person)
    tagged = set(TripTag.objects.filter(trip=trip).values_list("tag_id", flat=True))
    for tag_id in data.get("add_tag_ids") or []:
        if tag_id not in tagged:
            tag_trip(user, trip, tags[tag_id])
    for tag_id in data.get("remove_tag_ids") or []:
        with guarded_write():
            TripTag.objects.filter(trip=trip, tag_id=tag_id, author_id=user.pk).delete()
