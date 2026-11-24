"""Dispatch an import batch to the importer for its kind. Importers run in the worker, as the
batch owner, and write their summary into the batch. An importer returns its summary (the batch
is then done), or a `Result` to end in another status: the trip spreadsheet importer stops at
`preview` until the user commits (§28.8), or `failed` for a file it refuses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.utils import timezone

from travel.core.rls import rls_context

from .models import ImportBatch


@dataclass
class Result:
    summary: dict
    status: str = ImportBatch.Status.DONE
    error: str = ""


Importer = Callable[[ImportBatch], "dict | Result"]
_REGISTRY: dict[str, Importer] = {}


def register(kind: str):
    def decorator(fn: Importer) -> Importer:
        _REGISTRY[kind] = fn
        return fn

    return decorator


def run(batch_id: int, owner_id: int) -> ImportBatch:
    with rls_context(owner_id):
        batch = ImportBatch.objects.select_related("raw_file").get(pk=batch_id)
    importer = _REGISTRY.get(batch.kind)
    if importer is None:
        with rls_context(owner_id):
            batch.status = ImportBatch.Status.UNSUPPORTED
            batch.summary = {
                "message": "the raw file is archived; it will be imported once an "
                "importer for this format exists"
            }
            batch.finished_at = timezone.now()
            batch.save(update_fields=["status", "summary", "finished_at"])
        return batch
    try:
        result = importer(batch)
    except Exception as exc:
        with rls_context(owner_id):
            ImportBatch.objects.filter(pk=batch_id).update(
                status=ImportBatch.Status.FAILED,
                error=f"{type(exc).__name__}: {exc}"[:2000],
                finished_at=timezone.now(),
            )
        raise
    if not isinstance(result, Result):
        result = Result(summary=result)
    with rls_context(owner_id):
        ImportBatch.objects.filter(pk=batch_id).update(
            status=result.status,
            summary=result.summary,
            error=result.error[:2000],
            finished_at=timezone.now(),
        )
        return ImportBatch.objects.get(pk=batch_id)
