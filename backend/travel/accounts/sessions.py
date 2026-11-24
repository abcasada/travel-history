"""How long a browser session lasts without the provider (F-3, D-108, D-122).

A Django session is good for `DJANGO_SESSION_AGE` (14 days), but whether its account may still
use the app is the provider's call: Authentik's `travel-users` group and whether the Authentik
user is active. The app learns either only from a fresh ID token. So the callback stamps the
session with the time the provider last vouched for it, and once that is older than
`OIDC_SESSION_RECHECK_SECONDS` the session is due: reads are answered as signed out (pages
redirect to sign-in, the API answers 401). The sign-in goes back through Authentik, which
answers without asking anything while its own session lives, and the callback checks the group
and the second factor again. An account outside the group gets no new session.

A save that meets the check (D-122): for a grace period after the check falls due, writes
(POST, PUT, PATCH, DELETE) still go through and the session is kept, so a form filled in before
the check isn't lost to it, and a read in between (a refetch, another tab) doesn't end the
session under the next write. Reads start the sign-in as before (the SPA's redirect, D-120).
Past the grace every request ends the session.
"""

from __future__ import annotations

import enum
import time

from django.conf import settings
from django.http import HttpRequest

CHECKED_AT = "oidc_checked_at"
# Not re-checked: the callback renews the stamp itself (and needs the session's sign-in state),
# and signing out needs the stored ID token for the provider's end-session redirect.
EXEMPT_PATHS = frozenset({"/auth/callback", "/auth/logout"})
# The SPA matches this sentence exactly to sign in again at once (frontend/src/auth/recheck.ts,
# D-120): change both together.
DUE_DETAIL = "sign in again: the session needs a fresh check with the sign-in provider"
# Only these keep working through the grace. Every other method (GET, HEAD, OPTIONS, anything
# unknown) counts as a read and starts the sign-in.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Finishing a save needs minutes, not the interval: a longer interval (production allows up to
# a day) doesn't stretch the grace past an hour.
MAX_GRACE_SECONDS = 3600


class Recheck(enum.Enum):
    ALLOW = "allow"  # vouched for recently enough, or a write within the grace
    REFUSE = "refuse"  # due: this request is answered as signed out; the session stays
    END = "end"  # past the grace, or never stamped: the session ends


def grace_seconds() -> int:
    """How long after the check falls due writes still go through (D-122)."""
    return min(settings.OIDC_SESSION_RECHECK_SECONDS, MAX_GRACE_SECONDS)


def mark_checked(request: HttpRequest) -> None:
    """The provider has just vouched for this session (a validated ID token at the callback)."""
    request.session[CHECKED_AT] = int(time.time())


def recheck(request: HttpRequest) -> Recheck:
    """What the provider check means for this request of a signed-in session. Sessions without
    a stamp (from before this check, or made outside the callback) have no time to measure a
    grace from, so they end."""
    limit = settings.OIDC_SESSION_RECHECK_SECONDS
    if limit <= 0 or request.path_info in EXEMPT_PATHS:
        return Recheck.ALLOW
    checked = request.session.get(CHECKED_AT)
    if not isinstance(checked, int) or isinstance(checked, bool):
        return Recheck.END
    age = time.time() - checked
    if age <= limit:
        return Recheck.ALLOW
    if age > limit + grace_seconds():
        return Recheck.END
    return Recheck.ALLOW if request.method in WRITE_METHODS else Recheck.REFUSE
