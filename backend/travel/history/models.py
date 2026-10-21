"""Raw history: original uploads, import batches, append-only points, versioned Timeline
segments, coverage, and home periods (PLAN.md §5.5-5.6). Trips reference time ranges of this
data; they never copy points."""

import uuid

from django.conf import settings
from django.contrib.gis.db import models as gis
from django.contrib.postgres.fields import ArrayField, DateTimeRangeField
from django.contrib.postgres.indexes import BrinIndex, GistIndex
from django.db import models
from django.db.models import F, Func, Q, Value

from travel.core.choices import DatePrecision

User = settings.AUTH_USER_MODEL


class RawFile(models.Model):
    """The original upload, byte-for-byte (zstd-compressed on the HDD), read-only."""

    class UploadedVia(models.TextChoices):
        WEB = "web", "Web"
        COMPANION = "companion", "Android companion"
        API = "api", "API"

    owner = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="raw_files")
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_path = models.CharField(max_length=500)
    compression = models.CharField(max_length=16, default="zstd")
    compressed_size = models.BigIntegerField()
    uploaded_via = models.CharField(
        max_length=16, choices=UploadedVia.choices, default=UploadedVia.WEB
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "sha256"], name="rawfile_unique_per_owner")
        ]

    def __str__(self) -> str:
        return f"{self.original_name} ({self.sha256[:12]})"


class ImportBatch(models.Model):
    class Kind(models.TextChoices):
        GOOGLE_TIMELINE = "google_timeline", "Google Timeline"
        FLIGHTS_TEMPLATE = "flights_template", "Flights (template)"
        MYFLIGHTRADAR24 = "myflightradar24", "MyFlightRadar24"
        FLIGHTY = "flighty", "Flighty"
        APPINTHEAIR = "appintheair", "App in the Air"
        TRIPIT = "tripit", "TripIt"
        JETLOG = "jetlog", "JetLog"
        BYAIR = "byair", "byAir"
        GPX = "gpx", "GPX"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        DONE = "done", "Done"
        DUPLICATE = "duplicate", "Identical file already imported"
        UNSUPPORTED = "unsupported", "No importer for this format yet"
        FAILED = "failed", "Failed"

    owner = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="import_batches")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    raw_file = models.ForeignKey(
        RawFile, null=True, blank=True, on_delete=models.DO_NOTHING, related_name="batches"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    summary = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.kind} import {self.pk} ({self.status})"


class UploadSession(models.Model):
    """A resumable chunked upload (PLAN.md §17, D-33): chunks of at most `chunk_size` bytes are
    appended in order to a part file on the HDD; on completion the worker stores the raw file
    and starts the import. Shared by the web app and the Android companion."""

    class Status(models.TextChoices):
        OPEN = "open", "Receiving chunks"
        COMPLETE = "complete", "Complete"
        ABORTED = "aborted", "Aborted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="+")
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    kind = models.CharField(max_length=32, choices=ImportBatch.Kind.choices)
    total_size = models.BigIntegerField()
    chunk_size = models.PositiveIntegerField()
    received_bytes = models.BigIntegerField(default=0)
    next_index = models.PositiveIntegerField(default=0)
    last_chunk_sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    uploaded_via = models.CharField(
        max_length=16, choices=RawFile.UploadedVia.choices, default=RawFile.UploadedVia.WEB
    )
    import_batch = models.ForeignKey(
        ImportBatch, null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"upload {self.filename} ({self.received_bytes}/{self.total_size})"


class PointSource(models.TextChoices):
    OWNTRACKS = "owntracks", "OwnTracks"
    OVERLAND = "overland", "Overland"
    GPSLOGGER = "gpslogger", "GPSLogger"
    COLOTA = "colota", "Colota"
    GOOGLE_RAW = "google_raw", "Google raw signal"
    GOOGLE_PATH = "google_path", "Google timeline path"
    GPX = "gpx", "GPX"
    OTHER = "other", "Other"


class LocationPoint(models.Model):
    """Append-only raw point (no UPDATE: trigger + revoked privilege)."""

    id = models.BigAutoField(primary_key=True)
    owner = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="+", db_index=False)
    ts = models.DateTimeField()
    geom = gis.PointField(srid=4326)
    accuracy_m = models.FloatField(null=True, blank=True)
    altitude_m = models.FloatField(null=True, blank=True)
    speed_mps = models.FloatField(null=True, blank=True)
    course_deg = models.FloatField(null=True, blank=True)
    battery_pct = models.SmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=16, choices=PointSource.choices)
    # DO_NOTHING (a plain FK that refuses the delete), never SET_NULL: nulling the column would be
    # an UPDATE, which the append-only trigger rejects. Device tokens are revoked, not deleted.
    device = models.ForeignKey(
        "accounts.DeviceToken", null=True, blank=True, on_delete=models.DO_NOTHING, related_name="+"
    )
    import_batch = models.ForeignKey(
        ImportBatch, null=True, blank=True, on_delete=models.DO_NOTHING, related_name="+"
    )
    received_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "source", "device", "ts"],
                name="point_dedupe",
                nulls_distinct=False,
            )
        ]
        indexes = [
            models.Index(fields=["owner", "ts"], name="point_owner_ts_idx"),
            BrinIndex(fields=["ts"], name="point_ts_brin"),
        ]

    def __str__(self) -> str:
        return f"point {self.pk} @ {self.ts:%Y-%m-%d %H:%M}"


class TimelineSegment(models.Model):
    """One version of a Google Timeline segment. Versions are append-only; only `is_current` and
    `superseded_by` may change (trigger). A lineage groups versions of the same real segment."""

    class Kind(models.TextChoices):
        VISIT = "visit", "Visit"
        ACTIVITY = "activity", "Activity"
        PATH = "path", "Path"
        MEMORY = "memory", "Memory"

    owner = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="+", db_index=False)
    lineage_id = models.UUIDField()
    version = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    superseded_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    start_utc = models.DateTimeField()
    end_utc = models.DateTimeField()
    time_range = models.GeneratedField(
        expression=Func(F("start_utc"), F("end_utc"), Value("[]"), function="tstzrange"),
        output_field=DateTimeRangeField(),
        db_persist=True,
    )
    utc_offset_min = models.SmallIntegerField(null=True, blank=True)
    # Google nests visits (a shop inside a mall); versions only match at the same level.
    hierarchy_level = models.PositiveSmallIntegerField(default=0)
    place_id = models.CharField(max_length=255, blank=True)
    semantic_type = models.CharField(max_length=32, blank=True)
    activity_type = models.CharField(max_length=32, blank=True)
    probability = models.FloatField(null=True, blank=True)
    geom = gis.GeometryField(srid=4326, null=True, blank=True)
    distance_m = models.FloatField(null=True, blank=True)
    data = models.JSONField()
    fingerprint = models.CharField(max_length=64)
    import_batch = models.ForeignKey(
        ImportBatch, null=True, blank=True, on_delete=models.DO_NOTHING, related_name="+"
    )
    edited_in_app = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lineage_id", "version"], name="segment_version"),
            models.UniqueConstraint(
                fields=["lineage_id"], condition=Q(is_current=True), name="segment_one_current"
            ),
            models.CheckConstraint(
                condition=Q(end_utc__gte=F("start_utc")), name="segment_times_ordered"
            ),
        ]
        indexes = [
            GistIndex(fields=["owner", "time_range"], name="segment_owner_range_gist"),
            models.Index(fields=["owner", "kind", "is_current"], name="segment_owner_kind_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.start_utc:%Y-%m-%d} v{self.version}"


class PlaceHint(models.Model):
    """Home/work labels from a Timeline export (`userLocationProfile.frequentPlaces`, and visits
    whose semantic type is HOME/WORK/INFERRED_*). Hints for home detection, never decisive."""

    class Label(models.TextChoices):
        HOME = "HOME", "Home"
        WORK = "WORK", "Work"

    owner = models.ForeignKey(User, on_delete=models.DB_CASCADE, related_name="+")
    label = models.CharField(max_length=8, choices=Label.choices)
    place_id = models.CharField(max_length=255, blank=True)
    point = gis.PointField(srid=4326)
    import_batch = models.ForeignKey(
        ImportBatch, null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "label", "place_id"], name="placehint_unique")
        ]

    def __str__(self) -> str:
        return f"{self.label} hint {self.place_id}"


class CoverageReport(models.Model):
    owner = models.ForeignKey(User, on_delete=models.DB_CASCADE, related_name="+")
    day = models.DateField()
    source = models.CharField(max_length=16, choices=PointSource.choices)
    points = models.PositiveIntegerField(default=0)
    hours_with_points = models.PositiveSmallIntegerField(default=0)
    gap_hours = ArrayField(models.PositiveSmallIntegerField(), default=list, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "day", "source"], name="coverage_unique")
        ]

    def __str__(self) -> str:
        return f"{self.day} {self.source}: {self.hours_with_points}/24"


class DetectionRun(models.Model):
    owner = models.ForeignKey(User, on_delete=models.DB_CASCADE, related_name="+")
    params = models.JSONField(default=dict)
    summary = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"detection {self.pk}"


class HomePeriod(models.Model):
    class Kind(models.TextChoices):
        HOME = "home", "Home"
        LONG_STAY = "long_stay", "Long stay"

    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        DETECTED = "detected", "Detected"
        GOOGLE_HINT = "google_hint", "Google hint"

    person = models.ForeignKey(
        "accounts.Person", on_delete=models.DB_CASCADE, related_name="home_periods"
    )
    managed_by = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="+")
    point = gis.PointField(srid=4326, null=True, blank=True)
    address = models.CharField(max_length=300, blank=True)
    label = models.CharField(max_length=100, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    from_precision = models.CharField(
        max_length=16, choices=DatePrecision.choices, default=DatePrecision.DAY
    )
    to_precision = models.CharField(
        max_length=16, choices=DatePrecision.choices, default=DatePrecision.DAY
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.HOME)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CONFIRMED)
    overlap_allowed = models.BooleanField(default=False)
    shared_with_family = models.BooleanField(default=False)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    evidence = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True)
                | Q(valid_to__isnull=True)
                | Q(valid_to__gte=F("valid_from")),
                name="home_period_ordered",
            ),
            models.CheckConstraint(
                condition=Q(point__isnull=False) | ~Q(address=""),
                name="home_period_has_location",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} of {self.person_id} from {self.valid_from}"
