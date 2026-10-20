"""Deny by default (PLAN.md §7.6): every path requires a logged-in user except this allowlist.
A test walks the URL resolver and checks every other route rejects anonymous requests."""

from django.http import JsonResponse
from django.shortcuts import redirect

PUBLIC_EXACT = frozenset(
    {
        "/",
        "/healthz",
        "/auth/login",
        "/auth/callback",
        "/request-access",
        "/app/manifest.webmanifest",  # fetched without cookies by browsers
        "/app/sw.js",
        "/favicon.ico",
        "/robots.txt",
    }
)
PUBLIC_PREFIXES = (
    "/app/assets/",  # hashed JS/CSS bundles (no data)
    "/app/icons/",
    "/invite/",
    "/api/v1/ingest/",  # tracker endpoints authenticate with device tokens
    "/t/",  # unlisted public trips (public renderer)
    "/u/",  # public profiles (public renderer)
    "/pm/",  # public media (stripped copies)
    "/static/",
    "/icons/",
)


def is_public_path(path: str) -> bool:
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


class LoginWallMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated or is_public_path(request.path):
            return self.get_response(request)
        if request.path.startswith("/api/"):
            # Bearer tokens (Android companion) are verified by the API's auth classes.
            if request.headers.get("Authorization", "").startswith("Bearer "):
                return self.get_response(request)
            return JsonResponse({"detail": "authentication required"}, status=401)
        return redirect(f"/auth/login?next={request.get_full_path()}")
