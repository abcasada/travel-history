"""Cut `?token=` out of tracker requests before anything can record it.

Overland (some versions) and hand-configured trackers may put the device token in the URL.
URLs end up in many places: the server's access log (gunicorn reads `RAW_URI` from the same
WSGI environ), redirects, `request.get_full_path()`, Django's error pages and reports. This
middleware runs first, takes the token out of `QUERY_STRING`, `RAW_URI` and `REQUEST_URI`, and
leaves it only on the request object, where `tokens.hash_from_request` reads it.

The development server logs the raw request line itself; the redacting log formatter covers
that (travel/core/logredact.py).
"""

from urllib.parse import parse_qsl, urlencode

from django.http import HttpRequest

INGEST_PATH = "/api/v1/ingest"
QUERY_KEY = "token"


class IngestTokenScrubMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        if request.path_info.startswith(INGEST_PATH):
            scrub_query_token(request)
        return self.get_response(request)


def scrub_query_token(request: HttpRequest) -> None:
    request.ingest_query_token = None
    query = request.META.get("QUERY_STRING", "")
    if QUERY_KEY not in query and "%" not in query:
        return
    pairs = parse_qsl(query, keep_blank_values=True)
    found = [value for key, value in pairs if key == QUERY_KEY]
    if not found:
        return
    # Two tokens in one URL is not a valid request; neither is used.
    request.ingest_query_token = found[0] if len(found) == 1 else ""
    kept = urlencode([(key, value) for key, value in pairs if key != QUERY_KEY])
    request.META["QUERY_STRING"] = kept
    clean_uri = request.path + (f"?{kept}" if kept else "")
    for key in ("RAW_URI", "REQUEST_URI"):
        if key in request.META:
            request.META[key] = clean_uri
