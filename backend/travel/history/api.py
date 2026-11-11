"""Upload and import endpoints (PLAN.md §17). The same API serves the browser (session + CSRF)
and the Android companion (bearer token)."""

import datetime as dt
import gzip
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from ninja import Field, Query, Router, Schema, Status
from ninja.errors import HttpError

from travel.core import policy

from . import tiles, uploads
from .models import ImportBatch, PointSource, RawFile, UploadSession

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


# --- Raw-history map (milestone 2.3, PLAN.md §14) -------------------------------------------
# Row-level security limits every query below to the caller's own history; the policy check is
# the app-level half of the same rule (never the Admin, never another member).

MVT = "application/vnd.mapbox-vector-tile"
_TILE_DOC = {
    "responses": {
        200: {"description": "Mapbox Vector Tile", "content": {MVT: {}}},
        404: {"description": "Tile outside the supported zoom range or grid"},
        503: {"description": "Tile took too long; narrow the date range or zoom in"},
    }
}


def _require_raw_history(request) -> None:
    if not policy.can_access_raw_history(request.user, request.user.pk):
        raise HttpError(403, "no access to raw history")


class TimeRangeIn(Schema):
    start: dt.datetime | None = Field(None, alias="from", description="inclusive, with offset")
    end: dt.datetime | None = Field(None, alias="to", description="exclusive, with offset")


class PointsTileIn(TimeRangeIn):
    source: str | None = Field(None, description="comma-separated point sources")


class CoverageIn(Schema):
    first: dt.date = Field(alias="from")
    last: dt.date = Field(alias="to")
    tz: str = Field("UTC", description="IANA zone that defines the local days")


def _range(params: TimeRangeIn) -> tuple[dt.datetime | None, dt.datetime | None]:
    start, end = params.start, params.end
    for value in (start, end):
        if value is not None and value.tzinfo is None:
            raise HttpError(422, "'from' and 'to' need a UTC offset")
    if start is not None and end is not None and end <= start:
        raise HttpError(422, "'to' must be after 'from'")
    return start, end


def _sources(source: str | None) -> list[str] | None:
    if not source:
        return None
    picked = [s for s in source.split(",") if s]
    if not set(picked) <= set(PointSource.values):
        raise HttpError(422, "unknown point source")
    return picked


def _tile_response(request, make) -> HttpResponse:
    try:
        tile = make()
    except tiles.TileError as error:
        raise HttpError(404, str(error)) from None
    except tiles.TileTimeout:
        response = HttpResponse("tile took too long", status=503, content_type="text/plain")
        response["Retry-After"] = "30"
        return response
    data = tile.data
    response = HttpResponse(content_type=MVT)
    if data and "gzip" in request.headers.get("Accept-Encoding", ""):
        data = gzip.compress(data, compresslevel=5)
        response["Content-Encoding"] = "gzip"
    response.content = data
    response["Vary"] = "Accept-Encoding, Cookie"
    # Private history: the browser may reuse it briefly, shared caches never.
    response["Cache-Control"] = "private, max-age=300"
    response["X-Tile-Aggregated"] = "1" if tile.aggregated else "0"
    if tile.truncated:
        response["X-Tile-Truncated"] = "1"
    return response


@router.get(
    "/history/tiles/{z}/{x}/{y}.mvt",
    operation_id="getHistoryPointsTile",
    tags=["history"],
    openapi_extra=_TILE_DOC,
)
def history_points_tile(request, z: int, x: int, y: int, params: Query[PointsTileIn]):
    """The caller's raw location points as a vector tile (layer `points`). Below zoom 14, and in
    dense tiles above it, points are counted into a grid (`n` = points in the cell); otherwise
    each point is a feature with `ts` (epoch seconds) and `src`."""
    _require_raw_history(request)
    start, end = _range(params)
    sources = _sources(params.source)
    return _tile_response(
        request, lambda: tiles.points_tile(z, x, y, start=start, end=end, sources=sources)
    )


@router.get(
    "/history/segments/tiles/{z}/{x}/{y}.mvt",
    operation_id="getHistorySegmentsTile",
    tags=["history"],
    openapi_extra=_TILE_DOC,
)
def history_segments_tile(request, z: int, x: int, y: int, params: Query[TimeRangeIn]):
    """The caller's current Timeline segments as a vector tile (layer `segments`; zoom 5 and
    up): visits as points, activities and paths as lines, with `kind`, `activity`, `semantic`,
    `t0`/`t1` (epoch seconds)."""
    _require_raw_history(request)
    start, end = _range(params)
    return _tile_response(request, lambda: tiles.segments_tile(z, x, y, start=start, end=end))


class CoverageDayOut(Schema):
    day: dt.date
    points: int
    segments: int


class CoverageOut(Schema):
    first_day: dt.date | None
    last_day: dt.date | None
    days: list[CoverageDayOut]


@router.get(
    "/history/coverage", response=CoverageOut, operation_id="getHistoryCoverage", tags=["history"]
)
def history_coverage(request, params: Query[CoverageIn]):
    """Which local days (in IANA zone `tz`) have points or Timeline segments, for the coverage
    strip; at most 400 days per request. Days without data are omitted."""
    _require_raw_history(request)
    try:
        zone = ZoneInfo(params.tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise HttpError(422, "unknown time zone") from None
    try:
        return tiles.coverage(params.first, params.last, zone)
    except ValueError as error:
        raise HttpError(422, str(error)) from None
    except tiles.TileTimeout:
        raise HttpError(503, "coverage took too long; try a shorter range") from None
