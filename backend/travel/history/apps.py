from django.apps import AppConfig


class HistoryConfig(AppConfig):
    name = "travel.history"
    label = "history"

    def ready(self) -> None:
        from .timeline import importer  # noqa: F401 - registers the Google Timeline importer
