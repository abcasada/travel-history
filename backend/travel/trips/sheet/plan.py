"""What committing a parsed tab would do (§28.8, §28.9): its outcome against the caller's own
trips and the diff (trip fields old -> new, stops and legs added, changed field by field, and
kept-not-in-sheet). Runs as the caller under RLS; never writes."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from travel.core import policy

from ..models import (
    Leg,
    Place,
    Route,
    Stop,
    Trip,
    TripParticipant,
    TripSheetLink,
    TripSheetRecord,
    TripTag,
)

NEW = "new"
UPDATE = "update"
IDENTICAL = "identical"
REVIEW = "review"
DELETED = "deleted"  # skipped: the trip was deleted in the app
TRANSFERRED = "transferred"  # skipped: the trip belongs to someone else now
BLOCKED = "blocked"
IMPORTABLE = {NEW, UPDATE, IDENTICAL, REVIEW, DELETED, TRANSFERRED}

TRIP_FIELDS = (
    "title",
    "start_date",
    "end_date",
    "date_precision",
    "purpose_id",
    "visibility",
    "notes",
)
STOP_FIELDS = ("place", "kind", "arrive_utc", "depart_utc", "tz", "time_precision", "notes")
LEG_FIELDS = (
    "mode",
    "origin",
    "destination",
    "start_utc",
    "end_utc",
    "start_tz",
    "end_tz",
    "time_precision",
    "origin_label",
    "destination_label",
    "origin_airport_id",
    "destination_airport_id",
    "airline_id",
    "flight_number",
    "aircraft_type_id",
    "aircraft_registration",
    "seat",
    "cabin_class",
    "vehicle_id",
    "notes",
)


def problems(record: TripSheetRecord, *, create_people: bool = False) -> list[dict]:
    """The issues that block the tab. Unknown people block it unless the user ticked 'create
    these people' for this tab (Q-20)."""
    found = [i for i in record.issues if i.get("severity") == "problem"]
    if create_people:
        found = [i for i in found if not (i["reason"] == "unknown_person" and i.get("candidates"))]
    return found


def parse_utc(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


def json_value(value):
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return value


def edited_since(trip: Trip, applied_at: dt.datetime | None) -> bool:
    """Edited in the app since the last import: the in-app edit stamp, or a saved route
    version on one of its legs (rule 7)."""
    if applied_at is None:
        return True
    if trip.edited_in_app_at is not None and trip.edited_in_app_at > applied_at:
        return True
    return Route.objects.filter(leg__trip=trip, produced_at__gt=applied_at).exists()


@dataclass
class TabPlan:
    record: TripSheetRecord
    outcome: str
    link: TripSheetLink | None = None
    trip: Trip | None = None
    diff: dict = field(default_factory=dict)
    blocking: list[dict] = field(default_factory=list)

    @property
    def trip_updated_at(self) -> dt.datetime | None:
        return self.trip.updated_at if self.trip is not None else None


def plan_record(user, record: TripSheetRecord, *, create_people: bool = False) -> TabPlan:
    plan = TabPlan(record=record, outcome=NEW)
    plan.link = TripSheetLink.objects.filter(owner_id=user.pk, key=record.key).first()
    if plan.link is not None and plan.link.trip_id is not None:
        trip = Trip.objects.filter(pk=plan.link.trip_id).first()
        if trip is not None and policy.can_reimport_trip(user, trip):
            plan.trip = trip
    plan.blocking = problems(record, create_people=create_people)
    if plan.blocking:
        plan.outcome = BLOCKED
    elif plan.link is None:
        plan.outcome = NEW
    elif plan.link.trip_id is None:
        plan.outcome = DELETED
    elif plan.trip is None:
        plan.outcome = TRANSFERRED  # hidden from the caller, or owned by someone else now
    elif record.content_hash == plan.link.applied_hash:
        plan.outcome = IDENTICAL
    elif edited_since(plan.trip, plan.link.applied_at):
        plan.outcome = REVIEW
    else:
        plan.outcome = UPDATE
    if plan.trip is not None and plan.outcome in {UPDATE, REVIEW, BLOCKED}:
        plan.diff = diff(record.content, plan.trip)
    elif plan.outcome in {NEW, DELETED} or (plan.outcome == BLOCKED and plan.trip is None):
        plan.diff = new_trip_diff(record.content)
    return plan


# --- Diff ------------------------------------------------------------------------------------


def new_trip_diff(content: dict) -> dict:
    return {
        "trip": [],
        "people_added": [p["name"] for p in content["trip"].get("people") or []],
        "tags_added": list(content["trip"].get("tags") or []),
        "stops": {"added": [_stop_ref(s) for s in content["stops"]], "changed": [], "kept": []},
        "legs": {"added": [_leg_ref(leg) for leg in content["legs"]], "changed": [], "kept": []},
    }


def _stop_ref(stop: dict) -> dict:
    return {"row": stop["row"], "name": stop["display_name"], "sheet_key": stop["sheet_key"]}


def _leg_ref(leg: dict) -> dict:
    return {
        "row": leg["row"],
        "name": f"{leg['origin_label'] or '?'} → {leg['destination_label'] or '?'}",
        "mode": leg["mode"],
        "sheet_key": leg["sheet_key"],
    }


def trip_changes(content: dict, trip: Trip) -> dict:
    """Trip fields the sheet gives that differ (blank = not given). Dates the sheet doesn't give
    only widen the trip to cover its stops and legs."""
    sheet = content["trip"]
    wanted = {
        "title": sheet.get("title"),
        "purpose_id": sheet.get("purpose_id"),
        "visibility": sheet.get("visibility"),
        "notes": sheet.get("notes"),
    }
    start = dt.date.fromisoformat(sheet["start_date"]) if sheet.get("start_date") else None
    end = dt.date.fromisoformat(sheet["end_date"]) if sheet.get("end_date") else None
    if sheet.get("dates_given"):
        wanted.update(start_date=start, end_date=end, date_precision=sheet.get("date_precision"))
    else:
        if start and start < trip.start_date:
            wanted["start_date"] = start
        if end and end > trip.end_date:
            wanted["end_date"] = end
    return {
        name: value
        for name, value in wanted.items()
        if value is not None and getattr(trip, name) != value
    }


def same_place(place: Place | None, sheet: dict | None) -> bool:
    if place is None or sheet is None:
        return place is None and sheet is None
    if sheet.get("geonames_id"):
        return place.geonames_id == sheet["geonames_id"]
    return abs(place.point.y - sheet["lat"]) < 1e-5 and abs(place.point.x - sheet["lon"]) < 1e-5


def stop_changes(stop: Stop, sheet: dict) -> dict:
    """Field -> (old, new) for what the sheet gives and the stop has differently. Times and
    their zone travel together: the UTC values were computed in that zone."""
    changes: dict = {}
    # A stop's name is its place's name; another name means another place (a place can be on
    # several stops, so it is never renamed).
    renamed = sheet.get("name") is not None and stop.place.name != sheet["name"]
    if renamed or not same_place(stop.place, sheet["place"]):
        changes["place"] = (stop.place.name, sheet["display_name"])
    if sheet.get("kind") is not None and stop.kind != sheet["kind"]:
        changes["kind"] = (stop.kind, sheet["kind"])
    if sheet.get("times_given"):
        for name in ("arrive_utc", "depart_utc"):
            new = parse_utc(sheet.get(name))
            if new is not None and getattr(stop, name) != new:
                changes[name] = (getattr(stop, name), new)
        if sheet.get("tz") and stop.tz != sheet["tz"]:
            changes["tz"] = (stop.tz, sheet["tz"])
        if stop.time_precision != sheet["time_precision"]:
            changes["time_precision"] = (stop.time_precision, sheet["time_precision"])
    elif sheet.get("tz_given") and stop.tz != sheet["tz_given"]:
        changes["tz"] = (stop.tz, sheet["tz_given"])
    if sheet.get("notes") is not None and stop.notes != sheet["notes"]:
        changes["notes"] = (stop.notes, sheet["notes"])
    return changes


def leg_changes(leg: Leg, sheet: dict, stop_keys: dict[int, str]) -> dict:
    changes: dict = {}
    for name in LEG_FIELDS:
        if name in ("origin", "destination"):
            key = sheet.get(f"{name}_key")
            current = stop_keys.get(getattr(leg, f"{name}_stop_id"))
            if key is not None and key != current:
                changes[name] = (current, key)
            continue
        if name in ("start_utc", "end_utc"):
            new = parse_utc(sheet.get(name))
        elif name in ("start_tz", "end_tz", "time_precision"):
            if not sheet.get("times_given"):
                continue
            new = sheet.get(name) or None
        else:
            new = sheet.get(name)
        if new is not None and new != "" and getattr(leg, name) != new:
            changes[name] = (getattr(leg, name), new)
    return changes


def _changes_out(changes: dict) -> list[dict]:
    return [
        {"field": name, "old": json_value(old), "new": json_value(new)}
        for name, (old, new) in changes.items()
    ]


def diff(content: dict, trip: Trip) -> dict:
    stops = list(Stop.objects.filter(trip=trip).select_related("place").order_by("pk"))
    legs = list(Leg.objects.filter(trip=trip).order_by("sequence"))
    stop_keys = {s.pk: s.sheet_key for s in stops if s.sheet_key}
    by_key = {s.sheet_key: s for s in stops if s.sheet_key}
    out_stops: dict = {"added": [], "changed": [], "kept": []}
    matched: set[int] = set()
    for sheet in content["stops"]:
        stop = by_key.get(sheet["sheet_key"])
        if stop is None:
            out_stops["added"].append(_stop_ref(sheet))
            continue
        matched.add(stop.pk)
        changes = stop_changes(stop, sheet)
        if changes:
            out_stops["changed"].append(
                {**_stop_ref(sheet), "stop_id": stop.pk, "changes": _changes_out(changes)}
            )
    out_stops["kept"] = [
        {"stop_id": s.pk, "name": s.place.name or f"stop {s.pk}"}
        for s in stops
        if s.pk not in matched
    ]
    core = [leg for leg in legs if not leg.is_contribution]
    legs_by_key = {leg.sheet_key: leg for leg in core if leg.sheet_key}
    out_legs: dict = {"added": [], "changed": [], "kept": []}
    matched = set()
    for sheet in content["legs"]:
        leg = legs_by_key.get(sheet["sheet_key"])
        if leg is None:
            out_legs["added"].append(_leg_ref(sheet))
            continue
        matched.add(leg.pk)
        changes = leg_changes(leg, sheet, stop_keys)
        if changes:
            out_legs["changed"].append(
                {**_leg_ref(sheet), "leg_id": leg.pk, "changes": _changes_out(changes)}
            )
    out_legs["kept"] = [
        {
            "leg_id": leg.pk,
            "name": f"{leg.origin_label or '?'} → {leg.destination_label or '?'}",
            "mode": leg.mode,
        }
        for leg in core
        if leg.pk not in matched
    ]
    on_trip = set(TripParticipant.objects.filter(trip=trip).values_list("person_id", flat=True))
    tagged = {
        name.casefold()
        for name in TripTag.objects.filter(trip=trip, tag__owner_id=trip.owner_id).values_list(
            "tag__name", flat=True
        )
    }
    people = content["trip"].get("people") or []
    old = {name: getattr(trip, name) for name in TRIP_FIELDS}
    return {
        "trip": [
            {"field": name, "old": json_value(old[name]), "new": json_value(value)}
            for name, value in trip_changes(content, trip).items()
        ],
        "people_added": [
            p["name"] for p in people if p["person_id"] is None or p["person_id"] not in on_trip
        ],
        "tags_added": [t for t in content["trip"].get("tags") or [] if t.casefold() not in tagged],
        "stops": out_stops,
        "legs": out_legs,
    }


def has_changes(diff_: dict) -> bool:
    return bool(
        diff_.get("trip")
        or diff_.get("people_added")
        or diff_.get("tags_added")
        or any(
            diff_.get(part, {}).get(k) for part in ("stops", "legs") for k in ("added", "changed")
        )
    )
