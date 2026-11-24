"""Trip spreadsheet preview, commit and discard (§28.8), and the template download.

Imports are raw history: only their owner sees a batch (RLS hides the rest, and
`policy.can_commit_trip_sheet` agrees), never the Admin. Uploads use the chunked upload API with
kind `trip_sheet` (travel/history/api.py)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from django.shortcuts import get_object_or_404
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from travel.core import policy
from travel.history.models import ImportBatch

from ..models import TripSheetRecord
from . import plan as p
from .commit import CommitError, Options, commit_batch, discard_batch

router = Router(tags=["imports"])

TEMPLATE = Path(__file__).resolve().parent / "trip-template.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TEMPLATE_DOC = {
    "responses": {200: {"description": "The trip spreadsheet template", "content": {XLSX: {}}}}
}

Scalar = str | int | float | bool | None


class SheetIssueOut(Schema):
    tab: str
    row: int | None
    column: str
    header: str
    field: str
    severity: str
    reason: str
    message: str
    hint: str
    candidates: list[str]


class SheetFieldChangeOut(Schema):
    field: str
    old: Scalar
    new: Scalar


class SheetRowOut(Schema):
    row: int | None = None
    name: str
    mode: str | None = None
    stop_id: int | None = None
    leg_id: int | None = None
    changes: list[SheetFieldChangeOut] = []


class SheetPartDiffOut(Schema):
    added: list[SheetRowOut]
    changed: list[SheetRowOut]
    kept: list[SheetRowOut]


class SheetDiffOut(Schema):
    trip: list[SheetFieldChangeOut]
    people_added: list[str]
    tags_added: list[str]
    stops: SheetPartDiffOut
    legs: SheetPartDiffOut


class SheetMapStopOut(Schema):
    row: int
    name: str
    kind: str | None
    lon: float
    lat: float


class SheetMapLegOut(Schema):
    row: int
    name: str
    mode: str | None
    origin: list[float] | None
    destination: list[float] | None


class SheetTabOut(Schema):
    record_id: int
    tab: str
    position: int
    key: str
    title: str
    outcome: str
    committed: str
    can_commit: bool
    issues: list[SheetIssueOut]
    unknown_people: list[str]
    new_tags: list[str]
    trip_id: int | None
    trip_updated_at: dt.datetime | None
    last_imported_at: dt.datetime | None
    diff: SheetDiffOut | None
    stops: list[SheetMapStopOut]
    legs: list[SheetMapLegOut]


class TripSheetPreviewOut(Schema):
    batch_id: int
    status: str
    original_name: str | None
    can_commit: bool
    workbook_issues: list[SheetIssueOut]
    tabs: list[SheetTabOut]


class SeenIn(Schema):
    record_id: int
    trip_updated_at: dt.datetime | None


class TripSheetCommitIn(Schema):
    records: list[int] | None = None
    seen: list[SeenIn] | None = None
    create_people: list[int] = []
    recreate: list[int] = []
    remove_missing: list[int] = []


class SheetTabResultOut(Schema):
    record_id: int
    tab: str
    outcome: str
    trip_id: int | None
    message: str


class TripSheetCommitOut(Schema):
    batch_id: int
    status: str
    results: list[SheetTabResultOut]


class SheetConflictOut(Schema):
    detail: str
    records: list[int]


def _batch(request, batch_id: int) -> ImportBatch:
    batch = get_object_or_404(
        ImportBatch.objects.select_related("raw_file"),
        pk=batch_id,
        owner=request.user,
        kind=ImportBatch.Kind.TRIP_SHEET,
    )
    if not policy.can_commit_trip_sheet(request.user, batch):
        raise HttpError(403, "your role cannot import data")
    return batch


def _workbook_issue(issue: dict) -> dict:
    return {
        "tab": "",
        "row": None,
        "column": "",
        "header": "",
        "field": "",
        "hint": "",
        "candidates": [],
        **issue,
    }


def _tab(record: TripSheetRecord, plan: p.TabPlan | None, batch_open: bool) -> dict:
    content = record.content
    trip = content.get("trip", {})
    issues = sorted(record.issues, key=lambda i: (i.get("row") is not None, i.get("row") or 0))
    if record.outcome:
        outcome = {"created": p.NEW, "updated": p.UPDATE}.get(record.outcome, record.outcome)
    else:
        outcome = plan.outcome if plan else p.BLOCKED if record.blocked else "not_committed"
    return {
        "record_id": record.pk,
        "tab": record.tab_name,
        "position": record.position,
        "key": record.key,
        "title": trip.get("title") or trip.get("default_title") or record.tab_name,
        "outcome": outcome,
        "committed": record.outcome,
        "can_commit": batch_open
        and not record.outcome
        and plan is not None
        and plan.outcome != p.BLOCKED,
        "issues": issues,
        "unknown_people": content.get("unknown_people", []),
        "new_tags": trip.get("new_tags", []),
        "trip_id": plan.trip.pk if plan and plan.trip else record.trip_id,
        "trip_updated_at": plan.trip_updated_at if plan else None,
        "last_imported_at": plan.link.applied_at if plan and plan.link else None,
        "diff": plan.diff if plan and plan.diff else None,
        "stops": [
            {
                "row": s["row"],
                "name": s["display_name"],
                "kind": s.get("kind"),
                "lon": s["place"]["lon"],
                "lat": s["place"]["lat"],
            }
            for s in content.get("stops", [])
            if s.get("place")
        ],
        "legs": [
            {
                "row": leg["row"],
                "name": f"{leg['origin_label'] or '?'} → {leg['destination_label'] or '?'}",
                "mode": leg.get("mode"),
                "origin": leg.get("origin_point"),
                "destination": leg.get("destination_point"),
            }
            for leg in content.get("legs", [])
        ],
    }


@router.get(
    "/imports/{batch_id}/trip-sheet",
    response=TripSheetPreviewOut,
    operation_id="getTripSheetPreview",
)
def trip_sheet_preview(request, batch_id: int):
    """Per tab: its outcome (`new`, `update`, `identical`, `review` (edited in the app),
    `deleted` or `transferred` (skipped), `blocked` by problems), its issues, and the diff
    against the trip. `trip_updated_at` goes back in the commit's `seen` (409 if the trip
    changed meanwhile). A tab blocked only by unknown people becomes importable when the commit
    lists it in `create_people`."""
    batch = _batch(request, batch_id)
    batch_open = batch.status == ImportBatch.Status.PREVIEW
    tabs = []
    for record in TripSheetRecord.objects.filter(import_batch=batch).order_by("position"):
        plan = p.plan_record(request.user, record) if batch_open and not record.outcome else None
        tabs.append(_tab(record, plan, batch_open))
    return {
        "batch_id": batch.pk,
        "status": batch.status,
        "original_name": batch.raw_file.original_name if batch.raw_file_id else None,
        "can_commit": batch_open and any(t["can_commit"] for t in tabs),
        "workbook_issues": [_workbook_issue(i) for i in batch.summary.get("workbook_issues", [])],
        "tabs": tabs,
    }


@router.post(
    "/imports/{batch_id}/commit",
    response={200: TripSheetCommitOut, 409: SheetConflictOut, 422: SheetConflictOut},
    operation_id="commitTripSheet",
)
def commit_trip_sheet(request, batch_id: int, payload: TripSheetCommitIn):
    """Apply the chosen tabs (default: every importable one), one transaction per tab, as the
    caller. Lists in `create_people`, `recreate` and `remove_missing` are record ids: create
    the unknown people the preview listed (Q-20), bring back a trip deleted in the app, remove
    the stops and legs the sheet no longer has (Q-19). The batch is then `done`."""
    batch = _batch(request, batch_id)
    options = Options(
        records=payload.records,
        seen=(
            {s.record_id: s.trip_updated_at for s in payload.seen}
            if payload.seen is not None
            else None
        ),
        create_people=set(payload.create_people),
        recreate=set(payload.recreate),
        remove_missing=set(payload.remove_missing),
    )
    try:
        results = commit_batch(request.user, batch, options)
    except CommitError as error:
        if error.status in (409, 422) and "records" in error.details:
            return Status(error.status, {"detail": error.message, **error.details})
        raise HttpError(error.status, error.message) from None
    batch.refresh_from_db()
    return {
        "batch_id": batch.pk,
        "status": batch.status,
        "results": [r.__dict__ for r in results],
    }


@router.post(
    "/imports/{batch_id}/discard",
    response={204: None},
    operation_id="discardTripSheet",
)
def discard_trip_sheet(request, batch_id: int):
    """End the import without writing trips; the raw file stays archived."""
    batch = _batch(request, batch_id)
    try:
        discard_batch(request.user, batch)
    except CommitError as error:
        raise HttpError(error.status, error.message) from None
    return Status(204, None)
