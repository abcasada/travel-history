"""OIDC relying party (PLAN.md §7.1): Authlib's Django client for browser logins, joserfc for
validating bearer access tokens (Android companion). The identity provider is Authentik in
production and navikt/mock-oauth2-server in development."""

from __future__ import annotations

import time
from functools import lru_cache
from urllib.parse import urlsplit

import requests
from authlib.integrations.django_client import DjangoOAuth2App, OAuth
from authlib.integrations.requests_client import OAuth2Session
from django.conf import settings
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from requests.adapters import HTTPAdapter

HTTP_TIMEOUT = 10  # seconds, for every server-to-server call to the provider


class _BackChannelAdapter(HTTPAdapter):
    """Development only (OIDC_BACKCHANNEL_URL). Browsers reach the provider at its public URL,
    but containers on this host cannot reach the host's own LAN address. Server-to-server calls
    are sent to the provider's internal URL with the public Host header, so the issuer and
    endpoint URLs the provider reports stay identical for browser and server."""

    def __init__(self, public_base: str, internal_base: str):
        super().__init__()
        self.public_base = public_base.rstrip("/")
        self.internal_base = internal_base.rstrip("/")
        self.public_host = urlsplit(public_base).netloc

    def send(self, request, **kwargs):
        if request.url.startswith(self.public_base):
            request.url = self.internal_base + request.url[len(self.public_base) :]
            request.headers["Host"] = self.public_host
        return super().send(request, **kwargs)


def _mount_back_channel(session: requests.Session) -> requests.Session:
    if settings.OIDC_BACKCHANNEL_URL and settings.OIDC_ISSUER:
        parts = urlsplit(settings.OIDC_ISSUER)
        public = f"{parts.scheme}://{parts.netloc}"
        session.mount(public, _BackChannelAdapter(public, settings.OIDC_BACKCHANNEL_URL))
    return session


class _Session(OAuth2Session):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _mount_back_channel(self)


class _App(DjangoOAuth2App):
    client_cls = _Session


_oauth = OAuth()
_oauth.oauth2_client_cls = _App


def client():
    """The registered OIDC client (state, nonce and PKCE S256 handled by Authlib)."""
    existing = _oauth._clients.get("idp")
    if existing is not None:
        return existing
    return _oauth.register(
        name="idp",
        server_metadata_url=f"{settings.OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration",
        client_id=settings.OIDC_CLIENT_ID,
        client_secret=settings.OIDC_CLIENT_SECRET,
        client_kwargs={
            "scope": "openid email profile",
            "code_challenge_method": "S256",
            "default_timeout": HTTP_TIMEOUT,
        },
    )


def metadata() -> dict:
    return client().load_server_metadata()


# --- Bearer access tokens ------------------------------------------------------------------

_JWKS_TTL = 3600


@lru_cache(maxsize=4)
def _jwks_cached(jwks_uri: str, bucket: int) -> KeySet:  # noqa: ARG001 - bucket busts the cache
    with _mount_back_channel(requests.Session()) as session:
        response = session.get(jwks_uri, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return KeySet.import_key_set(response.json())


def jwks() -> KeySet:
    return _jwks_cached(metadata()["jwks_uri"], int(time.time() // _JWKS_TTL))


class InvalidToken(Exception):
    pass


def validate_access_token(token: str, key_set: KeySet | None = None) -> dict:
    """Validate an RS256/ES256 JWT access token from the provider and return its claims."""
    try:
        decoded = jwt.decode(token, key_set or jwks(), algorithms=["RS256", "ES256"])
    except (JoseError, ValueError) as exc:
        raise InvalidToken(str(exc)) from exc
    claims = decoded.claims
    now = time.time()
    if "exp" not in claims or claims["exp"] < now - 30:
        raise InvalidToken("expired")
    if claims.get("nbf", 0) > now + 30:
        raise InvalidToken("not yet valid")
    if claims.get("iss") not in settings.OIDC_ACCEPTED_ISSUERS:
        raise InvalidToken("unexpected issuer")
    audiences = claims.get("aud")
    audiences = {audiences} if isinstance(audiences, str) else set(audiences or [])
    if not audiences & set(settings.OIDC_ACCEPTED_AUDIENCES):
        raise InvalidToken("unexpected audience")
    if not claims.get("sub"):
        raise InvalidToken("no subject")
    return claims
