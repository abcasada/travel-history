"""How long a browser session lasts without the provider (F-3, D-108).

A Django session is good for `DJANGO_SESSION_AGE` (14 days), but whether its account may still
use the app is the provider's call: Authentik's `travel-users` group and whether the Authentik
user is active. The app learns either only from a fresh ID token. So the callback stamps the
session with the time the provider last vouched for it, and once that is older than
`OIDC_SESSION_RECHECK_SECONDS` the next request treats the session as signed out (it is ended):
pages redirect to sign-in, the API answers 401. The sign-in goes back through Authentik, which
answers without asking anything while its own session lives, and the callback checks the group
and the second factor again. An account outside the group gets no new session.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.http import HttpRequest

CHECKED_AT = "oidc_checked_at"
# Not re-checked: the callback renews the stamp itself (and needs the session's sign-in state),
# and signing out needs the stored ID token for the provider's end-session redirect.
EXEMPT_PATHS = frozenset({"/auth/callback", "/auth/logout"})
DUE_DETAIL = "sign in again: the session needs a fresh check with the sign-in provider"


def mark_checked(request: HttpRequest) -> None:
    """The provider has just vouched for this session (a validated ID token at the callback)."""
    request.session[CHECKED_AT] = int(time.time())


def check_due(request: HttpRequest) -> bool:
    """True when the signed-in session must go back through the provider first. Sessions
    without a stamp (from before this check, or made outside the callback) are due."""
    limit = settings.OIDC_SESSION_RECHECK_SECONDS
    if limit <= 0 or request.path_info in EXEMPT_PATHS:
        return False
    checked = request.session.get(CHECKED_AT)
    if not isinstance(checked, int) or isinstance(checked, bool):
        return True
    return time.time() - checked > limit
