"""Milestone 1.4: OIDC login, re-authentication, logout, login wall, API authentication."""

import time

import pytest
from authlib.integrations.base_client.errors import OAuthError
from django.http import HttpResponseRedirect
from django.urls import URLPattern, URLResolver, get_resolver
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from tests.factories import UserFactory
from tests.helpers import as_owner
from travel.accounts import oidc
from travel.accounts.models import Role, User
from travel.core.loginwall import is_public_path
from travel.core.rls import rls_context
from travel.trips.models import Purpose

pytestmark = pytest.mark.django_db

ISSUER = "https://idp.example.test/application/o/travel/"
CLIENT_ID = "travel-web"
COMPANION_ID = "travel-android"


class FakeIdp:
    """Stands in for Authlib's client: records redirects, returns preset verified claims."""

    def __init__(self):
        self.redirects: list[dict] = []
        self.fail = False
        self.claims = {
            "iss": ISSUER,
            "sub": "subject-1",
            "email": "member@example.test",
            "name": "Synthetic Member",
            "groups": ["travel-users"],
        }

    def authorize_redirect(self, request, redirect_uri, **kwargs):
        self.redirects.append({"redirect_uri": redirect_uri, **kwargs})
        return HttpResponseRedirect("https://idp.example.test/authorize")

    def authorize_access_token(self, request):
        if self.fail:
            raise OAuthError(error="mismatching_state")
        return {"userinfo": dict(self.claims), "id_token": "header.payload.sig"}

    def load_server_metadata(self):
        return {
            "end_session_endpoint": "https://idp.example.test/end-session/",
            "jwks_uri": "https://idp.example.test/jwks/",
        }


@pytest.fixture
def idp(monkeypatch, settings):
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_CLIENT_ID = CLIENT_ID
    settings.OIDC_REQUIRED_GROUP = "travel-users"
    settings.OIDC_ACCEPTED_ISSUERS = [ISSUER]
    settings.OIDC_ACCEPTED_AUDIENCES = [CLIENT_ID, COMPANION_ID]
    fake = FakeIdp()
    monkeypatch.setattr(oidc, "client", lambda: fake)
    return fake


def sign_in(client, idp, **claims):
    idp.claims.update(claims)
    client.get("/auth/login")
    return client.get("/auth/callback?code=c&state=s")


def owner_lookup(**filters):
    with as_owner():
        return User.objects.filter(**filters).first()


# --- Login ----------------------------------------------------------------------------------


def test_login_redirects_to_provider_and_keeps_a_safe_next(client, idp):
    response = client.get("/auth/login?next=/trips/5")
    assert response.status_code == 302
    assert response["Location"].startswith("https://idp.example.test/authorize")
    assert idp.redirects[-1]["redirect_uri"].endswith("/auth/callback")
    assert client.session["login_next"] == "/trips/5"


def test_login_rejects_open_redirects(client, idp):
    client.get("/auth/login?next=https://evil.example/")
    assert client.session["login_next"] == "/"


def test_first_login_creates_a_member_and_seeds_purposes(client, idp):
    client.get("/auth/login?next=/welcome")
    response = client.get("/auth/callback?code=c&state=s")
    assert response.status_code == 302
    assert response["Location"] == "/welcome"
    user = owner_lookup(oidc_issuer=ISSUER, oidc_sub="subject-1")
    assert user.role == Role.MEMBER
    assert user.email == "member@example.test"
    assert not user.has_usable_password()
    with as_owner():
        assert Purpose.objects.filter(owner=user).count() == 7
        assert Purpose.objects.get(owner=user, name="Work").default_visibility == "private"
    me = client.get("/api/v1/me").json()
    assert me["email"] == "member@example.test"
    assert client.session["auth_at"] <= time.time()


def test_returning_user_is_matched_by_issuer_and_subject_not_email(client, idp):
    sign_in(client, idp)
    client.post("/auth/logout")  # needs CSRF in real browsers; test client skips the check
    sign_in(client, idp, name="Renamed Member")
    with as_owner():
        assert User.objects.count() == 1
        assert User.objects.get().display_name == "Renamed Member"


def test_users_outside_the_app_group_are_refused(client, idp):
    response = sign_in(client, idp, groups=["other-app-users"])
    assert response.status_code == 403
    assert owner_lookup() is None
    assert client.get("/api/v1/me").status_code == 401


def test_same_email_from_a_different_identity_is_refused(client, idp):
    with as_owner():
        UserFactory(email="member@example.test", oidc_sub="someone-else")
    response = sign_in(client, idp)
    assert response.status_code == 403
    assert b"already exists" in response.content


def test_deactivated_accounts_cannot_log_in(client, idp):
    with as_owner():
        UserFactory(
            email="member@example.test", oidc_issuer=ISSUER, oidc_sub="subject-1", is_active=False
        )
    assert sign_in(client, idp).status_code == 403


def test_provider_errors_do_not_log_in(client, idp):
    idp.fail = True
    response = sign_in(client, idp)
    assert response.status_code == 400
    assert client.get("/api/v1/me").status_code == 401


def test_new_accounts_cannot_start_as_admin(idp):
    with pytest.raises(Exception, match="cannot start as Admin"), rls_context(None, ctx="auth"):
        User.objects.create(email="x@example.test", role=Role.ADMIN, oidc_sub="x")


# --- Re-authentication and logout -------------------------------------------------------------


def test_reauth_forces_a_fresh_login_and_records_the_time(client, idp):
    sign_in(client, idp)
    session = client.session
    session["auth_at"] = int(time.time()) - 3600
    session.save()
    response = client.get("/auth/reauth?next=/admin/requests/1")
    assert response.status_code == 302
    assert idp.redirects[-1]["prompt"] == "login"
    assert idp.redirects[-1]["max_age"] == 0
    response = client.get("/auth/callback?code=c&state=s")
    assert response["Location"] == "/admin/requests/1"
    assert time.time() - client.session["auth_at"] < 5


def test_reauth_as_a_different_user_logs_out(client, idp):
    sign_in(client, idp)
    client.get("/auth/reauth")
    idp.claims.update(sub="subject-2", email="other@example.test")
    response = client.get("/auth/callback?code=c&state=s")
    assert response.status_code == 403
    assert client.get("/api/v1/me").status_code == 401


def test_reauth_requires_a_session(client, idp):
    response = client.get("/auth/reauth")
    assert response.status_code == 302
    assert response["Location"].startswith("/auth/login")


def test_logout_is_post_only_and_ends_the_provider_session(client, idp):
    sign_in(client, idp)
    assert client.get("/auth/logout").status_code == 405
    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert response["Location"].startswith("https://idp.example.test/end-session/?")
    assert "id_token_hint=header.payload.sig" in response["Location"]
    assert client.get("/api/v1/me").status_code == 401


def test_has_recent_auth(rf, idp):
    from django.contrib.sessions.backends.db import SessionStore

    from travel.accounts.views import has_recent_auth

    request = rf.get("/")
    request.session = SessionStore()
    with as_owner():
        request.user = UserFactory()
    request.session["auth_at"] = int(time.time()) - 10
    assert has_recent_auth(request)
    request.session["auth_at"] = int(time.time()) - 3600
    assert not has_recent_auth(request)


# --- Login wall ---------------------------------------------------------------------------------


def _sample_paths(resolver=None, prefix=""):
    resolver = resolver or get_resolver()
    for entry in resolver.url_patterns:
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            yield from _sample_paths(entry, route)
        elif isinstance(entry, URLPattern):
            path = "/" + route.lstrip("^").rstrip("$")
            for converter, sample in (
                ("<int:", "1"),
                ("<str:", "x"),
                ("<slug:", "x"),
                ("<uuid:", "00000000-0000-0000-0000-000000000000"),
                ("<path:", "x"),
                ("<", "x"),
            ):
                while converter in path:
                    start = path.index(converter)
                    path = path[:start] + sample + path[path.index(">", start) + 1 :]
            yield path


def test_every_non_public_route_rejects_anonymous_requests(client, idp):
    checked = []
    for path in _sample_paths():
        if is_public_path(path):
            continue
        response = client.get(path)
        if path.startswith("/api/"):
            assert response.status_code == 401, path
        else:
            assert response.status_code == 302, path
            assert response["Location"].startswith("/auth/login"), path
        checked.append(path)
    assert "/api/v1/me" in checked
    assert "/auth/reauth" in checked


def test_public_routes_answer_anonymous_requests(client, idp):
    assert client.get("/").status_code == 200
    assert client.get("/healthz").status_code == 200


# --- API authentication -------------------------------------------------------------------------


def test_api_requires_authentication(client, idp):
    assert client.get("/api/v1/me").status_code == 401


def test_api_session_writes_need_csrf(idp):
    from django.test import Client

    browser = Client(enforce_csrf_checks=True)
    sign_in(browser, idp)
    assert browser.post("/api/v1/me/privacy-ack").status_code == 403
    browser.get("/")  # landing page renders a CSRF token -> cookie
    token = browser.cookies["csrftoken"].value
    response = browser.post("/api/v1/me/privacy-ack", HTTP_X_CSRFTOKEN=token)
    assert response.status_code == 200
    assert response.json()["privacy_notice_ack_at"] is not None


@pytest.fixture
def signing_key(monkeypatch, idp):
    key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
    monkeypatch.setattr(oidc, "jwks", lambda: KeySet([key]))
    return key


def bearer_token(key, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "subject-1",
        "aud": COMPANION_ID,
        "iat": now,
        "exp": now + 300,
        **overrides,
    }
    return jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)


@pytest.fixture
def companion_user(idp):
    with as_owner():
        return UserFactory(email="member@example.test", oidc_issuer=ISSUER, oidc_sub="subject-1")


def test_bearer_token_authenticates_an_existing_user(client, signing_key, companion_user):
    token = bearer_token(signing_key)
    response = client.get("/api/v1/me", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 200
    assert response.json()["id"] == companion_user.pk


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "some-other-app"},
        {"iss": "https://evil.example/"},
        {"exp": int(time.time()) - 600},
        {"sub": "unknown-subject"},
    ],
    ids=["wrong-audience", "wrong-issuer", "expired", "unknown-user"],
)
def test_bad_bearer_tokens_are_rejected(client, signing_key, companion_user, overrides):
    token = bearer_token(signing_key, **overrides)
    assert client.get("/api/v1/me", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401


def test_bearer_token_signed_by_another_key_is_rejected(client, signing_key, companion_user):
    other = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
    token = bearer_token(other)
    assert client.get("/api/v1/me", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401


def test_bearer_token_of_deactivated_user_is_rejected(client, signing_key, companion_user):
    with as_owner():
        User.objects.filter(pk=companion_user.pk).update(is_active=False)
    token = bearer_token(signing_key)
    assert client.get("/api/v1/me", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401


# --- Bootstrap command ------------------------------------------------------------------------


@pytest.mark.as_owner
def test_set_role_command_promotes_the_admin():
    from django.core.management import call_command

    user = UserFactory(email="adam@example.test")
    call_command("set_role", "adam@example.test", "admin")
    user.refresh_from_db()
    assert user.role == Role.ADMIN


def test_dev_back_channel_rewrites_url_and_keeps_public_host(settings, monkeypatch):
    import requests
    from requests.adapters import HTTPAdapter

    settings.OIDC_ISSUER = "http://192.0.2.10:8781/default"
    settings.OIDC_BACKCHANNEL_URL = "http://oidc:8080"
    sent = {}

    def fake_send(self, request, **kwargs):
        sent["url"], sent["host"] = request.url, request.headers.get("Host")
        return requests.Response()

    monkeypatch.setattr(HTTPAdapter, "send", fake_send)
    session = oidc._mount_back_channel(requests.Session())
    adapter = session.get_adapter("http://192.0.2.10:8781/default/jwks")
    adapter.send(requests.Request("GET", "http://192.0.2.10:8781/default/jwks").prepare())
    assert sent == {"url": "http://oidc:8080/default/jwks", "host": "192.0.2.10:8781"}


def test_no_back_channel_in_production(settings):
    import requests

    settings.OIDC_BACKCHANNEL_URL = ""
    session = oidc._mount_back_channel(requests.Session())
    assert not any(isinstance(a, oidc._BackChannelAdapter) for a in session.adapters.values())
