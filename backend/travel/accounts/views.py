"""Login, callback, logout and re-authentication (PLAN.md §7.1). Everything else about identity
lives in the provider (Authentik): passwords, second factors, enrollment."""

import time
from urllib.parse import urlencode

import requests
from authlib.integrations.base_client.errors import OAuthError
from django.conf import settings
from django.contrib.auth import login, logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from travel.core.rls import set_context

from . import oidc
from .provisioning import AccessDenied, user_for_claims

BACKEND = "django.contrib.auth.backends.ModelBackend"


def _safe_next(request: HttpRequest, candidate: str | None) -> str:
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return "/"


def _redirect_uri(request: HttpRequest) -> str:
    return request.build_absolute_uri(reverse("auth-callback"))


def _provider_unreachable(request: HttpRequest) -> HttpResponse:
    return render(
        request, "auth_error.html", {"reason": "the sign-in service is unreachable"}, status=503
    )


@require_GET
def login_view(request: HttpRequest) -> HttpResponse:
    request.session["login_next"] = _safe_next(request, request.GET.get("next"))
    request.session.pop("reauth_user", None)
    try:
        return oidc.client().authorize_redirect(request, _redirect_uri(request))
    except requests.RequestException:
        return _provider_unreachable(request)


@require_GET
def reauth_view(request: HttpRequest) -> HttpResponse:
    """Force a fresh login at the provider (approvals and destructive admin actions)."""
    request.session["login_next"] = _safe_next(request, request.GET.get("next"))
    request.session["reauth_user"] = request.user.pk
    try:
        return oidc.client().authorize_redirect(
            request, _redirect_uri(request), prompt="login", max_age=0
        )
    except requests.RequestException:
        return _provider_unreachable(request)


@require_GET
def callback_view(request: HttpRequest) -> HttpResponse:
    try:
        token = oidc.client().authorize_access_token(request)
    except OAuthError:
        return render(request, "auth_error.html", {"reason": "login_failed"}, status=400)
    except requests.RequestException:
        return _provider_unreachable(request)
    claims = token.get("userinfo") or {}
    next_url = request.session.pop("login_next", "/")
    reauth_user = request.session.pop("reauth_user", None)
    try:
        user = user_for_claims(claims)
    except AccessDenied as denied:
        set_context(None)
        return render(request, "auth_error.html", {"reason": str(denied)}, status=403)
    if reauth_user is not None and reauth_user != user.pk:
        set_context(None)
        logout(request)
        return render(
            request, "auth_error.html", {"reason": "re-login as another user"}, status=403
        )
    login(request, user, backend=BACKEND)
    # When re-authenticating, the provider's auth_time proves the login was fresh; providers
    # that omit it (the dev mock) are trusted to have honoured prompt=login.
    request.session["auth_at"] = int(claims.get("auth_time") or time.time())
    request.session["id_token"] = token.get("id_token", "")
    return redirect(next_url)


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    id_token = request.session.get("id_token", "")
    logout(request)
    set_context(None)
    end_session = oidc.metadata().get("end_session_endpoint") if settings.OIDC_ISSUER else None
    if not end_session:
        return redirect("/")
    params = {
        "client_id": settings.OIDC_CLIENT_ID,
        "post_logout_redirect_uri": request.build_absolute_uri("/"),
    }
    if id_token:
        params["id_token_hint"] = id_token
    return redirect(f"{end_session}?{urlencode(params)}")


def has_recent_auth(request: HttpRequest, max_age: int | None = None) -> bool:
    """True if the user logged in (or re-authenticated) within max_age seconds."""
    max_age = settings.REAUTH_MAX_AGE if max_age is None else max_age
    auth_at = request.session.get("auth_at")
    return bool(request.user.is_authenticated and auth_at and time.time() - auth_at <= max_age)


def landing_view(request: HttpRequest) -> HttpResponse:
    """Public landing page; the full version (request access, explanation) comes in phase 8."""
    return render(request, "landing.html", {"user": request.user})
