"""Take the device token out of tracker requests before anything can record it.

Requests carry the token in `Authorization` (Bearer, or Basic with the token as password) or,
for some Overland versions and hand-configured trackers, in `?token=`. Both end up in many
places: the server's access log (gunicorn reads `RAW_URI` from the same WSGI environ), the
request that Django attaches to every 4xx/5xx log record, error pages and mailed reports,
redirects. This middleware runs first: it removes the token from `META` (the header, the query
string, `RAW_URI`, `REQUEST_URI`) and leaves only its SHA-256 on the request, as
`request.ingest_token_hash` (None when the request has no well-formed token).

The development server logs the raw request line itself; the redacting log formatter covers
that (travel/core/logredact.py).
"""

from urllib.parse import parse_qsl, urlencode

from django.http import HttpRequest
from django.views.decorators.debug import sensitive_variables

from . import tokens

INGEST_PATH = "/api/v1/ingest"
QUERY_KEY = "token"


class IngestTokenScrubMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        if request.path_info.startswith(INGEST_PATH):
            take_token(request)
        return self.get_response(request)


@sensitive_variables()
def take_token(request: HttpRequest) -> None:
    """Accepted, in this order: the Authorization header, then `?token=`. A request with an
    Authorization header is judged by the header alone; two query tokens are invalid."""
    header = request.META.pop("HTTP_AUTHORIZATION", None)
    query_token = _pop_query_token(request)
    candidate = tokens.from_authorization(header) if header is not None else query_token
    request.ingest_token_hash = (
        tokens.hash_token(candidate) if tokens.is_well_formed(candidate) else None
    )


@sensitive_variables()
def _pop_query_token(request: HttpRequest) -> str | None:
    query = request.META.get("QUERY_STRING", "")
    if QUERY_KEY not in query and "%" not in query:
        return None
    pairs = parse_qsl(query, keep_blank_values=True)
    found = [value for key, value in pairs if key == QUERY_KEY]
    if not found:
        return None
    kept = urlencode([(key, value) for key, value in pairs if key != QUERY_KEY])
    request.META["QUERY_STRING"] = kept
    clean_uri = request.path + (f"?{kept}" if kept else "")
    for key in ("RAW_URI", "REQUEST_URI"):
        if key in request.META:
            request.META[key] = clean_uri
    return found[0] if len(found) == 1 else None
