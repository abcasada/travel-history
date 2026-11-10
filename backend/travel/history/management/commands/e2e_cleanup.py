"""Remove the duplicate import batches that `./dev e2e` leaves behind (audit finding #8).

Each smoke-test run uploads the same synthetic fixture; after the first run the upload is
recorded as a "duplicate" batch with no data of its own. Only duplicate batches whose raw file
has the given checksum are deleted, so real imports can never match:
    ./dev manage e2e_cleanup <sha256 of e2e/fixtures/timeline-synthetic.json>"""

import re

from django.core.management.base import BaseCommand, CommandError

from travel.history.models import ImportBatch


class Command(BaseCommand):
    help = "Delete duplicate import batches of the synthetic e2e fixture."

    def add_arguments(self, parser):
        parser.add_argument("sha256")

    def handle(self, *_args, sha256: str, **_options):
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise CommandError("expected a lower-case hex sha256")
        # Runs as the owner role (no RLS): the checksum and the duplicate status scope it.
        deleted, _ = ImportBatch.objects.filter(
            raw_file__sha256=sha256, status=ImportBatch.Status.DUPLICATE
        ).delete()
        self.stdout.write(f"e2e cleanup: removed {deleted} duplicate import batch(es)")
