"""Import a converted flight template as a user's data (docs/flights/README.md):

    ./dev manage flights_import <email> data/private/flights.template.csv

The same path as an upload through the app: the file is archived read-only as the user's raw
file and imported as an ImportBatch, every step as the runtime role under row-level security
in the user's context (not as the owner role this command connects with)."""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from travel.accounts.models import User
from travel.core import policy
from travel.core.rls import rls_context
from travel.history import importers, rawstore
from travel.history.models import ImportBatch, RawFile

from ._paths import repo_path


class Command(BaseCommand):
    help = "Import a flight template CSV for a user (as that user, under row-level security)."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("path")

    def handle(self, *_args, email, path, **_options):
        source = repo_path(path)
        # The only owner-role read: which account the email belongs to.
        user = User.objects.filter(email__iexact=email).first()
        if user is None or not policy.can_import(user):
            raise CommandError("no active Admin or Member account with that email")
        digest = rawstore.sha256_file(source)
        with connection.cursor() as cursor:
            cursor.execute("SET ROLE travel_app")
        try:
            batch = self._import(user.pk, source, digest)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("RESET ROLE")
        summary = batch.summary
        self.stdout.write(
            self.style.SUCCESS(
                f"batch {batch.pk}: {batch.status}; "
                f"{summary.get('resolved', 0)} resolved, {summary.get('unmatched', 0)} unmatched, "
                f"records {summary.get('records', {})}"
            )
            if batch.status == ImportBatch.Status.DONE
            else f"batch {batch.pk}: {batch.status} {summary}"
        )

    def _import(self, owner_id: int, source, digest: str) -> ImportBatch:
        with rls_context(owner_id):
            existing = rawstore.find_existing(owner_id, digest)
            if existing is not None:
                first = ImportBatch.objects.filter(raw_file=existing).order_by("created_at").first()
                return ImportBatch.objects.create(
                    owner_id=owner_id,
                    kind=ImportBatch.Kind.FLIGHTS_TEMPLATE,
                    raw_file=existing,
                    status=ImportBatch.Status.DUPLICATE,
                    summary={"duplicate_of_batch": first.pk if first else None},
                    finished_at=timezone.now(),
                )
            raw = rawstore.store_file(
                owner_id,
                source,
                original_name=source.name,
                content_type="text/csv",
                uploaded_via=RawFile.UploadedVia.API,
                sha256=digest,
            )
            batch = ImportBatch.objects.create(
                owner_id=owner_id,
                kind=ImportBatch.Kind.FLIGHTS_TEMPLATE,
                raw_file=raw,
                status=ImportBatch.Status.PROCESSING,
                started_at=timezone.now(),
            )
        return importers.run(batch.pk, owner_id)
