from django.apps import AppConfig


class TrackingConfig(AppConfig):
    """Live location tracking (PLAN.md §9): tracker ingestion endpoints and device tokens.
    The tables live elsewhere (`accounts.DeviceToken`, `history.LocationPoint`)."""

    name = "travel.tracking"
    label = "tracking"
