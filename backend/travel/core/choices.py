from django.db import models


class DatePrecision(models.TextChoices):
    EXACT = "exact", "Exact"
    DAY = "day", "Day"
    MONTH = "month", "Month"
    YEAR = "year", "Year"
    APPROXIMATE = "approximate", "Approximate"


class Visibility(models.TextChoices):
    PRIVATE = "private", "Private"
    PARTICIPANTS = "participants", "Participants"
    FAMILY = "family", "Family"
    PUBLIC = "public", "Public"


class TravelMode(models.TextChoices):
    DRIVE = "drive", "Drive"
    FLIGHT = "flight", "Flight"
    TRAIN = "train", "Train"
    BUS = "bus", "Bus"
    BOAT = "boat", "Boat"
    WALK = "walk", "Walk"
    OTHER = "other", "Other"


class DeviceClass(models.TextChoices):
    ANY = "any", "Any"
    DESKTOP = "desktop", "Desktop"
    MOBILE = "mobile", "Mobile"
