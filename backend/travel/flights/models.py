"""Imported flights (PLAN.md §12.3, milestone 3.2, D-88).

One `FlightRecord` per row of an imported flight template: the values as given, what they
resolved to (airports, airline, aircraft type by flight date), and why a row could not be
resolved. They are raw history of their owner (own-only RLS, like import batches); grouping into
trips and legs (milestone 3.3) reads them and never changes them."""

from django.contrib.postgres.fields import ArrayField
from django.db import models

from travel.accounts.models import User
from travel.trips.models import CabinClass


class FlightRecord(models.Model):
    class Status(models.TextChoices):
        RESOLVED = "resolved", "Resolved"
        UNMATCHED = "unmatched", "Needs attention"

    class DatePrecision(models.TextChoices):
        DAY = "day", "Day"
        MONTH = "month", "Month"
        YEAR = "year", "Year"

    class SeatType(models.TextChoices):
        WINDOW = "window", "Window"
        MIDDLE = "middle", "Middle"
        AISLE = "aisle", "Aisle"
        OTHER = "other", "Other"

    owner = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name="+")
    import_batch = models.ForeignKey(
        "history.ImportBatch",
        null=True,
        blank=True,
        on_delete=models.DB_SET_NULL,
        related_name="+",
    )
    # Identity across re-imports: the flight's key fields plus its occurrence number among rows
    # with the same fields, so two identical rows stay two flights (D-88).
    row_key = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    row_number = models.IntegerField()
    status = models.CharField(max_length=16, choices=Status.choices)
    problems = models.JSONField(default=list, blank=True)  # [{field, reason, detail}]
    warnings = models.JSONField(default=list, blank=True)  # [{field, reason, detail}]

    trip_key = models.CharField(max_length=100, blank=True)
    date = models.DateField(null=True, blank=True)  # first day of the period for partial dates
    date_precision = models.CharField(max_length=8, choices=DatePrecision.choices, blank=True)
    dep_time = models.TimeField(null=True, blank=True)  # local time at the origin
    arr_time = models.TimeField(null=True, blank=True)  # local time at the destination
    arr_date = models.DateField(null=True, blank=True)
    from_code = models.CharField(max_length=100, blank=True)
    to_code = models.CharField(max_length=100, blank=True)
    origin_airport = models.ForeignKey(
        "geo.Airport", null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    destination_airport = models.ForeignKey(
        "geo.Airport", null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    airline_text = models.CharField(max_length=200, blank=True)
    airline = models.ForeignKey(
        "geo.Airline", null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    flight_number = models.CharField(max_length=16, blank=True)
    aircraft_text = models.CharField(max_length=200, blank=True)
    aircraft_type = models.ForeignKey(
        "geo.AircraftType", null=True, blank=True, on_delete=models.DB_SET_NULL, related_name="+"
    )
    registration = models.CharField(max_length=16, blank=True)
    seat = models.CharField(max_length=8, blank=True)
    cabin_class = models.CharField(max_length=16, choices=CabinClass.choices, blank=True)
    seat_type = models.CharField(max_length=8, choices=SeatType.choices, blank=True)
    purpose = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    participants = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "row_key"], name="flightrecord_unique_row")
        ]
        indexes = [models.Index(fields=["owner", "date"])]
        ordering = ["date", "dep_time", "row_number"]

    def __str__(self) -> str:
        return f"{self.date} {self.from_code}-{self.to_code}"
