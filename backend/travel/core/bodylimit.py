"""Request body limits per endpoint (F-2, D-107).

Django reads a form body in CsrfViewMiddleware, before any view or rate limit runs, and sends
multipart file parts to temporary files (`/tmp`, a tmpfs in production, so memory) whatever
`DATA_UPLOAD_MAX_MEMORY_SIZE` says. Anyone with a well-formed `csrftoken` cookie could make the
web container hold tens of megabytes per request. This middleware runs before anything reads a
body and answers 413 when the declared `Content-Length` is above the endpoint's limit:

- the upload-chunk endpoint: one chunk (`TRAVEL_UPLOAD_CHUNK_BYTES`, 32 MiB), read by
  `uploads.receive_chunk` with its own length and checksum checks;
- the two tracker endpoints: `TRACKER_MAX_BODY_BYTES` (5 MiB), as the tracker views check;
- everything else: `DATA_UPLOAD_MAX_MEMORY_SIZE` (2.5 MiB; the largest JSON body, a drawn
  route of 10,000 points, stays well under 1 MiB).

A body without a `Content-Length` (chunked) is read as empty by Django, so it costs nothing;
the tracker endpoints refuse it with 411. The rest of an oversized body is discarded by the
server in small pieces, never held.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from travel.core.exposure import INGEST_PATH

# config/urls.py mounts the API at /api/v1/; travel.history.api's putChunk route.
UPLOAD_CHUNK_PATH = re.compile(r"/api/v1/uploads/[^/]+/chunks/[^/]+")


def body_limit(request: HttpRequest) -> int:
    """The largest body this request's endpoint accepts, in bytes."""
    path = request.path_info
    if request.method == "PUT" and UPLOAD_CHUNK_PATH.fullmatch(path):
        return settings.TRAVEL_UPLOAD_CHUNK_BYTES
    if INGEST_PATH.fullmatch(path):
        return settings.TRACKER_MAX_BODY_BYTES
    return settings.DATA_UPLOAD_MAX_MEMORY_SIZE


def declared_length(request: HttpRequest) -> int:
    """`Content-Length` as Django reads it (anything unparsable counts as an empty body)."""
    try:
        return max(int(request.META.get("CONTENT_LENGTH") or 0), 0)
    except ValueError:
        return 0


class BodySizeLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        limit = body_limit(request)
        if declared_length(request) > limit:
            response = JsonResponse(
                {"detail": f"the request body is larger than {limit} bytes"}, status=413
            )
            response["Cache-Control"] = "no-store"
            return response
        return self.get_response(request)
