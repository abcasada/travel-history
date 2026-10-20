"""Vehicles with ownership history (PLAN.md §5.4). Exactly one owner at any time: an exclusion
constraint forbids overlapping periods and a deferred trigger forbids gaps and owner-less
vehicles (migration 0002)."""

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import models
from django.db.models import F, Func, Q, Value

User = settings.AUTH_USER_MODEL


class Vehicle(models.Model):
    nickname = models.CharField(max_length=100, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    make = models.CharField(max_length=64, blank=True)
    model = models.CharField(max_length=64, blank=True)
    trim = models.CharField(max_length=64, blank=True)
    color = models.CharField(max_length=32, blank=True)
    photo = models.ForeignKey(
        "media.Media", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    hidden = models.BooleanField(default=False)
    is_rental = models.BooleanField(default=False)
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_from"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        label = " ".join(str(p) for p in (self.year, self.make, self.model) if p)
        return self.nickname or label or f"vehicle {self.pk}"


class VehiclePrivate(models.Model):
    """Plate and VIN, readable only by the vehicle's managing user (separate table for RLS)."""

    vehicle = models.OneToOneField(
        Vehicle, primary_key=True, on_delete=models.CASCADE, related_name="private"
    )
    plate = models.CharField(max_length=16, blank=True)
    plate_last4 = models.CharField(max_length=4, blank=True)
    vin = models.CharField(max_length=17, blank=True)

    def __str__(self) -> str:
        return f"private data for vehicle {self.vehicle_id}"


class VehicleOwnership(models.Model):
    class OutsideOwnerKind(models.TextChoices):
        RENTAL = "rental", "Rental company"
        FRIEND = "friend", "Friend"
        EMPLOYER = "employer", "Employer fleet"
        DEALER = "dealer", "Dealer"
        OTHER = "other", "Other"

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="ownerships")
    owner_person = models.ForeignKey(
        "accounts.Person", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    outside_owner_name = models.CharField(max_length=150, blank=True)
    outside_owner_kind = models.CharField(
        max_length=16, choices=OutsideOwnerKind.choices, blank=True
    )
    valid_from = models.DateField(null=True, blank=True)  # null = since before records
    valid_to = models.DateField(null=True, blank=True)  # null = still owned (exclusive bound)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(owner_person__isnull=False) & Q(outside_owner_name=""))
                | (Q(owner_person__isnull=True) & ~Q(outside_owner_name="")),
                name="ownership_exactly_one_owner",
            ),
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True)
                | Q(valid_to__isnull=True)
                | Q(valid_to__gt=F("valid_from")),
                name="ownership_period_ordered",
            ),
            ExclusionConstraint(
                name="ownership_no_overlap",
                expressions=[
                    ("vehicle", RangeOperators.EQUAL),
                    (
                        Func(F("valid_from"), F("valid_to"), Value("[)"), function="daterange"),
                        RangeOperators.OVERLAPS,
                    ),
                ],
            ),
        ]

    def __str__(self) -> str:
        return f"vehicle {self.vehicle_id} {self.valid_from}-{self.valid_to}"
