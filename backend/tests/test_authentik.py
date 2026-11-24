"""Signing in through Authentik (work-order item 40c-1, auth.md §7.2, D-103): the real Authlib
client against a synthetic Authentik provider behind a stubbed HTTP layer, so discovery, PKCE,
the confidential client's token request and Authlib's ID-token validation all run. Claims are
shaped like Authentik's: a per-provider issuer with a trailing slash, a hashed subject,
`email_verified = false`, a list of group names, `auth_time`, `acr` and `amr` (G-5)."""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, parse_qsl, urlsplit

import pytest
import requests
from authlib.oidc.core.util import create_half_hash
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from tests.factories import UserFactory
from tests.helpers import as_owner
from travel.accounts import oidc, sessions
from travel.accounts.models import Role, User

pytestmark = pytest.mark.django_db(databases=["default", "ratelimit"])

HOST = "https://auth.example.org"
ISSUER = f"{HOST}/application/o/travel-history/"
CLIENT_ID = "synthetic-travel-web"
CLIENT_SECRET = "synthetic-client-secret"
SUBJECT = hashlib.sha256(b"synthetic-authentik-user").hexdigest()  # sub_mode hashed_user_id
DROP = object()  # leave the claim out


class FakeAuthentik:
    """Authentik's OAuth2/OpenID provider as the app sees it: the discovery document, JWKS and
    token endpoint at Authentik's paths."""

    def __init__(self):
        self.key = RSAKey.generate_key(2048, parameters={"kid": "synthetic-key", "use": "sig"})
        self.signing_key = self.key
        self.requests: list[tuple[str, str]] = []
        self.token_requests: list[dict] = []
        self.authorize: dict[str, str] = {}
        self.overrides: dict = {}
        self.unreachable = False

    def discovery(self) -> dict:
        return {
            "issuer": ISSUER,
            "authorization_endpoint": f"{HOST}/application/o/authorize/",
            "token_endpoint": f"{HOST}/application/o/token/",
            "userinfo_endpoint": f"{HOST}/application/o/userinfo/",
            "end_session_endpoint": f"{ISSUER}end-session/",
            "introspection_endpoint": f"{HOST}/application/o/introspect/",
            "revocation_endpoint": f"{HOST}/application/o/revoke/",
            "jwks_uri": f"{ISSUER}jwks/",
            "response_types_supported": ["code", "id_token", "id_token token", "code token"],
            "response_modes_supported": ["query", "fragment", "form_post"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "email", "profile"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "claims_supported": ["sub", "iss", "aud", "exp", "iat", "auth_time", "acr", "amr"],
            "code_challenge_methods_supported": ["plain", "S256"],
        }

    def id_token(self, access_token: str) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "sub": SUBJECT,
            "aud": CLIENT_ID,
            "exp": now + 300,
            "iat": now,
            "auth_time": now - 20,
            "acr": "goauthentik.io/providers/oauth2/default",
            "amr": ["pwd", "mfa"],
            "sid": "synthetic-session-id",
            "nonce": self.authorize.get("nonce", ""),
            "at_hash": create_half_hash(access_token, "RS256").decode(),
            "email": "Member@Example.test",
            "email_verified": False,  # Authentik's default (auth.md §7.2)
            "name": "Synthetic Member",
            "given_name": "Synthetic Member",
            "preferred_username": "synthetic-member",
            "nickname": "synthetic-member",
            "groups": ["authentik Admins", "travel-users"],
        }
        claims.update(self.overrides)
        claims = {name: value for name, value in claims.items() if value is not DROP}
        header = {"alg": "RS256", "kid": "synthetic-key", "typ": "JWT"}
        return jwt.encode(header, claims, self.signing_key)

    def send(self, request: requests.PreparedRequest) -> requests.Response:
        if self.unreachable:
            raise requests.ConnectionError("synthetic: provider down")
        self.requests.append((request.method, request.url))
        if request.method == "GET" and request.url == f"{ISSUER}.well-known/openid-configuration":
            return _json(request, self.discovery())
        if request.method == "GET" and request.url == f"{ISSUER}jwks/":
            return _json(request, {"keys": [self.key.as_dict(private=False)]})
        if request.method == "POST" and request.url == f"{HOST}/application/o/token/":
            body = request.body.decode() if isinstance(request.body, bytes) else request.body
            form = {name: values[0] for name, values in parse_qs(body).items()}
            self.token_requests.append(
                {"form": form, "authorization": request.headers.get("Authorization", "")}
            )
            access_token = "synthetic-access-token"
            return _json(
                request,
                {
                    "access_token": access_token,
                    "token_type": "Bearer",
                    "scope": "openid email profile",
                    "expires_in": 300,
                    "id_token": self.id_token(access_token),
                },
            )
        return _json(request, {"detail": "not found"}, status=404)


def _json(request, payload: dict, status: int = 200) -> requests.Response:
    import json

    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload).encode()
    response.headers["Content-Type"] = "application/json"
    response.url = request.url
    response.request = request
    return response


@pytest.fixture(params=[ISSUER, ISSUER.rstrip("/")], ids=["issuer-with-slash", "without-slash"])
def authentik(request, monkeypatch, settings):
    """`OIDC_ISSUER` as Adam might paste it: with Authentik's trailing slash or without."""
    settings.OIDC_ISSUER = request.param
    settings.OIDC_CLIENT_ID = CLIENT_ID
    settings.OIDC_CLIENT_SECRET = CLIENT_SECRET
    settings.OIDC_BACKCHANNEL_URL = ""
    settings.OIDC_REQUIRED_GROUP = "travel-users"
    settings.OIDC_SECOND_FACTOR_AMR = ["mfa", "user"]
    settings.OIDC_ACCEPTED_ISSUERS = [request.param]
    settings.OIDC_ACCEPTED_AUDIENCES = [CLIENT_ID]
    fake = FakeAuthentik()
    monkeypatch.setattr(
        requests.adapters.HTTPAdapter, "send", lambda _adapter, req, **_kw: fake.send(req)
    )
    oidc.reset_client()
    yield fake
    oidc.reset_client()


def start(client, fake: FakeAuthentik, path: str = "/auth/login?next=/app/") -> dict[str, str]:
    response = client.get(path)
    assert response.status_code == 302
    location = urlsplit(response["Location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == (
        f"{HOST}/application/o/authorize/"
    )
    fake.authorize = dict(parse_qsl(location.query))
    return fake.authorize


def sign_in(client, fake: FakeAuthentik, **overrides):
    fake.overrides = overrides
    query = start(client, fake)
    return client.get("/auth/callback", {"code": "synthetic-code", "state": query["state"]})


def accounts() -> list[User]:
    with as_owner():
        return list(User.objects.order_by("pk"))


def test_sign_in_through_authentik(client, authentik):
    query = start(client, authentik)
    assert query["client_id"] == CLIENT_ID
    assert query["response_type"] == "code"
    assert query["scope"] == "openid email profile"
    assert query["redirect_uri"] == "http://testserver/auth/callback"
    assert query["code_challenge_method"] == "S256"
    assert query["nonce"]
    response = client.get("/auth/callback", {"code": "synthetic-code", "state": query["state"]})
    assert response.status_code == 302
    assert response["Location"] == "/app/"

    # Discovery under the per-provider issuer, whichever way OIDC_ISSUER is written.
    assert ("GET", f"{ISSUER}.well-known/openid-configuration") in authentik.requests
    # A confidential client: client_secret_basic, plus PKCE and the same redirect URI.
    (token_request,) = authentik.token_requests
    expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    assert token_request["authorization"] == f"Basic {expected}"
    form = token_request["form"]
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "synthetic-code"
    assert form["redirect_uri"] == query["redirect_uri"]
    challenge = hashlib.sha256(form["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(challenge).rstrip(b"=").decode() == query["code_challenge"]

    (user,) = accounts()
    assert user.oidc_issuer == ISSUER  # exactly as Authentik sent it
    assert user.oidc_sub == SUBJECT
    assert user.email == "member@example.test"
    assert user.display_name == "Synthetic Member"
    assert user.role == Role.MEMBER
    assert client.session["auth_at"] <= int(time.time()) - 19  # Authentik's auth_time
    assert client.get("/api/v1/me").json()["id"] == user.pk


def test_the_same_authentik_identity_finds_the_same_account(client, authentik):
    sign_in(client, authentik)
    client.post("/auth/logout")
    response = sign_in(client, authentik, name="Renamed Member", email="new@example.test")
    assert response.status_code == 302
    (user,) = accounts()
    assert (user.display_name, user.email) == ("Renamed Member", "new@example.test")


@pytest.mark.parametrize("verified", [False, True])
def test_an_email_never_links_an_authentik_identity_to_an_account(client, authentik, verified):
    with as_owner():
        UserFactory(email="member@example.test", oidc_issuer=ISSUER, oidc_sub="someone-else")
    response = sign_in(client, authentik, email_verified=verified)
    assert response.status_code == 403
    assert b"already exists" in response.content
    assert [user.oidc_sub for user in accounts()] == ["someone-else"]


@pytest.mark.parametrize(
    ("amr", "status"),
    [
        (["pwd", "mfa"], 302),  # password + TOTP or WebAuthn (Authenticator Validation stage)
        (["user"], 302),  # a passkey (passwordless WebAuthn)
        (DROP, 302),  # Authentik recorded no method: nothing to check (G-5)
        (["pwd"], 403),  # the flow let a password alone through
        ([], 403),
        (["sc"], 403),  # a certificate alone
    ],
    ids=["password+mfa", "passkey", "no-amr", "password-only", "empty", "certificate-only"],
)
def test_sign_ins_without_a_second_factor_are_refused(client, authentik, amr, status):
    response = sign_in(client, authentik, amr=amr)
    assert response.status_code == status
    assert len(accounts()) == (1 if status == 302 else 0)
    if status == 403:
        assert b"second factor" in response.content
        assert client.get("/api/v1/me").status_code == 401


@pytest.mark.parametrize(
    "groups",
    [["authentik Admins"], DROP, "travel-users-old", [], None],
    ids=["other-group", "no-claim", "string", "empty", "null"],
)
def test_identities_outside_travel_users_are_refused(client, authentik, groups):
    response = sign_in(client, authentik, groups=groups)
    assert response.status_code == 403
    assert accounts() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": f"{HOST}/application/o/another-app/"},
        {"aud": "another-client"},
        {"exp": int(time.time()) - 600},
        {"nonce": "replayed-nonce"},
        {"at_hash": "AAAAAAAAAAAAAAAAAAAAAA"},
        {"amr": "mfa"},  # not a list
        {"auth_time": "yesterday"},
    ],
    ids=["issuer", "audience", "expired", "nonce", "at-hash", "amr-string", "auth-time"],
)
def test_tokens_that_fail_validation_are_refused_cleanly(client, authentik, overrides):
    response = sign_in(client, authentik, **overrides)
    assert response.status_code == 400
    assert accounts() == []
    assert client.get("/api/v1/me").status_code == 401


def test_a_token_signed_by_another_key_is_refused(client, authentik):
    authentik.signing_key = RSAKey.generate_key(2048, parameters={"kid": "synthetic-key"})
    assert sign_in(client, authentik).status_code == 400
    assert accounts() == []


def test_an_unreachable_authentik_answers_503(client, authentik):
    authentik.unreachable = True
    assert client.get("/auth/login").status_code == 503


def test_sign_out_ends_the_authentik_session(client, authentik):
    sign_in(client, authentik)
    id_token = client.session["id_token"]
    response = client.post("/auth/logout")
    assert response.status_code == 302
    location = urlsplit(response["Location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{ISSUER}end-session/"
    query = dict(parse_qsl(location.query))
    # Authentik checks the hint's signature and audience before it honours the redirect.
    assert query["id_token_hint"] == id_token
    assert query["post_logout_redirect_uri"] == "http://testserver/"
    assert client.get("/api/v1/me").status_code == 401


def test_reauthentication_uses_authentiks_auth_time(client, authentik):
    from travel.accounts.views import has_recent_auth

    sign_in(client, authentik)
    now = int(time.time())
    for auth_time, fresh in ((now - 5, True), (now - 3600, False), (now + 3600, True)):
        authentik.overrides = {"auth_time": auth_time}
        query = start(client, authentik, "/auth/reauth?next=/app/")
        assert (query["prompt"], query["max_age"]) == ("login", "0")
        response = client.get("/auth/callback", {"code": "c", "state": query["state"]})
        assert response.status_code == 302
        # A stale auth_time (Authentik reused its session) isn't fresh; one ahead of our clock
        # counts from now, not from the future.
        assert client.session["auth_at"] == min(auth_time, client.session["auth_at"])
        assert client.session["auth_at"] <= int(time.time())
        request = type("R", (), {"user": accounts()[0], "session": client.session})()
        assert has_recent_auth(request) is fresh


def test_bearer_tokens_match_the_issuer_with_or_without_the_slash(authentik, settings):
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": SUBJECT, "aud": CLIENT_ID, "iat": now, "exp": now + 60}
    token = jwt.encode({"alg": "RS256", "kid": "synthetic-key"}, claims, authentik.key)
    assert oidc.validate_access_token(token, KeySet([authentik.key]))["sub"] == SUBJECT
    other = jwt.encode(
        {"alg": "RS256", "kid": "synthetic-key"},
        {**claims, "iss": f"{HOST}/application/o/another-app/"},
        authentik.key,
    )
    with pytest.raises(oidc.InvalidToken, match="issuer"):
        oidc.validate_access_token(other, KeySet([authentik.key]))


# --- Bearer tokens on every request (F-3, F-7; D-107, D-108) ----------------------------------


def access_token(fake: FakeAuthentik, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": SUBJECT,
        "aud": CLIENT_ID,
        "iat": now,
        "exp": now + 300,
        "groups": ["travel-users"],
        "amr": ["pwd", "mfa"],
        **overrides,
    }
    claims = {name: value for name, value in claims.items() if value is not DROP}
    return jwt.encode({"alg": "RS256", "kid": "synthetic-key"}, claims, fake.key)


@pytest.fixture
def bearer_account(authentik):
    with as_owner():
        return UserFactory(oidc_issuer=ISSUER, oidc_sub=SUBJECT)


def me_with(client, token: str):
    return client.get("/api/v1/me", HTTP_AUTHORIZATION=f"Bearer {token}")


def test_a_bearer_token_from_travel_users_signs_in(client, authentik, bearer_account):
    response = me_with(client, access_token(authentik))
    assert response.status_code == 200
    assert response.json()["id"] == bearer_account.pk


@pytest.mark.parametrize(
    "overrides",
    [
        {"groups": ["authentik Admins"]},  # removed from travel-users: the next token says so
        {"groups": DROP},
        {"groups": "travel-users"},
        {"amr": ["pwd"]},  # a password alone
    ],
    ids=["left-the-group", "no-groups", "groups-string", "password-only"],
)
def test_a_bearer_token_outside_travel_users_is_refused(
    client, authentik, bearer_account, overrides
):
    assert me_with(client, access_token(authentik, **overrides)).status_code == 401


def test_a_deactivated_accounts_bearer_token_is_refused(client, authentik, bearer_account):
    with as_owner():
        User.objects.filter(pk=bearer_account.pk).update(is_active=False)
    assert me_with(client, access_token(authentik)).status_code == 401


def test_junk_bearer_tokens_never_reach_the_provider(client, authentik):
    for junk in ("x", "a.b", "a..c", "a.b.c.d.e"):
        assert me_with(client, junk).status_code == 401
    assert authentik.requests == []


def test_an_unreachable_provider_means_no_user_not_an_error(client, authentik, bearer_account):
    """F-7: discovery failing answered 500 and was retried on every request."""
    authentik.unreachable = True
    token = access_token(authentik)
    assert me_with(client, token).status_code == 401
    # Within the back-off the provider isn't asked again, even once it is back.
    authentik.unreachable = False
    assert me_with(client, token).status_code == 401
    assert authentik.requests == []
    oidc.reset_provider_backoff()
    assert me_with(client, token).status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/docs", "/api/v1/openapi.json"])
def test_docs_and_schema_need_a_signed_in_session(client, authentik, bearer_account, path):
    """F-7: a Bearer header gets past the login wall, but not to the docs or the schema. (In
    production neither exists: test_production.py.)"""
    assert client.get(path).status_code == 401
    assert client.get(path, HTTP_AUTHORIZATION="Bearer x").status_code == 401
    token = access_token(authentik)
    assert client.get(path, HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401
    with as_owner():
        client.force_login(bearer_account)
    assert client.get(path).status_code == 200


# --- Sessions go back through Authentik (F-3, D-108, D-122) -----------------------------------


@pytest.fixture
def recheck(authentik, settings):
    settings.OIDC_SESSION_RECHECK_SECONDS = 3600  # compose.prod.yaml's value
    return authentik


def age_session(client, seconds: int) -> None:
    session = client.session
    session[sessions.CHECKED_AT] -= seconds
    session.save()


def test_a_session_goes_back_through_authentik_after_an_hour(client, recheck):
    sign_in(client, recheck)
    assert client.get("/api/v1/me").status_code == 200
    age_session(client, 3590)
    assert client.get("/api/v1/me").status_code == 200
    age_session(client, 20)
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json() == {"detail": sessions.DUE_DETAIL}
    # Every read says so until the provider vouches again (within the grace the session stays
    # for saves on their way, D-122); pages send the browser to sign in.
    assert client.get("/api/v1/me").json() == {"detail": sessions.DUE_DETAIL}
    page = client.get("/app/trips")
    assert (page.status_code, page["Location"]) == (302, "/auth/login?next=/app/trips")
    # Authentik still vouches (its own session lives): a new session straight away.
    assert sign_in(client, recheck).status_code == 302
    assert client.get("/api/v1/me").status_code == 200
    assert len(accounts()) == 1


def put_preference(client, **headers):
    return client.put(
        "/api/v1/preferences/grace_check",
        json.dumps({"value": 1}),
        content_type="application/json",
        **headers,
    )


def test_a_save_that_meets_the_check_lands_and_the_next_read_signs_in_again(client, recheck):
    sign_in(client, recheck)
    age_session(client, 3601)
    assert put_preference(client).status_code == 200  # the form filled in before the check
    assert client.get("/api/v1/me").json() == {"detail": sessions.DUE_DETAIL}
    assert sign_in(client, recheck).status_code == 302
    assert client.get("/api/v1/preferences").json()["grace_check"] == 1


def test_past_the_grace_the_session_ends(client, recheck):
    sign_in(client, recheck)
    age_session(client, 7201)
    response = put_preference(client)
    assert (response.status_code, response.json()) == (401, {"detail": sessions.DUE_DETAIL})
    assert client.get("/api/v1/me").json() == {"detail": "authentication required"}
    assert sign_in(client, recheck).status_code == 302
    assert "grace_check" not in client.get("/api/v1/preferences").json()  # nothing written


def test_leaving_travel_users_ends_access_at_the_next_check(client, recheck):
    sign_in(client, recheck)
    age_session(client, 3601)
    assert client.get("/api/v1/me").status_code == 401
    response = sign_in(client, recheck, groups=["authentik Admins"])
    assert response.status_code == 403
    assert b"not in the group" in response.content
    assert client.get("/api/v1/me").status_code == 401
    # The refused sign-in ended the session: no grace for writes either.
    assert put_preference(client).status_code == 401
    assert len(accounts()) == 1  # the account stays; deactivate_account is the server's step


def test_when_authentik_refuses_before_the_callback_writes_end_with_the_grace(client, recheck):
    """Authentik's own group binding refuses the sign-in on its side, so the app never hears
    no: reads end an hour after the provider last vouched, writes an hour later (D-122)."""
    sign_in(client, recheck)
    age_session(client, 3601)
    assert client.get("/api/v1/me").status_code == 401
    assert put_preference(client).status_code == 200
    age_session(client, 3600)
    assert put_preference(client).status_code == 401
    assert client.get("/api/v1/me").json() == {"detail": "authentication required"}


def test_bearer_tokens_have_no_grace(client, recheck, bearer_account):
    """The grace is for browser sessions: a bearer token is checked on every request, writes
    included (D-108 (3))."""
    token = access_token(recheck)
    assert put_preference(client, HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 200
    assert me_with(client, token).status_code == 200
    gone = access_token(recheck, groups=["authentik Admins"])
    assert put_preference(client, HTTP_AUTHORIZATION=f"Bearer {gone}").status_code == 401
    assert me_with(client, gone).status_code == 401


def test_a_refused_sign_in_ends_the_browsers_session(client, recheck):
    sign_in(client, recheck)
    assert client.get("/api/v1/me").status_code == 200
    assert sign_in(client, recheck, groups=[]).status_code == 403
    assert client.get("/api/v1/me").status_code == 401  # though the old one wasn't due yet


def test_signing_out_still_ends_authentiks_session_when_the_check_is_due(client, recheck):
    sign_in(client, recheck)
    id_token = client.session["id_token"]
    age_session(client, 3601)
    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert dict(parse_qsl(urlsplit(response["Location"]).query))["id_token_hint"] == id_token


def test_sessions_without_the_providers_stamp_are_due(client, recheck):
    with as_owner():
        client.force_login(UserFactory())
    assert put_preference(client).status_code == 401  # no stamp, no grace
    assert client.get("/api/v1/me").status_code == 401


def test_development_doesnt_recheck(client, settings):
    assert settings.OIDC_SESSION_RECHECK_SECONDS == 0
    with as_owner():
        client.force_login(UserFactory())
    assert client.get("/api/v1/me").status_code == 200
