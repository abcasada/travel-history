from django.apps import AppConfig


class TripsConfig(AppConfig):
    name = "travel.trips"
    label = "trips"

    def ready(self) -> None:
        from .sheet import importer  # noqa: F401 - registers the trip spreadsheet importer
