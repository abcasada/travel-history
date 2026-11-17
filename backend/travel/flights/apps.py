from django.apps import AppConfig


class FlightsConfig(AppConfig):
    name = "travel.flights"
    label = "flights"

    def ready(self) -> None:
        from . import importer  # noqa: F401 - registers the flight template importer
