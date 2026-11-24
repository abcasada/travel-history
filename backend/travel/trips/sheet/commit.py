"""Committing parsed tabs (§28.8 step 4, §28.9): one savepoint per tab, as the caller under RLS,
through travel.trips.services with the API's policy checks. Never deletes by absence (rule 6):
stops and legs missing from the sheet are kept unless the user ticked "also remove these" for
that trip (Q-19). Never changes a trip edited in the app (rule 7): it gets a review flag."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from django.contrib.gis.geos import Point
from django.db import connection, transaction
from django.utils import timezone

from travel.accounts.models import Person
from travel.core import policy
from travel.history.models import ImportBatch

from .. import services
from ..models import (
    Leg,
    Place,
    ReviewFlag,
    Stop,
    Trip,
    TripParticipant,
    TripSheetLink,
    TripSheetRecord,
    TripTag,
)
from ..services import TripError, guarded_write
from . import plan as p

Outcome = TripSheetRecord.Outcome


class CommitError(Exception):
    def __init__(self, status: int, message: str, details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}


@dataclass
class Options:
    records: list[int] | None = None  # None: every importable tab
    seen: dict[int, dt.datetime | None] | None = None  # trip.updated_at the preview showed
    create_people: set[int] = field(default_factory=set)  # record ids (Q-20)
    recreate: set[int] = field(default_factory=set)  # record ids whose deleted trip comes back
    remove_missing: set[int] = field(default_factory=set)  # record ids (Q-19)


@dataclass
class TabResult:
    record_id: int
    tab: str
    outcome: str
    trip_id: int | None = None
    message: str = ""


def _lock(user_id: int) -> None:
    """One commit per user at a time, so two previews can't both create a trip for a key."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('trip_sheet_commit:' || %s, 0))",
            [user_id],
        )


def same_instant(seen: dt.datetime | None, current: dt.datetime | None) -> bool:
    """The API's JSON carries milliseconds (Django's encoder), the database microseconds."""
    if seen is None or current is None:
        return seen is None and current is None
    return abs(seen - current) < dt.timedelta(milliseconds=1)


def commit_batch(user, batch: ImportBatch, options: Options) -> list[TabResult]:
    """Apply the chosen tabs. Raises CommitError (409) before writing anything if a target trip
    changed since the preview, (422) for a blocked or unknown tab, (409) for a batch that is no
    longer in preview."""
    if not policy.can_commit_trip_sheet(user, batch):
        raise CommitError(404, "import not found")
    if batch.status != ImportBatch.Status.PREVIEW:
        raise CommitError(409, f"this import is {batch.status}, not waiting for a commit")
    _lock(user.pk)
    records = list(TripSheetRecord.objects.filter(import_batch=batch).order_by("position"))
    by_id = {r.pk: r for r in records}
    wanted = options.records
    if wanted is not None:
        unknown = [rid for rid in wanted if rid not in by_id]
        if unknown:
            raise CommitError(422, "unknown tab", {"records": unknown})
    plans = []
    for record in records:
        if wanted is not None and record.pk not in wanted:
            continue
        if record.outcome:
            continue  # already committed
        plan = p.plan_record(user, record, create_people=record.pk in options.create_people)
        if plan.outcome == p.BLOCKED:
            if wanted is not None:
                raise CommitError(
                    422, f"tab {record.tab_name!r} has problems", {"records": [record.pk]}
                )
            continue
        plans.append(plan)
    if options.seen is not None:
        stale = [
            plan.record.pk
            for plan in plans
            if plan.record.pk in options.seen
            and not same_instant(options.seen[plan.record.pk], plan.trip_updated_at)
        ]
        if stale:
            raise CommitError(
                409, "a trip changed since the preview; preview again", {"records": stale}
            )
    results = []
    for plan in plans:
        with transaction.atomic():
            results.append(apply(user, batch, plan, options))
    _finish(batch, results)
    return results


def _finish(batch: ImportBatch, results: list[TabResult]) -> None:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
    summary = {
        **batch.summary,
        "committed": counts,
        "committed_at": timezone.now().isoformat(),
    }
    ImportBatch.objects.filter(pk=batch.pk).update(
        status=ImportBatch.Status.DONE, summary=summary, finished_at=timezone.now()
    )


def discard_batch(user, batch: ImportBatch) -> None:
    if not policy.can_commit_trip_sheet(user, batch):
        raise CommitError(404, "import not found")
    if batch.status != ImportBatch.Status.PREVIEW:
        raise CommitError(409, f"this import is {batch.status}, not waiting for a commit")
    ImportBatch.objects.filter(pk=batch.pk).update(
        status=ImportBatch.Status.DISCARDED, finished_at=timezone.now()
    )


# --- One tab ----------------------------------------------------------------------------------


def _mark(record: TripSheetRecord, outcome: str, trip: Trip | None) -> None:
    TripSheetRecord.objects.filter(pk=record.pk).update(
        outcome=outcome, trip=trip, committed_at=timezone.now()
    )


def _link(user, record: TripSheetRecord, link: TripSheetLink | None, trip: Trip) -> None:
    now = timezone.now()
    values = {
        "trip": trip,
        "last_record": record,
        "applied_hash": record.content_hash,
        "applied_at": now,
    }
    with guarded_write():
        if link is None:
            TripSheetLink.objects.create(owner_id=user.pk, key=record.key, **values)
        else:
            TripSheetLink.objects.filter(pk=link.pk).update(**values, updated_at=now)


def apply(user, batch: ImportBatch, plan: p.TabPlan, options: Options) -> TabResult:
    record = plan.record
    result = TabResult(record.pk, record.tab_name, plan.outcome)
    try:
        if plan.outcome == p.NEW or (plan.outcome == p.DELETED and record.pk in options.recreate):
            trip = Writer(user, batch, record, options).create()
            _link(user, record, plan.link, trip)
            _mark(record, Outcome.CREATED, trip)
            result.outcome, result.trip_id = Outcome.CREATED, trip.pk
        elif plan.outcome == p.UPDATE:
            Writer(user, batch, record, options).update(plan.trip)
            _link(user, record, plan.link, plan.trip)
            _mark(record, Outcome.UPDATED, plan.trip)
            result.outcome, result.trip_id = Outcome.UPDATED, plan.trip.pk
        elif plan.outcome == p.IDENTICAL:
            _mark(record, Outcome.IDENTICAL, plan.trip)
            result.outcome, result.trip_id = Outcome.IDENTICAL, plan.trip.pk
        elif plan.outcome == p.REVIEW:
            flag_for_review(batch, plan)
            _mark(record, Outcome.REVIEW, plan.trip)
            result.outcome, result.trip_id = Outcome.REVIEW, plan.trip.pk
            result.message = "edited in the app since the last import: sent to review"
        else:  # deleted (not re-created) or transferred
            _mark(record, Outcome.SKIPPED, None)
            result.outcome = Outcome.SKIPPED
            result.message = (
                "deleted in the app" if plan.outcome == p.DELETED else "no longer your trip"
            )
    except TripError as error:
        raise CommitError(error.status, f"tab {record.tab_name!r}: {error.message}") from None
    return result


def flag_for_review(batch: ImportBatch, plan: p.TabPlan) -> None:
    """Rule 7: one open `source_changed` flag per trip and content hash holds the batch, the
    record and the diff; resolving it may apply the sheet version later."""
    trip, record = plan.trip, plan.record
    if ReviewFlag.objects.filter(
        trip=trip,
        reason=ReviewFlag.Reason.SOURCE_CHANGED,
        resolved_at__isnull=True,
        details__content_hash=record.content_hash,
    ).exists():
        return
    with guarded_write():
        ReviewFlag.objects.create(
            trip=trip,
            reason=ReviewFlag.Reason.SOURCE_CHANGED,
            details={
                "source": "trip_sheet",
                "import_batch_id": batch.pk,
                "record_id": record.pk,
                "content_hash": record.content_hash,
                "diff": plan.diff,
            },
        )
        # A plain UPDATE (no auto_now): the flag is not an edit of the trip.
        Trip.objects.filter(pk=trip.pk).update(needs_review=True)


class Writer:
    """Writes one tab's content into a trip, as the caller, without marking it edited in the
    app (`in_app=False`)."""

    def __init__(self, user, batch: ImportBatch, record: TripSheetRecord, options: Options):
        self.user = user
        self.batch = batch
        self.record = record
        self.content = record.content
        self.create_people = record.pk in options.create_people
        self.remove_missing = record.pk in options.remove_missing
        self.people: dict[str, Person] = {}

    # --- trip ---------------------------------------------------------------------------------

    def create(self) -> Trip:
        if not policy.can_create(self.user):
            raise TripError(403, "your role cannot import trips")
        sheet = self.content["trip"]
        data = {
            "title": sheet.get("title") or sheet["default_title"],
            "start_date": dt.date.fromisoformat(sheet["start_date"]),
            "end_date": dt.date.fromisoformat(sheet["end_date"]),
            "date_precision": sheet.get("date_precision") or "day",
            "notes": sheet.get("notes") or "",
            "purpose_id": sheet.get("purpose_id"),
            "visibility": sheet.get("visibility"),
        }
        trip = services.create_trip(self.user, data, source=Trip.Source.SHEET_IMPORT, in_app=False)
        self.add_people(trip)
        self.add_tags(trip)
        stops = {s["sheet_key"]: self.new_stop(trip, s) for s in self.content["stops"]}
        for sheet_leg in self.content["legs"]:
            leg = self.new_leg(trip, sheet_leg, stops)
            self.leg_people(leg, sheet_leg, new=True)
        return trip

    def update(self, trip: Trip) -> None:
        if not policy.can_edit_trip_core(self.user, trip):
            raise TripError(403, "not allowed")
        changes = p.trip_changes(self.content, trip)
        if changes:
            services.update_trip(self.user, trip, changes, in_app=False)
        self.add_people(trip)
        self.add_tags(trip)
        existing = {
            s.sheet_key: s
            for s in Stop.objects.filter(trip=trip).select_related("place")
            if s.sheet_key
        }
        stops: dict[str, Stop] = {}
        for sheet_stop in self.content["stops"]:
            stop = existing.get(sheet_stop["sheet_key"])
            if stop is None:
                stops[sheet_stop["sheet_key"]] = self.new_stop(trip, sheet_stop)
            else:
                stops[sheet_stop["sheet_key"]] = self.update_stop(trip, stop, sheet_stop)
        core = {
            leg.sheet_key: leg
            for leg in Leg.objects.filter(trip=trip, is_contribution=False)
            if leg.sheet_key
        }
        sheet_legs: list[Leg] = []
        for sheet_leg in self.content["legs"]:
            leg = core.get(sheet_leg["sheet_key"])
            if leg is None:
                leg = self.new_leg(trip, sheet_leg, stops)
                self.leg_people(leg, sheet_leg, new=True)
            else:
                self.update_leg(leg, sheet_leg, stops)
                self.leg_people(leg, sheet_leg, new=False)
            sheet_legs.append(leg)
        if self.remove_missing:
            self.remove_missing_rows(trip, set(stops.values()), sheet_legs)
        self.reorder(trip, sheet_legs)

    def add_people(self, trip: Trip) -> None:
        """People are only added, never removed (§28.9)."""
        on_trip = set(TripParticipant.objects.filter(trip=trip).values_list("person_id", flat=True))
        for entry in self.content["trip"].get("people") or []:
            person = self.person(entry)
            if person.pk in on_trip:
                continue
            if not policy.can_add_participant(self.user, trip, person):
                raise TripError(403, f"you cannot add {entry['name']!r} to the trip")
            services.add_participant(self.user, trip, person, in_app=False)
            on_trip.add(person.pk)

    def person(self, entry: dict) -> Person:
        name = entry["name"]
        if name.casefold() in self.people:
            return self.people[name.casefold()]
        person = None
        if entry.get("person_id"):
            person = Person.objects.filter(pk=entry["person_id"]).first()
            if person is None or not policy.can_view_person(self.user, person):
                raise TripError(422, f"unknown person {name!r}")
        else:
            if not self.create_people or not policy.can_create_person(self.user):
                raise TripError(422, f"unknown person {name!r}")
            # Q-20: only names the preview listed, and only when the user ticked the option.
            if name not in self.content.get("unknown_people", []):
                raise TripError(422, f"unknown person {name!r}")
            with guarded_write():
                person = Person.objects.create(display_name=name[:150], created_by_id=self.user.pk)
        self.people[name.casefold()] = person
        return person

    def add_tags(self, trip: Trip) -> None:
        """The caller's own tags, created when new; tags already on the trip stay (§28.9)."""
        tagged = set(TripTag.objects.filter(trip=trip).values_list("tag_id", flat=True))
        for name in self.content["trip"].get("tags") or []:
            tag = services.own_tag(self.user, name=name)
            if tag.pk in tagged:
                continue
            if not policy.can_tag_trip(self.user, trip, tag):
                raise TripError(403, "you cannot tag this trip")
            services.tag_trip(self.user, trip, tag)
            tagged.add(tag.pk)

    # --- stops --------------------------------------------------------------------------------

    def place(self, trip: Trip, sheet_stop: dict) -> Place:
        """The caller's own place with the same GeoNames id (or the same coordinates) and the
        same name, else a new one (§28.4)."""
        sheet = sheet_stop["place"]
        name = sheet_stop.get("name") or sheet.get("name") or ""
        candidates = Place.objects.filter(owner_id=self.user.pk, name=name)
        if sheet.get("geonames_id"):
            candidates = candidates.filter(geonames_id=sheet["geonames_id"])
        for place in candidates.order_by("pk"):
            if p.same_place(place, sheet) and policy.can_use_place(self.user, trip, place):
                return place
        place = Place(
            owner_id=self.user.pk,
            name=name[:200],
            point=Point(sheet["lon"], sheet["lat"], srid=4326),
            geonames_id=sheet.get("geonames_id"),
            country_code=(sheet.get("country_code") or "")[:2],
            admin1_code=(sheet.get("admin1_code") or "")[:16],
            source=Place.Source.MANUAL,
        )
        with guarded_write():
            place.save()
        return place

    def stop_data(self, sheet: dict, *, full: bool) -> dict:
        data: dict = {}
        if full or sheet.get("kind") is not None:
            data["kind"] = sheet.get("kind") or Stop.Kind.DESTINATION
        if full or sheet.get("times_given") or sheet.get("tz_given"):
            data["tz"] = sheet.get("tz") or ""
        if full or sheet.get("times_given"):
            for name in ("arrive_utc", "depart_utc"):
                value = p.parse_utc(sheet.get(name))
                if value is not None or full:
                    data[name] = value
            data["time_precision"] = sheet.get("time_precision") or "exact"
        if full or sheet.get("notes") is not None:
            data["notes"] = sheet.get("notes") or ""
        return data

    def new_stop(self, trip: Trip, sheet: dict) -> Stop:
        data = self.stop_data(sheet, full=True)
        data["place_id"] = self.place(trip, sheet).pk
        return services.create_stop(
            self.user,
            trip,
            data,
            in_app=False,
            provenance={"sheet_key": sheet["sheet_key"], "import_batch_id": self.batch.pk},
        )

    def update_stop(self, trip: Trip, stop: Stop, sheet: dict) -> Stop:
        changes = p.stop_changes(stop, sheet)
        if not changes:
            return stop
        data = {k: v for k, v in self.stop_data(sheet, full=False).items() if k in changes}
        if "place" in changes:
            data["place_id"] = self.place(trip, sheet).pk
        return services.update_stop(self.user, stop, data, in_app=False)

    # --- legs ---------------------------------------------------------------------------------

    def leg_data(self, sheet: dict, stops: dict[str, Stop], *, full: bool) -> dict:
        data: dict = {}
        for name in p.LEG_FIELDS:
            if name in ("origin", "destination"):
                key = sheet.get(f"{name}_key")
                if key is not None:
                    data[f"{name}_stop_id"] = stops[key].pk
                continue
            if name in ("start_utc", "end_utc"):
                value = p.parse_utc(sheet.get(name))
            elif name in ("start_tz", "end_tz", "time_precision"):
                if not (full or sheet.get("times_given")):
                    continue
                value = sheet.get(name) or ("exact" if name == "time_precision" else "")
            else:
                value = sheet.get(name)
            if value is None or (value == "" and not full):
                continue
            data[name] = value
        return data

    def new_leg(self, trip: Trip, sheet: dict, stops: dict[str, Stop]) -> Leg:
        return services.create_leg(
            self.user,
            trip,
            "core",
            self.leg_data(sheet, stops, full=True),
            in_app=False,
            provenance={"sheet_key": sheet["sheet_key"], "import_batch_id": self.batch.pk},
        )

    def update_leg(self, leg: Leg, sheet: dict, stops: dict[str, Stop]) -> None:
        stop_keys = {s.pk: key for key, s in stops.items()}
        stop_keys.update(
            {s.pk: s.sheet_key for s in Stop.objects.filter(trip_id=leg.trip_id) if s.sheet_key}
        )
        changes = p.leg_changes(leg, sheet, stop_keys)
        if not changes:
            return
        data = self.leg_data(sheet, stops, full=False)
        wanted = {
            name
            for change in changes
            for name in (
                (f"{change}_stop_id",) if change in ("origin", "destination") else (change,)
            )
        }
        services.update_leg(
            self.user, leg, {k: v for k, v in data.items() if k in wanted}, in_app=False
        )

    def leg_people(self, leg: Leg, sheet: dict, *, new: bool) -> None:
        """Only when the leg's people differ from the trip's: exactly these people on a new leg
        (include/exclude overrides); on an existing leg people are only added."""
        entries = sheet.get("people")
        if entries is None:
            return
        wanted = {self.person(entry).pk: self.person(entry) for entry in entries}
        trip_people = {
            tp.person_id: tp.person
            for tp in TripParticipant.objects.filter(trip_id=leg.trip_id).select_related("person")
        }
        current = services.participation(leg.trip, [leg]).legs[leg.pk]
        for person_id, person in wanted.items():
            if person_id not in current:
                self._set(leg, person, True)
        if new:
            for person_id, person in trip_people.items():
                if person_id not in wanted:
                    self._set(leg, person, False)

    def _set(self, leg: Leg, person: Person, on_leg: bool) -> None:
        if not policy.can_set_leg_participation(self.user, leg, person):
            raise TripError(403, f"you cannot set who was on leg {leg.sequence}")
        services.set_leg_participation(self.user, leg, person, on_leg, in_app=False)

    def remove_missing_rows(self, trip: Trip, kept_stops: set[Stop], sheet_legs: list[Leg]) -> None:
        """Q-19: the user asked, for this trip, to remove the stops and core legs the sheet no
        longer has. Contributed legs are never touched."""
        keep_legs = {leg.pk for leg in sheet_legs}
        for leg in Leg.objects.filter(trip=trip, is_contribution=False).exclude(pk__in=keep_legs):
            services.delete_leg(leg, in_app=False)
        keep = {s.pk for s in kept_stops}
        for stop in Stop.objects.filter(trip=trip).exclude(pk__in=keep):
            services.delete_stop(stop, in_app=False)

    def reorder(self, trip: Trip, sheet_legs: list[Leg]) -> None:
        """Sheet legs take the sheet's order; other legs keep their place by time (before the
        first sheet leg that departs after them), or stay at the end in their order."""
        current = list(Leg.objects.filter(trip=trip).order_by("sequence"))
        sheet_ids = [leg.pk for leg in sheet_legs]
        order = list(sheet_ids)
        starts = {leg.pk: leg.start_utc for leg in current}
        for leg in current:
            if leg.pk in sheet_ids:
                continue
            position = len(order)
            if leg.start_utc is not None:
                for index, other in enumerate(order):
                    other_start = starts.get(other)
                    if other_start is not None and other_start > leg.start_utc:
                        position = index
                        break
            order.insert(position, leg.pk)
        if order != [leg.pk for leg in current]:
            services.reorder_legs(trip, order, in_app=False)
