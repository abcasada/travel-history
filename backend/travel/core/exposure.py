"""What the internet may reach (D-73, D-85; docs/tracking/exposure.md).

Until go-live (Authentik with 2FA, phase 8) only the two tracker ingestion endpoints are public.
This guard enforces that inside the app, so it never rests on a tunnel or dashboard rule alone:

- **Public host names** (`TRAVEL_PUBLIC_HOSTS`, e.g. the tunnel's hostname): with
  `TRAVEL_PUBLIC_SCOPE=tracker` (the default) every path except the ingest endpoints answers
  404. A server running with DEBUG answers 404 to every path on them, so pointing the tunnel at
  the development server by mistake exposes nothing.
- **Ingest-only servers** (`TRAVEL_INGEST_ONLY`, the `ingest` service the tunnel points at):
  the same allowlist whatever the Host header says (a tunnel "HTTP Host Header" override, for
  instance), plus `/healthz` for the container's own health check from inside the container.

It runs right after SecurityMiddleware (so its 404s carry HSTS and the other security headers)
and before WhiteNoise, which would otherwise serve static files and the SPA bundle.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.http.request import split_domain_port

# Mirrors the two ingest routes in config/urls.py (a trailing slash is accepted there too);
# tests/test_exposure.py checks both agree.
INGEST_PATH = re.compile(r"/api/v1/ingest/(?:owntracks|overland)/?")
HEALTHZ = "/healthz"
LOOPBACK = frozenset({"127.0.0.1", "::1"})
SCOPES = ("tracker", "all")


def is_public_host(request: HttpRequest) -> bool:
    """Judged on the raw Host header (Django ignores X-Forwarded-Host here too), before
    ALLOWED_HOSTS is checked, so the decision never depends on that check running first."""
    domain, _port = split_domain_port(request.META.get("HTTP_HOST", "").lower())
    return bool(domain) and domain in settings.TRAVEL_PUBLIC_HOSTS


def is_reachable(request: HttpRequest) -> bool:
    path = request.path_info
    if is_public_host(request):
        if settings.DEBUG:
            return False
        if settings.TRAVEL_PUBLIC_SCOPE != "all" or settings.TRAVEL_INGEST_ONLY:
            return INGEST_PATH.fullmatch(path) is not None
        return True
    if settings.TRAVEL_INGEST_ONLY:
        if INGEST_PATH.fullmatch(path):
            return True
        # The health check runs inside the container; nothing outside it connects from
        # loopback (published ports arrive from the Docker gateway address).
        return path == HEALTHZ and request.META.get("REMOTE_ADDR") in LOOPBACK
    return True


def not_found() -> HttpResponse:
    response = HttpResponseNotFound(b"Not Found\n", content_type="text/plain; charset=utf-8")
    # This response skips the inner middleware (CSP, X-Frame-Options), so it sets its own.
    response["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response["X-Frame-Options"] = "DENY"
    response["Cache-Control"] = "no-store"
    return response


class ExposureGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not is_reachable(request):
            return not_found()
        return self.get_response(request)


def production_problems(
    *,
    debug: bool,
    proxy_ssl_header: tuple[str, str] | None,
    ssl_redirect: bool,
    hsts_seconds: int,
    secure_cookies: bool,
    public_hosts: list[str],
    allowed_hosts: list[str],
) -> list[str]:
    """Why a server facing the internet (TRAVEL_INGEST_ONLY) must not start; settings.py raises
    ImproperlyConfigured when this list isn't empty."""
    problems = []
    if debug:
        problems.append("DJANGO_DEBUG must be false")
    if proxy_ssl_header is None:
        problems.append("DJANGO_BEHIND_TLS_PROXY must be true (the tunnel terminates TLS)")
    if not ssl_redirect:
        problems.append("DJANGO_SSL_REDIRECT must be true (HTTPS only)")
    if hsts_seconds <= 0:
        problems.append("DJANGO_HSTS_SECONDS must be positive")
    if not secure_cookies:
        problems.append("DJANGO_SECURE_COOKIES must be true")
    if not public_hosts:
        problems.append("TRAVEL_PUBLIC_HOSTS must name the public host name")
    if "*" in allowed_hosts:
        problems.append("DJANGO_ALLOWED_HOSTS must not contain '*'")
    return problems
