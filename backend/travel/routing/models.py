"""Routing proxy storage (docs/design/routing.md §13.1).

Only a short-lived cache of proposals. Saved routes live in `trips.Route` (frozen versions).
"""

from django.conf import settings
from django.db import models


class RouteRequestCache(models.Model):
    """One answered routing request, reused for identical requests by the same user for
    ROUTING_CACHE_SECONDS. Per user (RLS: own rows only) because the waypoints are that user's
    drawing; expired rows are deleted when the user routes again and by the hourly
    `routing_cache` job."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DB_CASCADE, related_name="+"
    )
    key = models.CharField(max_length=64)  # SHA-256 of the normalized request
    response = models.JSONField()  # OSRM-shaped answer plus provenance
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "key"], name="routecache_unique_key")
        ]
        indexes = [models.Index(fields=["owner", "expires_at"], name="routecache_expiry")]

    def __str__(self) -> str:
        return f"route cache {self.key[:8]}"
