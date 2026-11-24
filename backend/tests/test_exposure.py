"""What the internet may reach before go-live (D-73, D-85, work-order item 8): the exposure
guard (travel/core/exposure.py) and the production settings of the internet-facing service.

The public host name answers 404 on every path except the two tracker endpoints; a DEBUG
server answers nothing on it; the `ingest` service answers only the tracker endpoints whatever
the Host header says; the service refuses to start without production settings."""

import json
import time

import pytest
from django.test import Client
from django.urls import resolve

from tests.factories import UserFactory, device_token
from tests.helpers import as_owner, load_settings, loaded, sample_paths
from travel.core import exposure
from travel.history.models import LocationPoint

PUBLIC = "travel.example.org"
OWNTRACKS = "/api/v1/ingest/owntracks"
OVERLAND = "/api/v1/ingest/overland"
INGEST_PATHS = [OWNTRACKS, OWNTRACKS + "/", OVERLAND, OVERLAND + "/"]
# Beyond the URL patterns: static files and the SPA bundle (WhiteNoise), probes for common
# secrets and admin pages, and near misses of the ingest paths.
EXTRA_PATHS = [
    "/",
    "/healthz",
    "/static/x.css",
    "/app/",
    "/app/trackers",
    "/app/assets/index.js",
    "/app/manifest.webmanifest",
    "/app/sw.js",
    "/robots.txt",
    "/favicon.ico",
    "/admin/",
    "/.env",
    "/api/v1/",
    "/api/v1/openapi.json",
    "/api/v1/docs",
    "/api/v1/me",
    "/api/v1/tracking/tokens",
    "/api/v1/ingest/",
    "/api/v1/ingest",
    "/api/v1/ingest/owntracksx",
    "/api/v1/ingest/owntracks/x",
    "/api/v1/ingest/owntracks//",
    "/api/v1/ingest//owntracks",
    "/api/v1/ingest/overland/../owntracks",
    "/API/V1/INGEST/OWNTRACKS",
    "//api/v1/ingest/owntracks",
]

pytestmark = pytest.mark.django_db(databases=["default", "ratelimit"])


@pytest.fixture
def public(settings):
    """Production-like: the public host name is guarded with the default scope."""
    settings.TRAVEL_PUBLIC_HOSTS = [PUBLIC]
    settings.TRAVEL_PUBLIC_SCOPE = "tracker"
    settings.ALLOWED_HOSTS = ["localhost", "127.0.0.1", PUBLIC]
    settings.SECURE_HSTS_SECONDS = 31536000
    return settings


@pytest.fixture
def member_secret(db):
    with as_owner():
        user = UserFactory()
    _token, secret = device_token(user)
    return secret


def guarded_paths():
    paths = {path for path in sample_paths() if "ingest" not in path} | set(EXTRA_PATHS)
    return sorted(paths)


def location() -> str:
    return json.dumps({"_type": "location", "lat": 37.69, "lon": -97.34, "tst": int(time.time())})


def assert_not_found(response, path):
    assert response.status_code == 404, path
    assert response.content in (b"Not Found\n", b""), path  # HEAD responses have no body
    assert response["Cache-Control"] == "no-store"
    assert "Set-Cookie" not in response, path


def assert_security_headers(response):
    assert response["Strict-Transport-Security"].startswith("max-age=31536000")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["X-Frame-Options"] == "DENY"
    assert response["Referrer-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert response["Cross-Origin-Opener-Policy"] == "same-origin"


# --- The public host name ------------------------------------------------------------------


def test_every_other_path_on_the_public_host_is_not_found(public):
    client = Client(HTTP_HOST=PUBLIC)
    checked = 0
    for path in guarded_paths():
        for method in (client.get, client.post, client.head, client.options):
            response = method(path, secure=True)
            assert_not_found(response, f"{method.__name__} {path}")
            checked += 1
    assert checked > 100  # every URL pattern plus the extras, four methods each


def test_404s_carry_the_security_headers(public):
    response = Client(HTTP_HOST=PUBLIC).get("/", secure=True)
    assert_not_found(response, "/")
    assert_security_headers(response)


def test_tracker_endpoints_are_reachable_on_the_public_host(public, member_secret):
    client = Client(HTTP_HOST=PUBLIC)
    response = client.post(
        OWNTRACKS,
        location(),
        content_type="application/json",
        secure=True,
        HTTP_AUTHORIZATION=f"Bearer {member_secret}",
    )
    assert response.status_code == 200
    assert response.content == b"[]"
    assert_security_headers(response)
    assert "Set-Cookie" not in response
    with as_owner():
        assert LocationPoint.objects.count() == 1

    for path in INGEST_PATHS:
        refused = client.post(path, "{}", content_type="application/json", secure=True)
        assert refused.status_code == 401, path  # the view answered, not the guard
        assert_security_headers(refused)


def test_host_header_variants_are_still_the_public_host(public):
    for host in (PUBLIC.upper(), f"{PUBLIC}:443", f"{PUBLIC}.", f"{PUBLIC}.:443"):
        response = Client(HTTP_HOST=host).get("/healthz", secure=True)
        assert response.status_code == 404, host


def test_other_hosts_are_not_guarded(public):
    assert Client(HTTP_HOST="localhost").get("/healthz").status_code == 200


def test_a_debug_server_answers_nothing_on_the_public_host(public, member_secret):
    public.DEBUG = True
    client = Client(HTTP_HOST=PUBLIC)
    for path in INGEST_PATHS:
        response = client.post(
            path,
            location(),
            content_type="application/json",
            secure=True,
            HTTP_AUTHORIZATION=f"Bearer {member_secret}",
        )
        assert_not_found(response, path)
    with as_owner():
        assert LocationPoint.objects.count() == 0


def test_go_live_scope_opens_the_public_host(public):
    public.TRAVEL_PUBLIC_SCOPE = "all"
    assert Client(HTTP_HOST=PUBLIC).get("/healthz", secure=True).status_code == 200


def test_the_guard_is_on_by_default():
    from django.conf import settings

    assert settings.TRAVEL_PUBLIC_SCOPE == "tracker"
    assert settings.TRAVEL_INGEST_ONLY is False
    middleware = settings.MIDDLEWARE
    guard = middleware.index("travel.core.exposure.ExposureGuardMiddleware")
    assert middleware.index("django.middleware.security.SecurityMiddleware") < guard
    assert guard < middleware.index("whitenoise.middleware.WhiteNoiseMiddleware")
    assert middleware[0] == "travel.tracking.middleware.IngestTokenScrubMiddleware"


def test_the_allowlist_matches_the_ingest_routes():
    for path in INGEST_PATHS:
        assert exposure.INGEST_PATH.fullmatch(path), path
        assert resolve(path).url_name in ("ingest-owntracks", "ingest-overland"), path
    for path in guarded_paths():
        assert not exposure.INGEST_PATH.fullmatch(path), path


# --- The ingest-only service -----------------------------------------------------------------


@pytest.fixture
def ingest_only(public):
    public.TRAVEL_INGEST_ONLY = True
    return public


def test_ingest_only_answers_only_the_tracker_endpoints_whatever_the_host(ingest_only):
    for host in ("localhost", "127.0.0.1", PUBLIC):
        client = Client(HTTP_HOST=host, REMOTE_ADDR="172.18.0.1")
        for path in guarded_paths():
            assert_not_found(client.get(path, secure=True), f"{host} {path}")
        for path in INGEST_PATHS:
            response = client.post(path, "{}", content_type="application/json", secure=True)
            assert response.status_code == 401, f"{host} {path}"


def test_ingest_only_health_check_only_from_inside_the_container(ingest_only):
    inside = Client(HTTP_HOST="127.0.0.1:8000", REMOTE_ADDR="127.0.0.1")
    assert inside.get("/healthz").status_code == 200  # plain HTTP: exempt from the redirect
    gateway = Client(HTTP_HOST="127.0.0.1:8000", REMOTE_ADDR="172.18.0.1")
    assert_not_found(gateway.get("/healthz"), "/healthz from the Docker gateway")
    tunnel = Client(HTTP_HOST=PUBLIC, REMOTE_ADDR="127.0.0.1")
    assert_not_found(tunnel.get("/healthz", secure=True), "/healthz on the public host")


def test_ingest_only_ignores_the_go_live_scope(ingest_only):
    ingest_only.TRAVEL_PUBLIC_SCOPE = "all"
    assert_not_found(Client(HTTP_HOST=PUBLIC).get("/", secure=True), "/")


def test_plain_http_is_redirected_to_https_behind_the_proxy(ingest_only, member_secret):
    ingest_only.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    ingest_only.TRAVEL_SSL_REDIRECT = True  # HttpsRedirectMiddleware (D-100)
    client = Client(HTTP_HOST=PUBLIC)
    plain = client.post(
        OWNTRACKS, location(), content_type="application/json", HTTP_X_FORWARDED_PROTO="http"
    )
    assert plain.status_code == 301
    assert plain["Location"] == f"https://{PUBLIC}{OWNTRACKS}"
    secure = client.post(
        OWNTRACKS,
        location(),
        content_type="application/json",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_AUTHORIZATION=f"Bearer {member_secret}",
    )
    assert secure.status_code == 200
    assert_security_headers(secure)
    inside = Client(HTTP_HOST="127.0.0.1:8000", REMOTE_ADDR="127.0.0.1")
    assert inside.get("/healthz").status_code == 200  # the health check is exempt


# --- Production settings of the internet-facing service ------------------------------------

# The `ingest` service's environment in compose.prod.yaml (keep in step).
INGEST_ENV = {
    "TRAVEL_PRODUCTION": "true",
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "",
    "DJANGO_SECURE_COOKIES": "true",
    "DJANGO_BEHIND_TLS_PROXY": "true",
    "DJANGO_SSL_REDIRECT": "true",
    "DJANGO_HSTS_SECONDS": "31536000",
    "TRAVEL_PUBLIC_HOSTS": PUBLIC,
    "TRAVEL_PUBLIC_SCOPE": "tracker",
    "TRAVEL_INGEST_ONLY": "true",
    "RATELIMIT_CLIENT_IP_HEADER": "CF-Connecting-IP",
}
SETTING_NAMES = [
    "DEBUG",
    "ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS",
    "SECURE_PROXY_SSL_HEADER",
    "SECURE_SSL_REDIRECT",
    "TRAVEL_SSL_REDIRECT",
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SECURE_CONTENT_TYPE_NOSNIFF",
    "SECURE_REFERRER_POLICY",
    "SECURE_CROSS_ORIGIN_OPENER_POLICY",
    "X_FRAME_OPTIONS",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "TRAVEL_PUBLIC_HOSTS",
    "TRAVEL_PUBLIC_SCOPE",
    "TRAVEL_INGEST_ONLY",
    "RATELIMIT_CLIENT_IP_HEADER",
]


def load_ingest_settings(**overrides: str):
    return load_settings({**INGEST_ENV, **overrides}, SETTING_NAMES)


def test_the_ingest_service_runs_with_production_settings():
    result = loaded(load_ingest_settings())
    assert result["DEBUG"] is False
    assert result["ALLOWED_HOSTS"] == ["127.0.0.1", "localhost", PUBLIC]
    assert result["CSRF_TRUSTED_ORIGINS"] == [f"https://{PUBLIC}"]
    assert result["SECURE_PROXY_SSL_HEADER"] == ["HTTP_X_FORWARDED_PROTO", "https"]
    # The redirect (and its /healthz exemption) is HttpsRedirectMiddleware's (D-100).
    assert result["TRAVEL_SSL_REDIRECT"] is True
    assert result["SECURE_SSL_REDIRECT"] is False
    assert result["SECURE_HSTS_SECONDS"] == 31536000
    assert result["SECURE_HSTS_INCLUDE_SUBDOMAINS"] is True
    assert result["SECURE_CONTENT_TYPE_NOSNIFF"] is True
    assert result["SECURE_REFERRER_POLICY"] == "same-origin"
    assert result["SECURE_CROSS_ORIGIN_OPENER_POLICY"] == "same-origin"
    assert result["X_FRAME_OPTIONS"] == "DENY"
    assert result["SESSION_COOKIE_SECURE"] is True
    assert result["CSRF_COOKIE_SECURE"] is True
    assert result["TRAVEL_PUBLIC_HOSTS"] == [PUBLIC]
    assert result["TRAVEL_PUBLIC_SCOPE"] == "tracker"
    assert result["TRAVEL_INGEST_ONLY"] is True
    assert result["RATELIMIT_CLIENT_IP_HEADER"] == "CF-Connecting-IP"


@pytest.mark.slow
@pytest.mark.parametrize(
    ("override", "problem"),
    [
        ({"DJANGO_DEBUG": "true"}, "DJANGO_DEBUG must be false"),
        ({"DJANGO_BEHIND_TLS_PROXY": "false"}, "DJANGO_BEHIND_TLS_PROXY must be true"),
        ({"DJANGO_SSL_REDIRECT": "false"}, "DJANGO_SSL_REDIRECT must be true"),
        ({"DJANGO_HSTS_SECONDS": "0"}, "DJANGO_HSTS_SECONDS must be positive"),
        ({"DJANGO_SECURE_COOKIES": "false"}, "DJANGO_SECURE_COOKIES must be true"),
        ({"TRAVEL_PUBLIC_HOSTS": ""}, "TRAVEL_PUBLIC_HOSTS must name"),
        ({"DJANGO_ALLOWED_HOSTS": "*"}, "must not contain '*'"),
        ({"TRAVEL_PUBLIC_SCOPE": "everything"}, "TRAVEL_PUBLIC_SCOPE must be"),
    ],
)
def test_the_ingest_service_refuses_to_start_without_production_settings(override, problem):
    result = load_ingest_settings(**override)
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert problem in result.stderr


def test_the_ingest_service_needs_hsts_whatever_the_scope():
    result = load_ingest_settings(DJANGO_HSTS_SECONDS="0", TRAVEL_PUBLIC_SCOPE="tracker")
    assert result.returncode != 0
    assert "DJANGO_HSTS_SECONDS must be positive" in result.stderr
