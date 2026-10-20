"""Serves the built single-page app under /app/ (production image). Static files (JS, CSS,
icons, manifest, service worker) are served by WhiteNoise from SPA_ROOT; this view returns
index.html for client-side routes. It sits behind the login wall."""

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse
from django.views.decorators.http import require_GET


@require_GET
def spa_index(request: HttpRequest, path: str = "") -> HttpResponse:  # noqa: ARG001
    index = settings.SPA_ROOT / "app" / "index.html"
    if not index.exists():
        return HttpResponse(
            "The frontend is served by the Vite dev server in development: open port 5173 /app/.",
            content_type="text/plain",
            status=404,
        )
    response = FileResponse(index.open("rb"), content_type="text/html")
    response["Cache-Control"] = "no-cache"
    return response
