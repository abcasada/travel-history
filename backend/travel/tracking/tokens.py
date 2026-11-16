"""Device tokens (PLAN.md §9.1, threat model §20): `trk_` + 32 random bytes in base64url.

The token exists in clear only in the response that creates it and in a tracker's requests.
The database stores its SHA-256 (checked: `devicetoken_hash_is_sha256`), the rate limiter an
HMAC of that hash, and nothing logs it: functions that hold it are marked
`sensitive_variables` (Django's error reports blank their locals), query-string tokens are
cut out of the request before anything else sees it (`middleware.py`), and every log line
passes through a redacting formatter (`travel/core/logredact.py`).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from dataclasses import dataclass

from django.http import HttpRequest
from django.views.decorators.debug import sensitive_variables

PREFIX = "trk_"
RANDOM_BYTES = 32
# base64url of 32 bytes without padding is 43 characters.
TOKEN_PATTERN = re.compile(r"trk_[A-Za-z0-9_-]{43}")
# What the token list shows: "trk_" plus 4 random characters (39 stay secret, ~234 bits).
DISPLAY_LENGTH = 8
MAX_AUTH_HEADER = 512


@dataclass(frozen=True, repr=False)
class NewToken:
    secret: str
    token_hash: str
    display_prefix: str


def hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


@sensitive_variables()
def generate() -> NewToken:
    secret = PREFIX + secrets.token_urlsafe(RANDOM_BYTES)
    return NewToken(
        secret=secret, token_hash=hash_token(secret), display_prefix=secret[:DISPLAY_LENGTH]
    )


def is_well_formed(candidate: str | None) -> bool:
    return bool(candidate) and TOKEN_PATTERN.fullmatch(candidate) is not None


@sensitive_variables()
def hash_from_request(request: HttpRequest) -> str | None:
    """The SHA-256 of the request's device token, or None if it carries none or a malformed one.

    Accepted, in this order: `Authorization: Bearer <token>`, `Authorization: Basic` with the
    token as the password (any user name: OwnTracks, GPSLogger, Colota), then `?token=` (some
    Overland versions only take a URL), which `IngestTokenScrubMiddleware` has already moved
    out of the query string. A request with an Authorization header is judged by the header
    alone. Only the hash leaves this function.
    """
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header:
        candidate = _from_authorization(header)
    else:
        candidate = getattr(request, "ingest_query_token", None)
    if not is_well_formed(candidate):
        return None
    return hash_token(candidate)


@sensitive_variables()
def _from_authorization(header: str) -> str | None:
    if len(header) > MAX_AUTH_HEADER:
        return None
    scheme, _, value = header.strip().partition(" ")
    scheme = scheme.lower()
    value = value.strip()
    if scheme == "bearer":
        return value
    if scheme == "basic":
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8")
        except (binascii.Error, ValueError):
            return None
        _user, separator, password = decoded.partition(":")
        return password if separator else None
    return None
