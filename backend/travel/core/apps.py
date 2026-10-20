from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "travel.core"
    label = "core"

    def ready(self) -> None:
        from django.db.models.signals import post_migrate

        from . import db_privileges

        post_migrate.connect(db_privileges.apply_after_migrate, sender=self)
