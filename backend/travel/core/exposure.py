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

- **Other public names** (`TRAVEL_PUBLIC_HOSTS` other than `TRAVEL_CANONICAL_HOST`, e.g.
  trips.example.org): every path except the ingest endpoints answers a permanent redirect to the
  same path on the canonical host (D-96). The target host comes from settings, never from the
  request, so it is not an open redirect. Ingest paths are served as on the canonical host, so a
  phone set up with the other name keeps working.
- **Development servers** (DEBUG): any Host header Django would refuse answers a bare 404 too.
  Otherwise Django answers it with DEBUG's technical error page (status 400), which shows
  settings and a traceback, so a tunnel pointed at the dev server by mistake would leak them.

It runs right after SecurityMiddleware (so its 404s carry HSTS and the other security headers)
and before WhiteNoise, which would otherwise serve static files and the SPA bundle.

`HttpsRedirectMiddleware` sits between the two: with `DJANGO_SSL_REDIRECT` (production) plain
HTTP answers a permanent redirect to HTTPS, except the container's own `/healthz` and plain HTTP
on the server's loopback names (`is_local_http`), which is how the production app is reached
over an SSH port-forward before go-live (G-4, D-103). Requests through the tunnel always carry
the public host name, `X-Forwarded-Proto` and `CF-Connecting-IP`, so none of them is local.

`production_problems` lists why a production server must not start (auth.md §7.7, D-85 (3),
D-96); settings.py raises ImproperlyConfigured when it isn't empty.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from django.conf import settings
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseNotFound,
    HttpResponsePermanentRedirect,
)
from django.http.request import split_domain_port, validate_host

# Mirrors the two ingest routes in config/urls.py (a trailing slash is accepted there too);
# tests/test_exposure.py checks both agree.
INGEST_PATH = re.compile(r"/api/v1/ingest/(?:owntracks|overland)/?")
HEALTHZ = "/healthz"
LOOPBACK = frozenset({"127.0.0.1", "::1"})
SCOPES = ("tracker", "all")
# Host names (as request_domain returns them) that only reach the server from the server itself:
# the production web port is published on 127.0.0.1 only (D-28), and an SSH port-forward
# arrives there too. G-4's temporary redirect URI is http://localhost:8784/auth/callback.
LOCAL_NAMES = frozenset({"localhost", "127.0.0.1", "[::1]"})
# Cloudflare's tunnel adds both to every request it forwards (cloudflared passes them on).
TUNNEL_HEADERS = ("HTTP_X_FORWARDED_PROTO", "HTTP_CF_CONNECTING_IP")


def request_domain(request: HttpRequest) -> str:
    """The raw Host header's name, lower-case and without the port (Django ignores
    X-Forwarded-Host here too), read before ALLOWED_HOSTS is checked, so no decision here
    depends on that check running first. Empty if the header is missing or malformed."""
    domain, _port = split_domain_port(request.META.get("HTTP_HOST", "").lower())
    return domain


def is_public_host(request: HttpRequest) -> bool:
    domain = request_domain(request)
    return bool(domain) and domain in settings.TRAVEL_PUBLIC_HOSTS


def _debug_allows_host(domain: str) -> bool:
    """What Django's own host check accepts on a DEBUG server (the localhost names when
    ALLOWED_HOSTS is empty)."""
    allowed = settings.ALLOWED_HOSTS or [".localhost", "127.0.0.1", "[::1]"]
    return bool(domain) and validate_host(domain, allowed)


def is_reachable(request: HttpRequest) -> bool:
    path = request.path_info
    if settings.DEBUG and not _debug_allows_host(request_domain(request)):
        return False
    if is_public_host(request):
        if settings.DEBUG:
            return False
        if settings.TRAVEL_PUBLIC_SCOPE != "all" or settings.TRAVEL_INGEST_ONLY:
            # Before go-live only the ingest paths; the other public names redirect first.
            return INGEST_PATH.fullmatch(path) is not None or (
                not settings.TRAVEL_INGEST_ONLY and canonical_redirect(request) is not None
            )
        return True
    if settings.TRAVEL_INGEST_ONLY:
        if INGEST_PATH.fullmatch(path):
            return True
        # The health check runs inside the container; nothing outside it connects from
        # loopback (published ports arrive from the Docker gateway address).
        return path == HEALTHZ and request.META.get("REMOTE_ADDR") in LOOPBACK
    return True


def canonical_redirect(request: HttpRequest) -> str | None:
    """Where a public name other than the canonical one sends this request: the same path and
    query on `https://<TRAVEL_CANONICAL_HOST>`. None for the canonical host itself, for hosts
    that aren't public, for the ingest paths and on ingest-only or DEBUG servers."""
    canonical = settings.TRAVEL_CANONICAL_HOST
    if (
        not canonical
        or settings.DEBUG
        or settings.TRAVEL_INGEST_ONLY
        or not is_public_host(request)
        or request_domain(request) == canonical
        or INGEST_PATH.fullmatch(request.path_info)
    ):
        return None
    # get_full_path() percent-encodes the path, so it can't end the URL's authority or add a
    # header line; the scheme and host are fixed above.
    return f"https://{canonical}{request.get_full_path()}"


def is_local_http(request: HttpRequest) -> bool:
    """Plain HTTP to one of the server's loopback names, not through the tunnel: the SSH
    port-forward to localhost (G-4) or the server itself. Only the HTTPS redirect is skipped for
    these; cookies stay Secure (Chrome and Firefox accept Secure cookies from
    http://localhost, Safari doesn't) and everything else is unchanged."""
    return (
        not request.is_secure()
        and request_domain(request) in LOCAL_NAMES
        and not is_public_host(request)
        and not any(header in request.META for header in TUNNEL_HEADERS)
    )


class HttpsRedirectMiddleware:
    """HTTPS only (auth.md §7.7): with `TRAVEL_SSL_REDIRECT` (DJANGO_SSL_REDIRECT), a plain-HTTP
    request answers a permanent redirect to the same URL over HTTPS, as Django's
    SECURE_SSL_REDIRECT would (same target, same refusal of hosts outside ALLOWED_HOSTS), except
    `/healthz` (the container's own health check) and `is_local_http` requests."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if (
            settings.TRAVEL_SSL_REDIRECT
            and not request.is_secure()
            and request.path_info != HEALTHZ
            and not is_local_http(request)
        ):
            return HttpResponsePermanentRedirect(
                f"https://{request.get_host()}{request.get_full_path()}"
            )
        return self.get_response(request)


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
        if target := canonical_redirect(request):
            response = HttpResponsePermanentRedirect(target)
            # Like not_found(): this response skips the inner middleware.
            response["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
            response["X-Frame-Options"] = "DENY"
            return response
        return self.get_response(request)


# The rate limiter trusts this header for client addresses (D-85 (4)); Cloudflare sets it.
CLIENT_IP_HEADER = "CF-Connecting-IP"
# Secret keys a production server must never run with (build step, tests, examples).
PLACEHOLDER_SECRET_KEYS = frozenset({"build-only", "test-only-not-secret", "generate"})
# Django's own deploy check (security.W009) asks for 50+ characters, 5+ of them different.
MIN_SECRET_KEY_LENGTH = 50
MIN_SECRET_KEY_UNIQUE = 5
REQUIRED_MIDDLEWARE = (
    "django.middleware.security.SecurityMiddleware",
    "travel.core.exposure.HttpsRedirectMiddleware",
    "travel.core.exposure.ExposureGuardMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
)


def production_problems(conf: Mapping[str, Any]) -> list[str]:
    """Why a server facing the internet must not start: the production stack (TRAVEL_PRODUCTION)
    and its ingest-only service (TRAVEL_INGEST_ONLY). `conf` maps setting names to values
    (settings.py passes its own globals). The checklist is auth.md §7.7; HSTS is required on
    the ingest-only service and, for the rest, once the whole app is public (scope `all`)."""
    problems = []
    if conf["DEBUG"]:
        problems.append("DJANGO_DEBUG must be false")
    key = conf["SECRET_KEY"]
    if (
        len(key) < MIN_SECRET_KEY_LENGTH
        or len(set(key)) < MIN_SECRET_KEY_UNIQUE
        or key in PLACEHOLDER_SECRET_KEYS
        or key.startswith("django-insecure")
    ):
        problems.append(
            f"DJANGO_SECRET_KEY must be a generated secret of {MIN_SECRET_KEY_LENGTH}+ characters"
        )
    if conf["SECURE_PROXY_SSL_HEADER"] is None:
        problems.append("DJANGO_BEHIND_TLS_PROXY must be true (the tunnel terminates TLS)")
    if not conf["TRAVEL_SSL_REDIRECT"]:
        problems.append("DJANGO_SSL_REDIRECT must be true (HTTPS only)")
    hsts_required = conf["TRAVEL_INGEST_ONLY"] or conf["TRAVEL_PUBLIC_SCOPE"] == "all"
    if hsts_required and conf["SECURE_HSTS_SECONDS"] <= 0:
        problems.append("DJANGO_HSTS_SECONDS must be positive")
    if not (conf["SESSION_COOKIE_SECURE"] and conf["CSRF_COOKIE_SECURE"]):
        problems.append("DJANGO_SECURE_COOKIES must be true")
    if not conf["TRAVEL_PUBLIC_HOSTS"]:
        problems.append("TRAVEL_PUBLIC_HOSTS must name the public host name")
    if LOCAL_NAMES & {_bracketed(host) for host in conf["TRAVEL_PUBLIC_HOSTS"]}:
        problems.append("TRAVEL_PUBLIC_HOSTS must not name localhost or a loopback address")
    allowed = conf["ALLOWED_HOSTS"]
    if "*" in allowed or any(host.startswith(".") for host in allowed):
        problems.append("DJANGO_ALLOWED_HOSTS must not contain '*' or '.domain' wildcards")
    if (conf["RATELIMIT_CLIENT_IP_HEADER"] or "").lower() != CLIENT_IP_HEADER.lower():
        problems.append(f"RATELIMIT_CLIENT_IP_HEADER must be {CLIENT_IP_HEADER}")
    if not conf["SECURE_CONTENT_TYPE_NOSNIFF"]:
        problems.append("SECURE_CONTENT_TYPE_NOSNIFF must be true")
    if conf["SECURE_REFERRER_POLICY"] != "same-origin":
        problems.append("SECURE_REFERRER_POLICY must be same-origin")
    if conf["X_FRAME_OPTIONS"] != "DENY":
        problems.append("X_FRAME_OPTIONS must be DENY")
    csp = conf["SECURE_CSP"] or {}
    if not csp.get("default-src") or csp.get("frame-ancestors") != ["'none'"]:
        problems.append("SECURE_CSP must set default-src and frame-ancestors 'none'")
    missing = [name for name in REQUIRED_MIDDLEWARE if name not in conf["MIDDLEWARE"]]
    if missing:
        problems.append("MIDDLEWARE must include " + ", ".join(missing))
    if conf["DATA_UPLOAD_MAX_MEMORY_SIZE"] is None or conf["TRAVEL_UPLOAD_MAX_BYTES"] <= 0:
        problems.append("upload size limits must be set")
    if conf["OIDC_BACKCHANNEL_URL"]:
        problems.append("OIDC_BACKCHANNEL_URL is for development only (D-57)")
    issuer = conf["OIDC_ISSUER"]
    if issuer and not issuer.startswith("https://"):
        problems.append("OIDC_ISSUER must be an https:// address (no mock provider)")
    # The ingest-only service never signs anyone in (compose.prod.yaml blanks its secret).
    if issuer and not conf["TRAVEL_INGEST_ONLY"]:
        if not (conf["OIDC_CLIENT_ID"] and conf["OIDC_CLIENT_SECRET"]):
            problems.append(
                "OIDC_CLIENT_ID and OIDC_CLIENT_SECRET must be set (a confidential client)"
            )
    if not conf["OIDC_REQUIRED_GROUP"]:
        problems.append("OIDC_REQUIRED_GROUP must name the app's group (travel-users)")
    if not conf["OIDC_SECOND_FACTOR_AMR"]:
        problems.append("OIDC_SECOND_FACTOR_AMR must list the second-factor methods (G-5)")
    return problems


def _bracketed(host: str) -> str:
    """A host as request_domain spells it: IPv6 addresses in brackets."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host
