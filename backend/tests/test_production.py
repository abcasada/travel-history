"""The production stack (work-order item 40a, D-96): startup hardening (auth.md §7.7), the
redirect from the other public names to the canonical one, development servers never answering
a public name, per-address limits on the public pages, and the landing page offering only
"Sign in".

The exposure guard's tracker-only rules before go-live are in test_exposure.py."""

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from django.conf import settings as django_settings
from django.test import Client

from tests.helpers import TEST_SECRET_KEY, load_settings, loaded
from travel.core import exposure

CANONICAL = "travel.example.org"
OTHER = "trips.example.org"
OWNTRACKS = "/api/v1/ingest/owntracks"
OVERLAND = "/api/v1/ingest/overland"

pytestmark = pytest.mark.django_db(databases=["default", "ratelimit"])

# --- Startup hardening ---------------------------------------------------------------------

# The production web service's environment in compose.prod.yaml (keep in step); the worker,
# migrate and tools services share it.
PROD_ENV = {
    "TRAVEL_PRODUCTION": "true",
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "",
    "DJANGO_SECURE_COOKIES": "true",
    "DJANGO_BEHIND_TLS_PROXY": "true",
    "DJANGO_SSL_REDIRECT": "true",
    "DJANGO_HSTS_SECONDS": "31536000",
    "RATELIMIT_CLIENT_IP_HEADER": "CF-Connecting-IP",
    "TRAVEL_PUBLIC_HOSTS": f"{CANONICAL},{OTHER}",
    "TRAVEL_CANONICAL_HOST": CANONICAL,
    "TRAVEL_PUBLIC_SCOPE": "tracker",
    "OIDC_ISSUER": "",
    "OIDC_BACKCHANNEL_URL": "",
    "OIDC_SESSION_RECHECK_SECONDS": "3600",
}
NAMES = [
    "DEBUG",
    "ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS",
    "SECURE_PROXY_SSL_HEADER",
    "SECURE_SSL_REDIRECT",
    "TRAVEL_SSL_REDIRECT",
    "SECURE_HSTS_SECONDS",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "TRAVEL_PRODUCTION",
    "TRAVEL_PUBLIC_HOSTS",
    "TRAVEL_CANONICAL_HOST",
    "TRAVEL_PUBLIC_SCOPE",
    "RATELIMIT_CLIENT_IP_HEADER",
    "OIDC_SESSION_RECHECK_SECONDS",
]


def load_production(**overrides: str):
    return load_settings({**PROD_ENV, **overrides}, NAMES)


def assert_refused(result, problem: str) -> None:
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert problem in result.stderr


def test_the_production_stack_starts_with_production_settings():
    result = loaded(load_production())
    assert result["DEBUG"] is False
    assert result["TRAVEL_PRODUCTION"] is True
    assert result["ALLOWED_HOSTS"] == ["localhost", "127.0.0.1", CANONICAL, OTHER]
    assert result["CSRF_TRUSTED_ORIGINS"] == [f"https://{CANONICAL}", f"https://{OTHER}"]
    assert result["SECURE_PROXY_SSL_HEADER"] == ["HTTP_X_FORWARDED_PROTO", "https"]
    assert result["TRAVEL_SSL_REDIRECT"] is True  # HttpsRedirectMiddleware (G-4, D-103)
    assert result["SECURE_SSL_REDIRECT"] is False  # Django's own can't exempt localhost
    assert result["SECURE_HSTS_SECONDS"] == 31536000
    assert result["SESSION_COOKIE_SECURE"] is True
    assert result["CSRF_COOKIE_SECURE"] is True
    assert result["TRAVEL_CANONICAL_HOST"] == CANONICAL
    assert result["TRAVEL_PUBLIC_SCOPE"] == "tracker"
    assert result["RATELIMIT_CLIENT_IP_HEADER"] == "CF-Connecting-IP"


def test_the_canonical_host_defaults_to_the_first_public_host():
    result = loaded(load_production(TRAVEL_CANONICAL_HOST=""))
    assert result["TRAVEL_CANONICAL_HOST"] == CANONICAL


def test_production_refuses_debug():
    assert_refused(load_production(DJANGO_DEBUG="true"), "DJANGO_DEBUG must be false")


def test_production_needs_hsts_once_the_whole_app_is_public():
    assert loaded(load_production(DJANGO_HSTS_SECONDS="0"))["SECURE_HSTS_SECONDS"] == 0
    assert_refused(
        load_production(DJANGO_HSTS_SECONDS="0", TRAVEL_PUBLIC_SCOPE="all"),
        "DJANGO_HSTS_SECONDS must be positive",
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    ("override", "problem"),
    [
        ({"DJANGO_BEHIND_TLS_PROXY": "false"}, "DJANGO_BEHIND_TLS_PROXY must be true"),
        ({"DJANGO_SSL_REDIRECT": "false"}, "DJANGO_SSL_REDIRECT must be true"),
        ({"DJANGO_SECURE_COOKIES": "false"}, "DJANGO_SECURE_COOKIES must be true"),
        ({"TRAVEL_PUBLIC_HOSTS": "", "TRAVEL_CANONICAL_HOST": ""}, "TRAVEL_PUBLIC_HOSTS must"),
        ({"DJANGO_ALLOWED_HOSTS": "*"}, "must not contain '*'"),
        ({"DJANGO_ALLOWED_HOSTS": ".example.org"}, "'.domain' wildcards"),
        ({"RATELIMIT_CLIENT_IP_HEADER": ""}, "RATELIMIT_CLIENT_IP_HEADER must be"),
        ({"RATELIMIT_CLIENT_IP_HEADER": "X-Forwarded-For"}, "RATELIMIT_CLIENT_IP_HEADER must"),
        ({"DJANGO_SECRET_KEY": "short"}, "DJANGO_SECRET_KEY must be a generated secret"),
        ({"DJANGO_SECRET_KEY": "x" * 49}, "DJANGO_SECRET_KEY must be a generated secret"),
        ({"DJANGO_SECRET_KEY": "abab" * 20}, "DJANGO_SECRET_KEY must be a generated secret"),
        ({"DJANGO_SECRET_KEY": "django-insecure-" + "x" * 40}, "DJANGO_SECRET_KEY must be"),
        ({"OIDC_BACKCHANNEL_URL": "http://oidc:8080"}, "OIDC_BACKCHANNEL_URL is for development"),
        ({"OIDC_ISSUER": "http://192.0.2.1:8781/default"}, "OIDC_ISSUER must be an https://"),
        ({"TRAVEL_CANONICAL_HOST": "elsewhere.example"}, "TRAVEL_CANONICAL_HOST must be one of"),
        ({"TRAVEL_PUBLIC_SCOPE": "everything"}, "TRAVEL_PUBLIC_SCOPE must be"),
        ({"TRAVEL_PUBLIC_HOSTS": f"{CANONICAL},localhost"}, "must not name localhost"),
        ({"OIDC_ISSUER": "https://auth.example.org/application/o/travel/"}, "confidential"),
        ({"OIDC_REQUIRED_GROUP": ""}, "OIDC_REQUIRED_GROUP must name"),
        ({"OIDC_SECOND_FACTOR_AMR": ""}, "OIDC_SECOND_FACTOR_AMR must list"),
    ],
)
def test_production_refuses_to_start_without_production_settings(override, problem):
    assert_refused(load_production(**override), problem)


_RESOLVE_DOCS = """
import json, sys
import django
django.setup()
from django.urls import Resolver404, resolve
found = {}
for path in sys.argv[1:]:
    try:
        found[path] = resolve(path).url_name
    except Resolver404:
        found[path] = None
print(json.dumps(found))
"""


def test_production_serves_no_api_docs_or_schema():
    """F-7: neither URL exists in production (the schema is in the repository and
    `export_openapi` builds it without them); development keeps both for signed-in sessions."""
    paths = ["/api/v1/docs", "/api/v1/openapi.json", "/api/v1/me"]
    prod = loaded(load_settings(PROD_ENV, paths, script=_RESOLVE_DOCS))
    assert prod == {"/api/v1/docs": None, "/api/v1/openapi.json": None, "/api/v1/me": "me"}
    dev = loaded(load_settings({"DJANGO_DEBUG": "false"}, paths, script=_RESOLVE_DOCS))
    assert dev["/api/v1/docs"] == "openapi-view"
    assert dev["/api/v1/openapi.json"] == "openapi-json"


def test_development_settings_skip_the_production_checks():
    result = loaded(
        load_settings({"DJANGO_DEBUG": "true", "DJANGO_SECURE_COOKIES": "false"}, NAMES)
    )
    assert result["TRAVEL_PRODUCTION"] is False


def _middleware_moved(name: str) -> list[str]:
    """MIDDLEWARE with `name` moved to the end (after WhiteNoise)."""
    return [m for m in django_settings.MIDDLEWARE if m != name] + [name]


def test_production_scope_tracker_needs_no_provider_yet():
    """Before go-live (scope `tracker`) production runs without Authentik values (40a)."""
    conf = production_conf(TRAVEL_PUBLIC_SCOPE="tracker", OIDC_ISSUER="")
    conf.update(OIDC_CLIENT_ID="", OIDC_CLIENT_SECRET="")
    assert exposure.production_problems(conf) == []


def production_conf(**overrides) -> dict:
    """Settings values as settings.py would hand them to production_problems."""
    conf = {
        name: getattr(django_settings, name)
        for name in (
            "SECURE_CONTENT_TYPE_NOSNIFF",
            "SECURE_REFERRER_POLICY",
            "X_FRAME_OPTIONS",
            "SECURE_CSP",
            "MIDDLEWARE",
            "DATA_UPLOAD_MAX_MEMORY_SIZE",
            "TRAVEL_UPLOAD_MAX_BYTES",
            "OIDC_REQUIRED_GROUP",
            "OIDC_SECOND_FACTOR_AMR",
        )
    }
    conf.update(
        DEBUG=False,
        SECRET_KEY=TEST_SECRET_KEY,
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        TRAVEL_SSL_REDIRECT=True,
        SECURE_HSTS_SECONDS=31536000,
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        TRAVEL_PUBLIC_HOSTS=[CANONICAL, OTHER],
        TRAVEL_PUBLIC_SCOPE="all",
        TRAVEL_INGEST_ONLY=False,
        ALLOWED_HOSTS=["localhost", "127.0.0.1", CANONICAL, OTHER],
        RATELIMIT_CLIENT_IP_HEADER="CF-Connecting-IP",
        OIDC_BACKCHANNEL_URL="",
        OIDC_ISSUER="https://auth.example.org/application/o/travel/",
        OIDC_CLIENT_ID="travel-web",
        OIDC_CLIENT_SECRET="synthetic-client-secret",
        OIDC_SESSION_RECHECK_SECONDS=3600,
    )
    conf.update(overrides)
    return conf


def test_production_problems_lists_nothing_for_production_settings():
    assert exposure.production_problems(production_conf()) == []


def test_the_ingest_only_service_needs_no_client_secret():
    conf = production_conf(TRAVEL_INGEST_ONLY=True, TRAVEL_PUBLIC_SCOPE="tracker")
    conf["OIDC_CLIENT_SECRET"] = ""  # compose.prod.yaml blanks it for `ingest`
    conf["OIDC_SESSION_RECHECK_SECONDS"] = 0  # it never signs anyone in
    assert exposure.production_problems(conf) == []


def test_compose_prod_forces_the_session_recheck():
    """The value the production stack runs with (compose.prod.yaml's x-prod-env)."""
    compose = Path(__file__).resolve().parents[2] / "compose.prod.yaml"
    if compose.exists():  # the backend container mounts backend/ only
        assert 'OIDC_SESSION_RECHECK_SECONDS: "3600"' in compose.read_text()
    result = loaded(load_production())
    assert result["OIDC_SESSION_RECHECK_SECONDS"] == 3600


def test_production_starts_with_the_authentik_client_configured():
    result = loaded(
        load_settings(
            {
                **PROD_ENV,
                "OIDC_ISSUER": "https://auth.example.org/application/o/travel/",
                "OIDC_CLIENT_ID": "travel-web",
                "OIDC_CLIENT_SECRET": "synthetic-client-secret",
            },
            ["OIDC_ISSUER", "OIDC_REQUIRED_GROUP", "OIDC_SECOND_FACTOR_AMR"],
        )
    )
    assert result["OIDC_REQUIRED_GROUP"] == "travel-users"
    assert result["OIDC_SECOND_FACTOR_AMR"] == ["mfa", "user"]


@pytest.mark.parametrize(
    ("override", "problem"),
    [
        ({"SECURE_CONTENT_TYPE_NOSNIFF": False}, "SECURE_CONTENT_TYPE_NOSNIFF"),
        ({"SECURE_REFERRER_POLICY": "origin"}, "SECURE_REFERRER_POLICY"),
        ({"X_FRAME_OPTIONS": "SAMEORIGIN"}, "X_FRAME_OPTIONS"),
        ({"SECURE_CSP": {}}, "SECURE_CSP"),
        ({"SECURE_CSP": {"default-src": ["'self'"]}}, "SECURE_CSP"),
        ({"MIDDLEWARE": ["django.middleware.security.SecurityMiddleware"]}, "MIDDLEWARE must"),
        ({"DATA_UPLOAD_MAX_MEMORY_SIZE": None}, "upload size limits"),
        ({"CSRF_COOKIE_SECURE": False}, "DJANGO_SECURE_COOKIES"),
        ({"SECRET_KEY": "build-only"}, "DJANGO_SECRET_KEY"),
        ({"SECURE_HSTS_SECONDS": 0}, "DJANGO_HSTS_SECONDS"),
        (
            {
                "SECURE_HSTS_SECONDS": 0,
                "TRAVEL_PUBLIC_SCOPE": "tracker",
                "TRAVEL_INGEST_ONLY": True,
            },
            "HSTS",
        ),
        ({"TRAVEL_SSL_REDIRECT": False}, "DJANGO_SSL_REDIRECT must be true"),
        (
            {"MIDDLEWARE": [m for m in django_settings.MIDDLEWARE if "HttpsRedirect" not in m]},
            "HttpsRedirectMiddleware",
        ),
        ({"TRAVEL_PUBLIC_HOSTS": [CANONICAL, "127.0.0.1"]}, "loopback"),
        ({"TRAVEL_PUBLIC_HOSTS": [CANONICAL, "::1"]}, "loopback"),
        ({"OIDC_CLIENT_SECRET": ""}, "confidential client"),
        ({"OIDC_CLIENT_ID": ""}, "confidential client"),
        ({"OIDC_REQUIRED_GROUP": ""}, "OIDC_REQUIRED_GROUP"),
        ({"OIDC_SECOND_FACTOR_AMR": []}, "OIDC_SECOND_FACTOR_AMR"),
        # F-9: scope `all` needs the sign-in provider (an https issuer and the client).
        ({"OIDC_ISSUER": ""}, "must be set once TRAVEL_PUBLIC_SCOPE=all"),
        (
            {"OIDC_ISSUER": "", "OIDC_CLIENT_ID": "", "OIDC_CLIENT_SECRET": ""},
            "must be set once TRAVEL_PUBLIC_SCOPE=all",
        ),
        ({"OIDC_ISSUER": "http://auth.example.org/o/travel/"}, "OIDC_ISSUER must be an https"),
        # F-1: CSP and X-Frame-Options must wrap WhiteNoise's responses.
        *(
            ({"MIDDLEWARE": _middleware_moved(name)}, "before WhiteNoiseMiddleware")
            for name in exposure.WRAP_WHITENOISE
        ),
        # F-3: sessions go back through the provider at least daily.
        ({"OIDC_SESSION_RECHECK_SECONDS": 0}, "OIDC_SESSION_RECHECK_SECONDS must be"),
        ({"OIDC_SESSION_RECHECK_SECONDS": 30}, "OIDC_SESSION_RECHECK_SECONDS must be"),
        ({"OIDC_SESSION_RECHECK_SECONDS": 90000}, "OIDC_SESSION_RECHECK_SECONDS must be"),
        # F-2: no 40 MB bodies by default.
        ({"DATA_UPLOAD_MAX_MEMORY_SIZE": 40 * 1024 * 1024}, "DATA_UPLOAD_MAX_MEMORY_SIZE must be"),
        (
            {"MIDDLEWARE": [m for m in django_settings.MIDDLEWARE if "bodylimit" not in m]},
            "BodySizeLimitMiddleware",
        ),
    ],
)
def test_production_problems_catch_each_missing_header_and_limit(override, problem):
    problems = exposure.production_problems(production_conf(**override))
    assert len(problems) == 1, problems
    assert problem in problems[0]


# --- The other public names redirect to the canonical one ---------------------------------


@pytest.fixture
def public(settings):
    settings.TRAVEL_PUBLIC_HOSTS = [CANONICAL, OTHER]
    settings.TRAVEL_CANONICAL_HOST = CANONICAL
    settings.TRAVEL_PUBLIC_SCOPE = "tracker"
    settings.ALLOWED_HOSTS = ["localhost", "127.0.0.1", CANONICAL, OTHER]
    settings.SECURE_HSTS_SECONDS = 31536000
    return settings


def assert_redirects_to(response, path_and_query: str) -> None:
    assert response.status_code == 301
    location = response["Location"]
    assert location == f"https://{CANONICAL}{path_and_query}"
    assert urlsplit(location).netloc == CANONICAL
    assert "Set-Cookie" not in response


@pytest.mark.parametrize("scope", ["tracker", "all"])
def test_the_other_name_redirects_to_the_same_path_on_the_canonical_host(public, scope):
    public.TRAVEL_PUBLIC_SCOPE = scope
    client = Client(HTTP_HOST=OTHER)
    for path in ("/", "/app/", "/app/trips/12", "/auth/login", "/healthz", "/api/v1/me"):
        assert_redirects_to(client.get(path, secure=True), path)
    assert_redirects_to(
        client.get("/app/trips?year=2024&q=a+b", secure=True), "/app/trips?year=2024&q=a+b"
    )
    assert_redirects_to(client.head("/", secure=True), "/")
    assert_redirects_to(client.post("/auth/logout", secure=True), "/auth/logout")
    for host in (OTHER.upper(), f"{OTHER}:443", f"{OTHER}."):
        assert_redirects_to(Client(HTTP_HOST=host).get("/x", secure=True), "/x")


def test_the_redirect_carries_the_security_headers(public):
    response = Client(HTTP_HOST=OTHER).get("/", secure=True)
    assert_redirects_to(response, "/")
    assert response["Strict-Transport-Security"].startswith("max-age=31536000")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["X-Frame-Options"] == "DENY"
    assert response["Referrer-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]


@pytest.mark.parametrize(
    "path",
    [
        "//evil.example/x",
        "/%2F%2Fevil.example",
        "/\\evil.example",
        "/x?next=https://evil.example",
        "/@evil.example",
        "/%0d%0aSet-Cookie:%20x=1",
        "/https://evil.example",
    ],
)
def test_the_redirect_is_not_an_open_redirect(public, path):
    response = Client(HTTP_HOST=OTHER).get(path, secure=True)
    assert response.status_code == 301
    location = response["Location"]
    assert location.startswith(f"https://{CANONICAL}/")
    assert urlsplit(location).netloc == CANONICAL
    assert "\r" not in location
    assert "\n" not in location
    assert "\\" not in location


def test_forwarded_host_headers_do_not_choose_the_target(public):
    response = Client(HTTP_HOST=OTHER, HTTP_X_FORWARDED_HOST="evil.example").get("/", secure=True)
    assert_redirects_to(response, "/")


def test_ingest_paths_on_the_other_name_are_served_not_redirected(public):
    client = Client(HTTP_HOST=OTHER)
    for path in (OWNTRACKS, OWNTRACKS + "/", OVERLAND, OVERLAND + "/"):
        response = client.post(path, "{}", content_type="application/json", secure=True)
        assert response.status_code == 401, path  # the view answered: no token


def test_the_canonical_host_and_other_hosts_are_not_redirected(public):
    public.TRAVEL_PUBLIC_SCOPE = "all"
    assert Client(HTTP_HOST=CANONICAL).get("/healthz", secure=True).status_code == 200
    assert Client(HTTP_HOST="localhost").get("/healthz", secure=True).status_code == 200


def test_before_go_live_the_canonical_host_still_answers_only_the_tracker_paths(public):
    response = Client(HTTP_HOST=CANONICAL).get("/", secure=True)
    assert response.status_code == 404


def test_ingest_only_and_debug_servers_never_redirect(public):
    public.TRAVEL_INGEST_ONLY = True
    assert Client(HTTP_HOST=OTHER).get("/", secure=True).status_code == 404
    public.TRAVEL_INGEST_ONLY = False
    public.DEBUG = True
    assert Client(HTTP_HOST=OTHER).get("/", secure=True).status_code == 404


# --- Development servers never answer a public name ---------------------------------------


@pytest.fixture
def dev_server(settings):
    """The dev stack: DEBUG, no public host names configured (item 40a empties them)."""
    settings.DEBUG = True
    settings.TRAVEL_PUBLIC_HOSTS = []
    settings.TRAVEL_CANONICAL_HOST = ""
    settings.ALLOWED_HOSTS = ["localhost", "127.0.0.1", "192.0.2.5", "web"]
    return settings


def test_a_dev_server_answers_unknown_hosts_with_a_bare_404(dev_server):
    for host in (CANONICAL, OTHER, "evil.example", "localhost.evil.example", ""):
        client = Client(HTTP_HOST=host) if host else Client()
        for path in ("/", "/healthz", OWNTRACKS, "/app/", "/api/v1/me", "/auth/login"):
            response = client.get(path)
            assert response.status_code == 404, f"{host} {path}"
            assert response.content == b"Not Found\n"  # never DEBUG's technical error page
    assert Client(HTTP_HOST="localhost").get("/healthz").status_code == 200
    assert Client(HTTP_HOST="192.0.2.5:8780").get("/healthz").status_code == 200


def test_a_dev_server_without_allowed_hosts_accepts_only_localhost(dev_server):
    dev_server.ALLOWED_HOSTS = []
    assert Client(HTTP_HOST="localhost").get("/healthz").status_code == 200
    assert Client(HTTP_HOST=CANONICAL).get("/healthz").status_code == 404


# --- Per-address limits on the public pages -------------------------------------------------


@pytest.fixture
def idp(monkeypatch, settings):
    """Login and callback reach a fake provider (no network)."""
    from django.http import HttpResponseRedirect

    from travel.accounts import oidc

    class Fake:
        def authorize_redirect(self, request, redirect_uri, **kwargs):
            return HttpResponseRedirect("https://idp.example.test/authorize")

        def authorize_access_token(self, request):
            from authlib.integrations.base_client.errors import OAuthError

            raise OAuthError(error="mismatching_state")

    monkeypatch.setattr(oidc, "client", Fake)
    settings.AUTH_RATE_PER_IP = 2
    settings.LANDING_RATE_PER_IP = 2
    return settings


@pytest.mark.parametrize(
    ("path", "allowed_status"),
    [("/auth/login", 302), ("/auth/callback?code=c&state=s", 400), ("/", 200)],
)
def test_public_pages_are_limited_per_address(idp, path, allowed_status):
    client = Client(REMOTE_ADDR="198.51.100.7")
    assert client.get(path).status_code == allowed_status
    assert client.get(path).status_code == allowed_status
    limited = client.get(path)
    assert limited.status_code == 429
    assert int(limited["Retry-After"]) >= 1
    other = Client(REMOTE_ADDR="198.51.100.8")
    assert other.get(path).status_code == allowed_status


def test_behind_the_tunnel_the_limit_follows_cf_connecting_ip(idp):
    idp.RATELIMIT_CLIENT_IP_HEADER = "CF-Connecting-IP"
    idp.TRAVEL_PUBLIC_HOSTS = [CANONICAL]
    idp.TRAVEL_CANONICAL_HOST = CANONICAL
    idp.TRAVEL_PUBLIC_SCOPE = "all"
    idp.ALLOWED_HOSTS = ["localhost", CANONICAL]
    tunnel = "172.18.0.1"  # every request arrives from cloudflared, naming the public host

    def visitor(address: str) -> Client:
        return Client(REMOTE_ADDR=tunnel, HTTP_HOST=CANONICAL, HTTP_CF_CONNECTING_IP=address)

    for _ in range(2):
        assert visitor("203.0.113.1").get("/auth/login", secure=True).status_code == 302
    assert visitor("203.0.113.1").get("/auth/login", secure=True).status_code == 429
    assert visitor("203.0.113.2").get("/auth/login", secure=True).status_code == 302


def test_login_and_callback_have_separate_budgets(idp):
    client = Client(REMOTE_ADDR="198.51.100.9")
    for _ in range(2):
        assert client.get("/auth/login").status_code == 302
    assert client.get("/auth/login").status_code == 429
    assert client.get("/auth/callback?code=c&state=s").status_code == 400


# --- The landing page -----------------------------------------------------------------------


def test_the_landing_page_offers_only_sign_in(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.content.decode()
    assert re.findall(r'href="([^"]*)"', html) == ["/auth/login"]
    assert "<form" not in html
    assert ">Sign in<" in html
    assert 'name="robots" content="noindex, nofollow"' in html
    assert "Set-Cookie" not in response


# --- Sign-in before exposure, over an SSH port-forward to localhost:8784 (G-4, D-103) --------

LOCAL = "localhost:8784"


@pytest.fixture
def production_web(settings):
    """The production web service's request handling (compose.prod.yaml), without DEBUG."""
    settings.DEBUG = False
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.TRAVEL_SSL_REDIRECT = True
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    settings.SECURE_HSTS_SECONDS = 31536000
    settings.RATELIMIT_CLIENT_IP_HEADER = "CF-Connecting-IP"
    settings.TRAVEL_PUBLIC_HOSTS = [CANONICAL, OTHER]
    settings.TRAVEL_CANONICAL_HOST = CANONICAL
    settings.TRAVEL_PUBLIC_SCOPE = "tracker"
    settings.ALLOWED_HOSTS = ["localhost", "127.0.0.1", CANONICAL, OTHER]
    return settings


@pytest.mark.parametrize("host", [LOCAL, "localhost", "127.0.0.1:8784", "LOCALHOST:8784"])
def test_plain_http_on_localhost_is_served_not_redirected(production_web, host):
    response = Client(HTTP_HOST=host).get("/")
    assert response.status_code == 200
    # HSTS only ever goes out over HTTPS; the other production headers stay.
    assert "Strict-Transport-Security" not in response
    assert response["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]


@pytest.mark.parametrize(
    ("host", "headers", "target"),
    [
        # Through the tunnel: the visitor used plain HTTP.
        (CANONICAL, {"HTTP_X_FORWARDED_PROTO": "http"}, f"https://{CANONICAL}/"),
        (CANONICAL, {}, f"https://{CANONICAL}/"),
        # A loopback name, but with the tunnel's headers: never treated as local.
        (LOCAL, {"HTTP_X_FORWARDED_PROTO": "http"}, f"https://{LOCAL}/"),
        (LOCAL, {"HTTP_CF_CONNECTING_IP": "203.0.113.9"}, f"https://{LOCAL}/"),
    ],
)
def test_plain_http_elsewhere_is_still_redirected_to_https(production_web, host, headers, target):
    for scope in ("tracker", "all"):
        production_web.TRAVEL_PUBLIC_SCOPE = scope
        response = Client(HTTP_HOST=host, **headers).get("/")
        assert response.status_code == 301
        assert response["Location"] == target


def test_the_redirect_keeps_path_and_query_and_refuses_unknown_hosts(production_web):
    response = Client(HTTP_HOST=CANONICAL).get("/app/trips?year=2024")
    assert response["Location"] == f"https://{CANONICAL}/app/trips?year=2024"
    assert Client(HTTP_HOST="evil.example").get("/").status_code == 400
    assert Client(HTTP_HOST="localhost.evil.example").get("/").status_code == 400
    # The container's own health check stays plain HTTP, whatever the host.
    assert Client(HTTP_HOST="127.0.0.1:8000").get("/healthz").status_code == 200


def test_https_on_the_public_name_is_unchanged(production_web):
    production_web.TRAVEL_PUBLIC_SCOPE = "all"
    response = Client(HTTP_HOST=CANONICAL).get("/", secure=True)
    assert response.status_code == 200
    assert response["Strict-Transport-Security"].startswith("max-age=31536000")


@pytest.fixture
def local_idp(monkeypatch, production_web):
    from django.http import HttpResponseRedirect

    from travel.accounts import oidc

    class Fake:
        redirect_uris: list[str] = []

        def authorize_redirect(self, request, redirect_uri, **kwargs):
            self.redirect_uris.append(redirect_uri)
            return HttpResponseRedirect("https://auth.example.org/application/o/authorize/")

        def authorize_access_token(self, request):
            return {
                "userinfo": {
                    "iss": "https://auth.example.org/application/o/travel/",
                    "sub": "synthetic-hashed-subject",
                    "email": "member@example.test",
                    "name": "Synthetic Member",
                    "groups": ["travel-users"],
                    "amr": ["pwd", "mfa"],
                },
                "id_token": "header.payload.sig",
            }

        def load_server_metadata(self):
            return {
                "end_session_endpoint": "https://auth.example.org/application/o/travel/end-session/"
            }

    fake = Fake()
    monkeypatch.setattr(oidc, "client", lambda: fake)
    production_web.OIDC_ISSUER = "https://auth.example.org/application/o/travel/"
    production_web.OIDC_CLIENT_ID = "travel-web"
    return fake


def test_signing_in_over_the_port_forward_works_with_secure_cookies(local_idp):
    browser = Client(HTTP_HOST=LOCAL, enforce_csrf_checks=True)
    response = browser.get("/auth/login?next=/app/")
    assert response.status_code == 302
    # G-4's temporary redirect URI in Authentik.
    assert local_idp.redirect_uris == [f"http://{LOCAL}/auth/callback"]
    response = browser.get("/auth/callback?code=c&state=s")
    assert response.status_code == 302
    assert response["Location"] == "/app/"
    session_cookie = response.cookies["sessionid"]
    assert session_cookie["secure"] is True  # not weakened; browsers accept it on localhost
    assert session_cookie["httponly"] is True
    assert browser.get("/api/v1/me").json()["email"] == "member@example.test"
    # CSRF checks the plain-HTTP origin of the port-forward (Origin: http://localhost:8784).
    browser.get("/")
    token = browser.cookies["csrftoken"].value
    assert browser.cookies["csrftoken"]["secure"] is True
    ok = browser.post(
        "/api/v1/me/privacy-ack", HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN=f"http://{LOCAL}"
    )
    assert ok.status_code == 200
    forged = browser.post(
        "/api/v1/me/privacy-ack", HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="https://evil.example"
    )
    assert forged.status_code == 403
    response = browser.post("/auth/logout", HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN=f"http://{LOCAL}")
    assert response.status_code == 302
    location = response["Location"]
    assert "post_logout_redirect_uri=http%3A%2F%2Flocalhost%3A8784%2F" in location


def test_the_port_forward_does_not_open_the_public_name_before_go_live(local_idp):
    assert Client(HTTP_HOST=CANONICAL).get("/auth/login", secure=True).status_code == 404
    assert Client(HTTP_HOST=CANONICAL).get("/app/", secure=True).status_code == 404
