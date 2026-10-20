"""Resumable chunked uploads (PLAN.md §17, D-33). Chunks arrive in order, each with its SHA-256;
re-sending the last chunk is harmless, so clients can retry after any network failure. The
finished file is stored and imported by the worker (`process_upload`), never in the request."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import BinaryIO

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from travel.core.rls import rls_context

from . import importers, rawstore
from .models import ImportBatch, RawFile, UploadSession

STALE_AFTER = dt.timedelta(days=7)


class UploadError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def part_path(session: UploadSession) -> Path:
    return Path(settings.BULK_DIR) / "uploads" / str(session.owner_id) / f"{session.pk}.part"


def _bytes_in_use(owner_id: int) -> int:
    stored = RawFile.objects.filter(owner_id=owner_id).aggregate(n=Sum("compressed_size"))["n"]
    pending = UploadSession.objects.filter(
        owner_id=owner_id, status=UploadSession.Status.OPEN
    ).aggregate(n=Sum("total_size"))["n"]
    return (stored or 0) + (pending or 0)


def _drop_stale_sessions(owner_id: int) -> None:
    cutoff = timezone.now() - STALE_AFTER
    for session in UploadSession.objects.filter(
        owner_id=owner_id, status=UploadSession.Status.OPEN, updated_at__lt=cutoff
    ):
        abort(session)


def create_session(
    owner_id: int,
    *,
    filename: str,
    size: int,
    kind: str,
    content_type: str = "",
    uploaded_via: str = RawFile.UploadedVia.WEB,
) -> UploadSession:
    if kind not in ImportBatch.Kind.values:
        raise UploadError(422, "unknown import kind")
    if size <= 0:
        raise UploadError(422, "empty file")
    if size > settings.TRAVEL_UPLOAD_MAX_BYTES:
        raise UploadError(413, "file is larger than the upload limit")
    _drop_stale_sessions(owner_id)
    if _bytes_in_use(owner_id) + size > settings.TRAVEL_USER_QUOTA_BYTES:
        raise UploadError(413, "storage quota exceeded")
    session = UploadSession.objects.create(
        owner_id=owner_id,
        filename=Path(filename).name[:255] or "upload",
        content_type=content_type[:100],
        kind=kind,
        total_size=size,
        chunk_size=settings.TRAVEL_UPLOAD_CHUNK_BYTES,
        uploaded_via=uploaded_via,
    )
    path = part_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    return session


def receive_chunk(
    session: UploadSession, index: int, stream: BinaryIO, length: int, sha256: str
) -> UploadSession:
    if session.status != UploadSession.Status.OPEN:
        raise UploadError(409, "upload is not open")
    sha256 = sha256.strip().lower()
    if index == session.next_index - 1 and sha256 == session.last_chunk_sha256:
        return session  # a retried chunk we already have
    if index != session.next_index:
        raise UploadError(409, f"expected chunk {session.next_index}")
    if length <= 0 or length > session.chunk_size:
        raise UploadError(413, "chunk too large")
    if session.received_bytes + length > session.total_size:
        raise UploadError(413, "more data than the declared size")
    last = session.received_bytes + length == session.total_size
    if not last and length != session.chunk_size:
        raise UploadError(422, "only the last chunk may be shorter than chunk_size")
    data = stream.read(length + 1)
    if len(data) != length:
        raise UploadError(422, "chunk length does not match Content-Length")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise UploadError(422, "chunk checksum mismatch")
    with part_path(session).open("r+b") as handle:
        # Write at the recorded offset (a crash mid-append must not leave stray bytes).
        handle.seek(session.received_bytes)
        handle.write(data)
        handle.truncate()
    session.received_bytes += length
    session.next_index += 1
    session.last_chunk_sha256 = sha256
    session.save(update_fields=["received_bytes", "next_index", "last_chunk_sha256", "updated_at"])
    return session


def complete(session: UploadSession) -> ImportBatch:
    """Close the upload and queue the worker job (enqueued in the same transaction)."""
    from .tasks import process_upload

    if session.status != UploadSession.Status.OPEN:
        raise UploadError(409, "upload is not open")
    if session.received_bytes != session.total_size:
        raise UploadError(409, "upload is incomplete")
    batch = ImportBatch.objects.create(owner_id=session.owner_id, kind=session.kind)
    session.status = UploadSession.Status.COMPLETE
    session.import_batch = batch
    session.save(update_fields=["status", "import_batch", "updated_at"])
    process_upload.configure(lock=f"imports-user-{session.owner_id}").defer(
        upload_id=str(session.pk), owner_id=session.owner_id
    )
    return batch


def abort(session: UploadSession) -> None:
    session.status = UploadSession.Status.ABORTED
    session.save(update_fields=["status", "updated_at"])
    part_path(session).unlink(missing_ok=True)


def process_upload(upload_id: str, owner_id: int) -> ImportBatch:
    """Worker job: checksum, detect identical re-uploads, archive the raw file, run the importer.
    Each step runs in its own short transaction as the owner."""
    with rls_context(owner_id):
        session = UploadSession.objects.get(pk=upload_id)
        batch = session.import_batch
        batch.status, batch.started_at = ImportBatch.Status.PROCESSING, timezone.now()
        batch.save(update_fields=["status", "started_at"])
    part = part_path(session)
    digest = rawstore.sha256_file(part)
    with rls_context(owner_id):
        existing = rawstore.find_existing(owner_id, digest)
        if existing is not None:
            first = (
                ImportBatch.objects.filter(raw_file=existing)
                .exclude(pk=batch.pk)
                .order_by("created_at")
                .first()
            )
            batch.raw_file = existing
            batch.status = ImportBatch.Status.DUPLICATE
            batch.summary = {"duplicate_of_batch": first.pk if first else None}
            batch.finished_at = timezone.now()
            batch.save(update_fields=["raw_file", "status", "summary", "finished_at"])
            part.unlink(missing_ok=True)
            return batch
        raw = rawstore.store_file(
            owner_id,
            part,
            original_name=session.filename,
            content_type=session.content_type,
            uploaded_via=session.uploaded_via,
            sha256=digest,
        )
        batch.raw_file = raw
        batch.save(update_fields=["raw_file"])
    part.unlink(missing_ok=True)
    return importers.run(batch.pk, owner_id)
