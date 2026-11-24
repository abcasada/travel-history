"""The `trip_sheet` import kind (§28.8 step 2): the worker parses the archived workbook into one
own-only `TripSheetRecord` per trip tab and stops at `preview`. Parsing never writes trips; the
user commits from the preview (or the CLI with --commit)."""

from __future__ import annotations

import csv
import io

from django.db import transaction

from travel.accounts.models import User
from travel.core.rls import rls_context
from travel.history import importers, rawstore
from travel.history.models import ImportBatch

from ..models import TripSheetRecord
from .parse import parse_workbook
from .reader import MAX_FILE_BYTES, SheetFileError

REPORT_COLUMNS = ("tab", "row", "column", "severity", "reason", "message", "hint")


def _read(batch: ImportBatch) -> bytes:
    with rawstore.open_original(batch.raw_file) as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise SheetFileError("too_large", "the file is larger than 10 MB")
    return data


def summarize(records: list[TripSheetRecord], workbook_issues: list[dict]) -> dict:
    severities = [issue["severity"] for record in records for issue in record.issues]
    return {
        "tabs": len(records),
        "blocked": sum(1 for record in records if record.blocked),
        "problems": severities.count("problem"),
        "warnings": severities.count("warning"),
        "workbook_issues": workbook_issues,
    }


@importers.register(ImportBatch.Kind.TRIP_SHEET)
def import_trip_sheet(batch: ImportBatch) -> importers.Result:
    owner_id = batch.owner_id
    with rls_context(owner_id):
        existing = list(TripSheetRecord.objects.filter(import_batch_id=batch.pk))
        if existing:  # a retried job: the records were stored already
            return importers.Result(summarize(existing, []), ImportBatch.Status.PREVIEW)
        try:
            data = _read(batch)
            user = User.objects.get(pk=owner_id)
            parsed = parse_workbook(data, user)
        except SheetFileError as error:
            return importers.Result(
                {"reason": error.reason, "message": error.message},
                ImportBatch.Status.FAILED,
                error.message,
            )
        with transaction.atomic():
            records = [
                TripSheetRecord.objects.create(
                    owner_id=owner_id,
                    import_batch_id=batch.pk,
                    tab_name=tab.name[:255],
                    position=tab.position,
                    key=tab.key,
                    content=tab.content,
                    content_hash=tab.content_hash,
                    issues=[issue.as_dict() for issue in tab.issues],
                    blocked=tab.blocked,
                )
                for tab in parsed.tabs
            ]
    return importers.Result(summarize(records, parsed.issues), ImportBatch.Status.PREVIEW)


def report_rows(records: list[TripSheetRecord], workbook_issues: list[dict] = ()) -> list[dict]:
    rows = [{"tab": "", "row": "", "column": "", "hint": "", **issue} for issue in workbook_issues]
    for record in records:
        for issue in sorted(record.issues, key=lambda i: i.get("row") or 0):
            column = issue.get("column") or ""
            if issue.get("header"):
                column = f"{column} ({issue['header']})" if column else issue["header"]
            rows.append({**issue, "column": column})
    return rows


def report_csv(records: list[TripSheetRecord], workbook_issues: list[dict] = ()) -> str:
    """`tab,row,column,severity,reason,message,hint` (§28.7)."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in report_rows(records, workbook_issues):
        writer.writerow({k: "" if row.get(k) is None else row.get(k) for k in REPORT_COLUMNS})
    return out.getvalue()
