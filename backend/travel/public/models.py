"""Public snapshot tables (PLAN.md §6.5). The snapshot builder is the only code that writes them
and it copies only allowlisted fields. They are the only tables the `travel_public` role can
read. No foreign keys to private tables: the snapshot stands alone."""

import uuid

from django.contrib.gis.db import models as gis
from django.db import models

from travel.core.choices import DatePrecision

# The complete set of columns a public trip page may ever see. A test compares the table's
# columns against this list, so adding a field is a deliberate, reviewed change.
PUBLIC_TRIP_FIELDS = (
    "id",
    "trip_id",
    "slug",
    "mode",
    "profile_slug",
    "title",
    "description",
    "start_date",
    "end_date",
    "date_precision",
    "times",
    "geometry",
    "legs",
    "participants",
    "notes",
    "media",
    "attribution",
    "generated_at",
)


class PublicTripSnapshot(models.Model):
    trip_id = models.BigIntegerField(unique=True)
    slug = models.CharField(max_length=22, unique=True)
    mode = models.CharField(max_length=16)  # unlisted | listed
    profile_slug = models.CharField(max_length=64, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    date_precision = models.CharField(max_length=16, choices=DatePrecision.choices)
    times = models.JSONField(null=True, blank=True)  # only if the owner enabled times
    geometry = gis.MultiLineStringField(srid=4326, null=True, blank=True)  # trimmed, simplified
    legs = models.JSONField(default=list)  # [{mode, geometry index}] for line styling only
    participants = models.JSONField(default=list)  # consenting participants' display names
    notes = models.JSONField(default=list)  # consenting authors' notes
    media = models.JSONField(default=list)  # [PublicMediaFile ids]
    attribution = models.JSONField(default=list)  # data/route attributions to display
    generated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.title


class PublicMediaFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snapshot = models.ForeignKey(
        PublicTripSnapshot, on_delete=models.DB_CASCADE, related_name="files"
    )
    variant = models.CharField(max_length=16)  # display | thumb
    path = models.CharField(max_length=500)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    caption = models.CharField(max_length=500, blank=True)

    def __str__(self) -> str:
        return f"{self.variant} {self.id}"


class PublicProfileSnapshot(models.Model):
    slug = models.SlugField(max_length=64, unique=True)
    display_name = models.CharField(max_length=150)
    bio = models.TextField(blank=True)
    avatar = models.UUIDField(null=True, blank=True)
    trips = models.JSONField(default=list)  # listed trips: [{slug, title, start_date, end_date}]
    generated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.slug
