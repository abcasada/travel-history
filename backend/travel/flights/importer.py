"""Importer for the flight template (ImportBatch kind `flights_template`, PLAN.md §12.3).

Runs in the worker as the batch owner. Each template row becomes or updates one FlightRecord of
the owner; rows that can't be resolved are kept with their reasons (the unmatched report), so a
later reference-data fix and a re-run resolves them. Re-imports never delete records that are
absent from the newer file (CLAUDE.md rule 6).
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter
from itertools import islice

from django.utils import timezone

from travel.core.rls import rls_context
from travel.history import importers, rawstore
from travel.history.models import ImportBatch

from .models import FlightRecord
from .template import COLUMNS, REQUIRED, ProcessedRow, process_row, row_keys

CHUNK = 500
MAX_ROWS = 50_000
REPORT_ROWS = 200


class TemplateError(ValueError):
    pass


def read_template(handle: io.TextIOBase) -> list[ProcessedRow]:
    reader = csv.DictReader(handle)
    header = [(name or "").strip().lower() for name in reader.fieldnames or []]
    missing = [column for column in REQUIRED if column not in header]
    if missing:
        raise TemplateError(
            "not a flight template: missing column(s) " + ", ".join(missing)
            + " (convert the spreadsheet with flights_convert first)"
        )
    reader.fieldnames = header
    rows = []
    for number, raw in enumerate(reader, start=2):  # row 1 is the header
        if number - 1 > MAX_ROWS:
            raise TemplateError(f"more than {MAX_ROWS} rows")
        if not any((value or "").strip() for value in raw.values() if isinstance(value, str)):
            continue
        rows.append(process_row({k: raw.get(k) for k in COLUMNS}, number))
    return rows


def _signature(row: ProcessedRow) -> str:
    """Values plus what they resolved to: a reference-data update that changes a resolution
    makes the row 'changed' on a re-run."""
    f = row.fields
    resolved = [
        getattr(f[key], "pk", None)
        for key in ("origin_airport", "destination_airport", "airline", "aircraft_type")
    ]
    extra = f"{resolved}|{[p.reason for p in row.problems]}|{len(row.warnings)}"
    return hashlib.sha256((row.content_hash() + extra).encode()).hexdigest()


def _record_values(row: ProcessedRow, batch_id: int) -> dict:
    return {
        **row.fields,
        "import_batch_id": batch_id,
        "row_number": row.row_number,
        "status": FlightRecord.Status.RESOLVED if row.ok else FlightRecord.Status.UNMATCHED,
        "problems": [issue.as_dict() for issue in row.problems],
        "warnings": [issue.as_dict() for issue in row.warnings],
    }


def store(owner_id: int, batch_id: int, rows: list[ProcessedRow]) -> Counter:
    counts: Counter = Counter()
    keyed = list(zip(row_keys(rows), rows, strict=True))
    iterator = iter(keyed)
    while chunk := list(islice(iterator, CHUNK)):
        with rls_context(owner_id):
            existing = {
                record.row_key: record
                for record in FlightRecord.objects.filter(
                    owner_id=owner_id, row_key__in=[key for key, _ in chunk]
                )
            }
            for key, row in chunk:
                signature = _signature(row)
                record = existing.get(key)
                if record is None:
                    FlightRecord.objects.create(
                        owner_id=owner_id,
                        row_key=key,
                        content_hash=signature,
                        **_record_values(row, batch_id),
                    )
                    counts["new"] += 1
                elif record.content_hash == signature:
                    counts["identical"] += 1
                else:
                    for name, value in _record_values(row, batch_id).items():
                        setattr(record, name, value)
                    record.content_hash = signature
                    record.save()
                    counts["changed"] += 1
    return counts


def summarize(rows: list[ProcessedRow]) -> dict:
    reasons: Counter = Counter(p.reason for row in rows for p in row.problems)
    unmatched = [row for row in rows if not row.ok]
    return {
        "rows": len(rows),
        "resolved": len(rows) - len(unmatched),
        "unmatched": len(unmatched),
        "with_warnings": sum(1 for row in rows if row.warnings),
        "problems_by_reason": dict(reasons),
        "unmatched_rows": [
            {
                "row": row.row_number,
                "date": row.values["date"],
                "from": row.values["from"],
                "to": row.values["to"],
                "problems": [p.as_dict() for p in row.problems],
            }
            for row in unmatched[:REPORT_ROWS]
        ],
    }


@importers.register(ImportBatch.Kind.FLIGHTS_TEMPLATE)
def import_flight_template(batch: ImportBatch) -> dict:
    with rawstore.open_original(batch.raw_file) as stream:
        handle = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
        rows = read_template(handle)
    counts = store(batch.owner_id, batch.pk, rows)
    return {
        **summarize(rows),
        "records": {"new": counts["new"], "changed": counts["changed"],
                    "identical": counts["identical"]},
        "imported_at": timezone.now().isoformat(),
    }
