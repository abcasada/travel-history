"""Trips, legs, frozen routes, participation and contributions (PLAN.md §5.3)."""

import secrets

from django.conf import settings
from django.contrib.gis.db import models as gis
from django.contrib.postgres.fields import ArrayField, DateTimeRangeField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from travel.core.choices import DatePrecision, TravelMode, Visibility

User = settings.AUTH_USER_MODEL


def new_public_slug() -> str:
    return secrets.token_urlsafe(16)[:22]


class Purpose(models.Model):
    """User-editable list of trip purposes; seeded per user (Work, Vacation, …)."""

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="purposes")
    name = models.CharField(max_length=64)
    default_visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.PARTICIPANTS
    )
    sort = models.PositiveSmallIntegerField(default=0)
    archived = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint("owner", Lower("name"), name="purpose_unique_name_ci")
        ]
        ordering = ["sort", "name"]

    def __str__(self) -> str:
        return self.name


class Trip(models.Model):
    class Status(models.TextChoices):
        CANDIDATE = "candidate", "Candidate"
        CONFIRMED = "confirmed", "Confirmed"

    class PublicMode(models.TextChoices):
        UNLISTED = "unlisted", "Unlisted link"
        LISTED = "listed", "Listed on profile"

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        DETECTED = "detected", "Detected"
        FLIGHT_IMPORT = "flight_import", "Flight import"
        MERGED = "merged", "Merged"

    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="trips")
    title = models.CharField(max_length=200)
    purpose = models.ForeignKey(
        Purpose, null=True, blank=True, on_delete=models.SET_NULL, related_name="trips"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    date_precision = models.CharField(
        max_length=16, choices=DatePrecision.choices, default=DatePrecision.DAY
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CONFIRMED)
    visibility = models.CharField(
        max_length=16, choices=Visibility.choices, default=Visibility.PARTICIPANTS
    )
    public_mode = models.CharField(max_length=16, choices=PublicMode.choices, blank=True)
    public_slug = models.CharField(max_length=22, unique=True, default=new_public_slug)
    public_description = models.TextField(blank=True)
    public_show_times = models.BooleanField(default=False)
    privacy_zone_enabled = models.BooleanField(default=True)
    privacy_zone_radius_m = models.PositiveIntegerField(default=1000)
    cover_media = models.ForeignKey(
        "media.Media", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    notes = models.TextField(blank=True)
    photo_limit_per_contributor = models.PositiveSmallIntegerField(default=10)
    locked = models.BooleanField(default=False)
    needs_review = models.BooleanField(default=False)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    detection_fingerprint = models.CharField(max_length=64, blank=True)
    edited_in_app_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")), name="trip_dates_ordered"
            ),
            models.CheckConstraint(
                condition=(Q(visibility=Visibility.PUBLIC) & ~Q(public_mode=""))
                | (~Q(visibility=Visibility.PUBLIC) & Q(public_mode="")),
                name="trip_public_mode_iff_public",
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "start_date"], name="trip_owner_start_idx"),
            models.Index(fields=["start_date", "end_date"], name="trip_dates_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.start_date})"


class CabinClass(models.TextChoices):
    ECONOMY = "economy", "Economy"
    PREMIUM_ECONOMY = "premium_economy", "Premium economy"
    BUSINESS = "business", "Business"
    FIRST = "first", "First"
    OTHER = "other", "Other"


class Leg(models.Model):
    class ParticipantScope(models.TextChoices):
        TRIP = "trip", "Trip participants"
        AUTHOR = "author", "Only the author"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="legs")
    sequence = models.PositiveIntegerField()
    mode = models.CharField(max_length=16, choices=TravelMode.choices)
    start_utc = models.DateTimeField(null=True, blank=True)
    start_tz = models.CharField(max_length=64, blank=True)
    end_utc = models.DateTimeField(null=True, blank=True)
    end_tz = models.CharField(max_length=64, blank=True)
    time_precision = models.CharField(
        max_length=16, choices=DatePrecision.choices, default=DatePrecision.EXACT
    )
    origin_stop = models.ForeignKey(
        "trips.Stop", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    destination_stop = models.ForeignKey(
        "trips.Stop", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    origin_label = models.CharField(max_length=200, blank=True)
    destination_label = models.CharField(max_length=200, blank=True)
    vehicle = models.ForeignKey(
        "vehicles.Vehicle", null=True, blank=True, on_delete=models.SET_NULL, related_name="legs"
    )
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="legs_authored")
    is_contribution = models.BooleanField(default=False)
    participant_scope = models.CharField(
        max_length=16, choices=ParticipantScope.choices, default=ParticipantScope.TRIP
    )
    current_route = models.ForeignKey(
        "trips.Route", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    distance_m = models.FloatField(null=True, blank=True)
    # Flight fields
    airline = models.ForeignKey(
        "geo.Airline", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    flight_number = models.CharField(max_length=16, blank=True)
    origin_airport = models.ForeignKey(
        "geo.Airport", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    destination_airport = models.ForeignKey(
        "geo.Airport", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    aircraft_type = models.ForeignKey(
        "geo.AircraftType", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    aircraft_registration = models.CharField(max_length=16, blank=True)
    seat = models.CharField(max_length=8, blank=True)
    cabin_class = models.CharField(max_length=16, choices=CabinClass.choices, blank=True)
    # Provenance: references to raw data (never copies of points)
    source_segments = ArrayField(models.BigIntegerField(), default=list, blank=True)
    import_batch = models.ForeignKey(
        "history.ImportBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["trip", "sequence"],
                name="leg_unique_sequence",
                deferrable=models.Deferrable.DEFERRED,
            ),
            models.CheckConstraint(
                condition=Q(end_utc__isnull=True)
                | Q(start_utc__isnull=True)
                | Q(end_utc__gte=models.F("start_utc")),
                name="leg_times_ordered",
            ),
        ]
        ordering = ["trip", "sequence"]

    def __str__(self) -> str:
        return f"{self.trip_id}#{self.sequence} {self.mode}"


class Route(models.Model):
    """One frozen geometry version for a leg. Immutable: a trigger rejects every UPDATE; edits
    insert a new version and move `leg.current_route`. Never recomputed (CLAUDE.md rule 5)."""

    class Kind(models.TextChoices):
        GPS = "gps", "GPS"
        MAP_MATCHED = "map_matched", "Map-matched"
        ROUTED = "routed", "Routed"
        HAND_EDITED = "hand_edited", "Hand-edited"
        GREAT_CIRCLE = "great_circle", "Great circle"

    leg = models.ForeignKey(Leg, on_delete=models.CASCADE, related_name="routes")
    version = models.PositiveIntegerField()
    geom = gis.MultiLineStringField(srid=4326)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    waypoints = models.JSONField(default=list, blank=True)
    engine = models.CharField(max_length=32, blank=True)
    engine_version = models.CharField(max_length=32, blank=True)
    engine_data_date = models.DateField(null=True, blank=True)
    produced_at = models.DateTimeField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    source_time_range = DateTimeRangeField(null=True, blank=True)
    length_m = models.FloatField()
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["leg", "version"], name="route_unique_version")
        ]

    def __str__(self) -> str:
        return f"route leg={self.leg_id} v{self.version} ({self.kind})"


class RouteSimplified(models.Model):
    """Per-zoom simplified copy of a route version, built once when the version is created."""

    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="simplified")
    zoom = models.PositiveSmallIntegerField()
    geom = gis.MultiLineStringField(srid=4326)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["route", "zoom"], name="routesimplified_unique_zoom")
        ]

    def __str__(self) -> str:
        return f"route {self.route_id} z{self.zoom}"


class TripParticipant(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="participants")
    person = models.ForeignKey(
        "accounts.Person", on_delete=models.PROTECT, related_name="participations"
    )
    added_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    public_consent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["trip", "person"], name="participant_unique")
        ]

    def __str__(self) -> str:
        return f"{self.person_id} on {self.trip_id}"


class LegParticipantOverride(models.Model):
    """Per-leg add (`include=True`) or remove (`include=False`) relative to the leg's base set."""

    leg = models.ForeignKey(Leg, on_delete=models.CASCADE, related_name="participant_overrides")
    person = models.ForeignKey("accounts.Person", on_delete=models.PROTECT, related_name="+")
    include = models.BooleanField()
    set_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["leg", "person"], name="legoverride_unique")]

    def __str__(self) -> str:
        return f"{'+' if self.include else '-'}{self.person_id} on leg {self.leg_id}"


class Place(models.Model):
    """Owner-scoped reusable location, named via local reverse geocoding."""

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        TIMELINE = "timeline", "Timeline"
        GEOCODED = "geocoded", "Geocoded"

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="places")
    name = models.CharField(max_length=200, blank=True)
    point = gis.PointField(srid=4326)
    address = models.CharField(max_length=300, blank=True)
    google_place_id = models.CharField(max_length=255, blank=True, db_index=True)
    geonames_id = models.BigIntegerField(null=True, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    admin1_code = models.CharField(max_length=16, blank=True)
    county_geoid = models.CharField(max_length=5, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name or f"place {self.pk}"


class Stop(models.Model):
    class Kind(models.TextChoices):
        LODGING = "lodging", "Lodging"
        DESTINATION = "destination", "Destination"
        VISIT = "visit", "Visit"
        WAYPOINT = "waypoint", "Waypoint"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="stops")
    leg = models.ForeignKey(
        Leg, null=True, blank=True, on_delete=models.SET_NULL, related_name="stops"
    )
    place = models.ForeignKey(Place, on_delete=models.PROTECT, related_name="stops")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    arrive_utc = models.DateTimeField(null=True, blank=True)
    depart_utc = models.DateTimeField(null=True, blank=True)
    tz = models.CharField(max_length=64, blank=True)
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    source_segment = models.ForeignKey(
        "history.TimelineSegment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.kind} stop on {self.trip_id}"


class Tag(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=64)
    color = models.CharField(max_length=7, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint("owner", Lower("name"), name="tag_unique_name_ci")]

    def __str__(self) -> str:
        return self.name


class TripTag(models.Model):
    """A tag applied to a trip by its author (the owner's tags are the trip's main tags)."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="trip_tags")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="trip_tags")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["trip", "tag"], name="triptag_unique")]

    def __str__(self) -> str:
        return f"{self.tag_id} on {self.trip_id}"


class TripNote(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="trip_notes")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    public_consent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"note {self.pk} on {self.trip_id}"


class TrackContribution(models.Model):
    """A participant attaching their own GPS track (a time range of their raw points)."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="track_contributions")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    time_range = DateTimeRangeField()
    route = models.ForeignKey(
        Route, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    public_consent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"track by {self.author_id} on {self.trip_id}"


class ReviewFlag(models.Model):
    class Reason(models.TextChoices):
        SOURCE_CHANGED = "source_changed", "Underlying data changed"
        OVERLAP = "overlap", "Overlaps another trip"
        FLIGHT_UNMATCHED = "flight_unmatched", "Flight not matched"
        OTHER = "other", "Other"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="review_flags")
    reason = models.CharField(max_length=32, choices=Reason.choices)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def __str__(self) -> str:
        return f"{self.reason} on {self.trip_id}"


class RejectedCandidate(models.Model):
    """Rejected detections never resurface (matched by fingerprint)."""

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    fingerprint = models.CharField(max_length=64)
    time_range = DateTimeRangeField()
    rejected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "fingerprint"], name="rejected_unique")
        ]

    def __str__(self) -> str:
        return self.fingerprint


class TransferOffer(models.Model):
    class Kind(models.TextChoices):
        TRIP = "trip", "Trip"
        VEHICLE = "vehicle", "Vehicle"
        HOME_PERIOD = "home_period", "Home period"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"

    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    object_id = models.BigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    batch = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.kind} {self.object_id} → {self.to_user_id} ({self.status})"
