"""The installed PWA runs under the CSP too (F-1, D-107).

WhiteNoise answers files without calling the middleware after it. It used to sit before the
CSP and X-Frame-Options middleware, so `/app/index.html`, which the service worker precaches
and answers every in-app navigation with, carried neither header after the first visit."""

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db(databases=["default", "ratelimit"])

INDEX = (
    b'<!doctype html><html><head><script type="module" src="/app/assets/index-SYNTHETIC.js">'
    b'</script></head><body><div id="root"></div></body></html>'
)


@pytest.fixture
def spa(settings, tmp_path):
    """A built SPA as the production image has it (SPA_ROOT/app/…), served by WhiteNoise."""
    app = tmp_path / "app"
    (app / "assets").mkdir(parents=True)
    (app / "index.html").write_bytes(INDEX)
    (app / "sw.js").write_bytes(b"/* SYNTHETIC service worker */")
    (app / "assets" / "index-SYNTHETIC.js").write_bytes(b"/* SYNTHETIC bundle */")
    settings.SPA_ROOT = tmp_path
    settings.WHITENOISE_ROOT = tmp_path
    return tmp_path


def assert_page_headers(response) -> None:
    csp = response["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin"


@pytest.mark.parametrize(
    "path", ["/app/index.html", "/app/sw.js", "/app/assets/index-SYNTHETIC.js"]
)
def test_files_whitenoise_serves_carry_the_csp(spa, path):
    response = Client().get(path)  # a new client loads WhiteNoise with this SPA root
    assert response.status_code == 200
    assert b"".join(response.streaming_content if response.streaming else [response.content])
    assert_page_headers(response)


def test_the_shell_from_the_view_carries_the_same_csp(spa, client, django_user_model):
    from tests.factories import UserFactory
    from tests.helpers import as_owner

    with as_owner():
        client.force_login(UserFactory())
    response = client.get("/app/trips")
    assert response.status_code == 200
    whitenoise = Client().get("/app/index.html")
    assert response["Content-Security-Policy"] == whitenoise["Content-Security-Policy"]
    assert_page_headers(response)


def test_the_middleware_order_wraps_whitenoise(settings):
    middleware = settings.MIDDLEWARE
    whitenoise = middleware.index("whitenoise.middleware.WhiteNoiseMiddleware")
    for name in (
        "django.middleware.csp.ContentSecurityPolicyMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
        "travel.core.bodylimit.BodySizeLimitMiddleware",
    ):
        assert middleware.index(name) < whitenoise, name
    assert middleware.index("travel.core.exposure.ExposureGuardMiddleware") < whitenoise
