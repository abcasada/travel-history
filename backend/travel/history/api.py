"""Upload and import endpoints (PLAN.md §17). The same API serves the browser (session + CSRF)
and the Android companion (bearer token)."""

import datetime as dt
import uuid

from django.shortcuts import get_object_or_404
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from travel.core import policy

from . import uploads
from .models import ImportBatch, RawFile, UploadSession

router = Router(tags=["imports"])


class UploadIn(Schema):
    filename: str
    size: int
    kind: ImportBatch.Kind
    content_type: str = ""


class UploadOut(Schema):
    id: uuid.UUID
    filename: str
    kind: str
    total_size: int
    chunk_size: int
    received_bytes: int
    next_index: int
    status: str
    import_batch_id: int | None


class ImportBatchOut(Schema):
    id: int
    kind: str
    status: str
    original_name: str | None
    size_bytes: int | None
    summary: dict
    error: str
    created_at: dt.datetime
    finished_at: dt.datetime | None

    @staticmethod
    def resolve_original_name(obj: ImportBatch) -> str | None:
        return obj.raw_file.original_name if obj.raw_file_id else None

    @staticmethod
    def resolve_size_bytes(obj: ImportBatch) -> int | None:
        return obj.raw_file.size_bytes if obj.raw_file_id else None


def _session(request, upload_id: uuid.UUID) -> UploadSession:
    return get_object_or_404(UploadSession, pk=upload_id, owner=request.user)


def _raise(error: uploads.UploadError):
    raise HttpError(error.status, error.message)


@router.post("/uploads", response={201: UploadOut}, operation_id="createUpload")
def create_upload(request, payload: UploadIn):
    if not policy.can_import(request.user):
        raise HttpError(403, "your role cannot import data")
    via = (
        RawFile.UploadedVia.COMPANION
        if getattr(request, "via_bearer", False)
        else RawFile.UploadedVia.WEB
    )
    try:
        session = uploads.create_session(
            request.user.pk,
            filename=payload.filename,
            size=payload.size,
            kind=payload.kind,
            content_type=payload.content_type,
            uploaded_via=via,
        )
    except uploads.UploadError as error:
        _raise(error)
    return Status(201, session)


@router.get("/uploads/{upload_id}", response=UploadOut, operation_id="getUpload")
def get_upload(request, upload_id: uuid.UUID):
    return _session(request, upload_id)


@router.put("/uploads/{upload_id}/chunks/{index}", response=UploadOut, operation_id="putChunk")
def put_chunk(request, upload_id: uuid.UUID, index: int):
    """Body: the raw chunk bytes (application/octet-stream); header X-Chunk-SHA256."""
    session = _session(request, upload_id)
    sha256 = request.headers.get("X-Chunk-SHA256", "")
    if len(sha256) != 64:
        raise HttpError(422, "X-Chunk-SHA256 header required")
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        raise HttpError(411, "Content-Length required") from None
    try:
        return uploads.receive_chunk(session, index, request, length, sha256)
    except uploads.UploadError as error:
        _raise(error)


@router.post(
    "/uploads/{upload_id}/complete", response={202: ImportBatchOut}, operation_id="completeUpload"
)
def complete_upload(request, upload_id: uuid.UUID):
    try:
        batch = uploads.complete(_session(request, upload_id))
    except uploads.UploadError as error:
        _raise(error)
    return Status(202, batch)


@router.delete("/uploads/{upload_id}", response={204: None}, operation_id="abortUpload")
def abort_upload(request, upload_id: uuid.UUID):
    session = _session(request, upload_id)
    if session.status == UploadSession.Status.OPEN:
        uploads.abort(session)
    return Status(204, None)


@router.get("/imports", response=list[ImportBatchOut], operation_id="listImports")
def list_imports(request):
    return (
        ImportBatch.objects.filter(owner=request.user)
        .select_related("raw_file")
        .order_by("-created_at")[:200]
    )


@router.get("/imports/{batch_id}", response=ImportBatchOut, operation_id="getImport")
def get_import(request, batch_id: int):
    return get_object_or_404(
        ImportBatch.objects.select_related("raw_file"), pk=batch_id, owner=request.user
    )
