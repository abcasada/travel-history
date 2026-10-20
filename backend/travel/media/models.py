"""Trip images (PLAN.md §5.7, §16): basic local photos now (stripped re-encodes on the HDD),
Immich links later. Follows the trip's visibility."""

from django.conf import settings
from django.db import models
from django.db.models import Q

User = settings.AUTH_USER_MODEL


class Media(models.Model):
    class Source(models.TextChoices):
        LOCAL = "local", "Basic upload"
        IMMICH = "immich", "Immich"

    trip = models.ForeignKey(
        "trips.Trip", null=True, blank=True, on_delete=models.DB_CASCADE, related_name="media"
    )
    leg = models.ForeignKey(
        "trips.Leg", null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    stop = models.ForeignKey(
        "trips.Stop", null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle", null=True, blank=True, on_delete=models.DB_CASCADE, related_name="+"
    )
    author = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="media")
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.LOCAL)
    external_id = models.CharField(max_length=64, blank=True)
    display_path = models.CharField(max_length=500, blank=True)
    thumb_path = models.CharField(max_length=500, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    bytes = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    captured_tz = models.CharField(max_length=64, blank=True)
    caption = models.CharField(max_length=500, blank=True)
    public_selected = models.BooleanField(default=False)
    public_consent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(source="local") & ~Q(display_path=""))
                | (Q(source="immich") & ~Q(external_id="")),
                name="media_has_content",
            )
        ]
        indexes = [models.Index(fields=["trip", "author"], name="media_trip_author_idx")]

    def __str__(self) -> str:
        return f"{self.source} media {self.pk}"
