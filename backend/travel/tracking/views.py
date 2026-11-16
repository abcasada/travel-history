"""Tracker ingestion endpoints (PLAN.md §9.1), outside the login wall.

    POST /api/v1/ingest/owntracks   one OwnTracks message  -> 200 []
    POST /api/v1/ingest/overland    one Overland batch     -> 200 {"result":"ok"}

These are plain Django views, not part of the JSON API: they authenticate with a device token
only (never a session, so no CSRF), answer in the exact shape each app expects, and never
return data. Order of checks, cheapest and least revealing first:

1. POST only; per-IP rate limit (before the body or the token is looked at);
2. headers: a declared length within the cap, no chunked or compressed bodies, JSON;
3. the token: well formed, per-token rate limit, then looked up (401 for any refusal);
4. the body: read (at most the cap), parsed and validated strictly (400/413);
5. stored as the token's owner (ingest.py).

Errors are short JSON objects naming the problem and, for invalid payloads, the fields; they
never echo values. Every response is `Cache-Control: no-store`.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_variables

from travel.core import ratelimit
from travel.core.ratelimit import Rate

from . import ingest, payloads, tokens
from .payloads import PayloadError

log = logging.getLogger(__name__)

OWNTRACKS_OK = b"[]"
OVERLAND_OK = b'{"result":"ok"}'
WINDOW_SECONDS = 60


@csrf_exempt
def owntracks(request: HttpRequest) -> HttpResponse:
    return _handle(request, ingest.OWNTRACKS)


@csrf_exempt
def overland(request: HttpRequest) -> HttpResponse:
    return _handle(request, ingest.OVERLAND)


def _error(status: int, detail: str, errors: list[str] | None = None) -> JsonResponse:
    body: dict = {"detail": detail}
    if errors:
        body["errors"] = errors
    response = JsonResponse(body, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _ok(endpoint: str) -> HttpResponse:
    body = OWNTRACKS_OK if endpoint == ingest.OWNTRACKS else OVERLAND_OK
    response = HttpResponse(body, content_type="application/json")
    response["Cache-Control"] = "no-store"
    return response


def _limited(decision: ratelimit.Decision) -> HttpResponse:
    response = ratelimit.too_many_requests(decision)
    response["Cache-Control"] = "no-store"
    return response


@sensitive_variables()
def _handle(request: HttpRequest, endpoint: str) -> HttpResponse:
    if request.method != "POST":
        response = _error(405, "use POST")
        response["Allow"] = "POST"
        return response

    per_ip = ratelimit.hit(
        "ingest-ip",
        ratelimit.client_ip(request),
        Rate(limit=settings.TRACKER_RATE_PER_IP, period=WINDOW_SECONDS),
    )
    if not per_ip.allowed:
        log.info("ingest %s: per-address rate limit reached", endpoint)
        return _limited(per_ip)

    try:
        length = _declared_length(request)
    except PayloadError as error:
        return _error(error.status, error.detail)

    token_hash = tokens.hash_from_request(request)
    if token_hash is None:
        return _error(401, "a valid device token is required")
    per_token = ratelimit.hit(
        "ingest-token",
        token_hash,
        Rate(limit=settings.TRACKER_RATE_PER_TOKEN, period=WINDOW_SECONDS),
    )
    if not per_token.allowed:
        log.info("ingest %s: per-token rate limit reached", endpoint)
        return _limited(per_token)
    try:
        token = ingest.resolve(token_hash, endpoint)
    except ingest.TokenRefused:
        log.info("ingest %s: token refused", endpoint)
        return _error(401, "a valid device token is required")

    if length == 0:
        if endpoint == ingest.OWNTRACKS:  # OwnTracks may send empty bodies; nothing to store
            return _ok(endpoint)
        return _error(400, "the body is empty")
    try:
        _check_content_type(request)
        parsed = _parse(request, endpoint)
    except PayloadError as error:
        log.warning(
            "ingest %s: payload rejected for device %s: %s %s",
            endpoint,
            token.pk,
            error.detail,
            "; ".join(error.errors),
        )
        return _error(error.status, error.detail, error.errors)

    try:
        outcome = ingest.store(token, parsed.fixes)
    except ingest.TokenRefused:
        return _error(401, "a valid device token is required")
    level = logging.INFO if outcome.out_of_window or outcome.flagged else logging.DEBUG
    log.log(
        level,
        "ingest %s: device %s received %d stored %d duplicates %d out-of-window %d "
        "flagged %d ignored %d",
        endpoint,
        token.pk,
        outcome.received,
        outcome.stored,
        outcome.duplicates,
        outcome.out_of_window,
        outcome.flagged,
        parsed.ignored,
    )
    return _ok(endpoint)


def _declared_length(request: HttpRequest) -> int:
    """The body's declared length. Bodies must say how long they are: Django reads a body
    without a Content-Length as empty, which would silently lose points."""
    if request.META.get("HTTP_TRANSFER_ENCODING"):
        raise PayloadError(411, "send the body with a Content-Length, not chunked")
    encoding = request.META.get("HTTP_CONTENT_ENCODING", "").strip().lower()
    if encoding not in ("", "identity"):
        raise PayloadError(415, "compressed bodies are not accepted")
    raw = request.META.get("CONTENT_LENGTH") or "0"
    try:
        length = int(raw)
    except ValueError:
        raise PayloadError(400, "invalid Content-Length") from None
    if length < 0:
        raise PayloadError(400, "invalid Content-Length")
    if length > settings.TRACKER_MAX_BODY_BYTES:
        raise PayloadError(413, f"the body is larger than {settings.TRACKER_MAX_BODY_BYTES} bytes")
    return length


def _check_content_type(request: HttpRequest) -> None:
    if request.content_type != "application/json":
        raise PayloadError(415, "send JSON (Content-Type: application/json)")


def _parse(request: HttpRequest, endpoint: str) -> payloads.Parsed:
    body = request.body  # bounded: the declared length is within the cap
    if len(body) > settings.TRACKER_MAX_BODY_BYTES:
        raise PayloadError(413, "the body is too large")
    document = payloads.load_json(body)
    if endpoint == ingest.OWNTRACKS:
        return payloads.parse_owntracks(document)
    return payloads.parse_overland(document, settings.TRACKER_MAX_POINTS)
