"""Re-run the importer for an archived batch, e.g. one stored as 'unsupported' before its
importer existed (PLAN.md D-66). Runs as the batch owner (row-level security applies):
    ./dev manage rerun_import <batch id>"""

from django.core.management.base import BaseCommand, CommandError

from travel.history import importers
from travel.history.models import ImportBatch


class Command(BaseCommand):
    help = "Re-run the importer for an import batch from its archived raw file."

    def add_arguments(self, parser):
        parser.add_argument("batch_id", type=int)

    def handle(self, *_args, batch_id, **_options):
        # The owner role (this command's connection) may read the batch to learn its owner.
        batch = ImportBatch.objects.filter(pk=batch_id).first()
        if batch is None or batch.raw_file_id is None:
            raise CommandError("no archived import batch with that id")
        result = importers.run(batch.pk, batch.owner_id)
        self.stdout.write(self.style.SUCCESS(f"batch {batch_id}: {result.status}"))
