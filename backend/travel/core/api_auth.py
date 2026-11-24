"""Authentication for the JSON API: Django session (browser, CSRF-checked) or an OIDC bearer
access token (Android companion). Either way the request's RLS context ends up as the user."""

import requests
from ninja.security import HttpBearer, SessionAuth

from travel.accounts import oidc, provisioning
from travel.accounts.models import User
from travel.core.rls import set_context


class BrowserSession(SessionAuth):
    """Session cookie; Django Ninja checks CSRF for unsafe methods."""


class OidcBearer(HttpBearer):
    def authenticate(self, request, token: str):
        try:
            claims = oidc.validate_access_token(token)
        except (oidc.InvalidToken, requests.RequestException):
            # An unreachable provider is no user, not a 500 (F-7).
            return None
        # Each request re-checks what the token says (F-3, D-108): a token minted after the
        # account left `travel-users`, or after a password-only sign-in, is refused. A refreshed
        # access token carries the provider's current groups.
        if not (
            provisioning.has_required_group(claims) and provisioning.shows_second_factor(claims)
        ):
            return None
        set_context(None, ctx="auth")
        user = User.objects.filter(
            oidc_issuer=claims["iss"], oidc_sub=claims["sub"], is_active=True
        ).first()
        if user is None:
            # Accounts are created at the first web login (PLAN.md D-55).
            set_context(None)
            return None
        set_context(user.pk)
        request.user = user
        request.via_bearer = True  # the Android companion (e.g. raw files record their origin)
        return user


API_AUTH = [BrowserSession(), OidcBearer()]
