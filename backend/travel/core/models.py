from django.db import models


class RateLimitBucket(models.Model):
    """Fixed-window request counter shared by all web workers (PLAN.md D-10; no Redis).
    `key` is a hash of the limited subject (IP, token, user) — never the raw value."""

    key = models.CharField(max_length=128)
    window_start = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["key", "window_start"], name="ratelimit_unique_window")
        ]
        indexes = [models.Index(fields=["window_start"], name="ratelimit_window_idx")]

    def __str__(self) -> str:
        return f"{self.key}@{self.window_start:%Y-%m-%dT%H:%M}"
