"""Remove what `./dev e2e` leaves behind (audit finding #8; F-11, D-110). Runs as the owner role
(no RLS), in the dev or lane database the e2e ran against:
    ./dev manage e2e_cleanup <sha256 of e2e/fixtures/timeline-synthetic.json>

- Duplicate import batches of the synthetic Timeline fixture: each run uploads it again, and
  after the first run the upload is recorded as a "duplicate" batch with no data of its own.
  Only duplicates of the file with the given checksum go, so real imports can never match.
- The trip-spreadsheet step's leftovers (travel.core.devcopy.remove_e2e_leftovers): its
  SYNTHETIC trip-sheet batches (parsed tabs and key links included), the persons named
  "E2E …" and the tags `e2e` and `e2e-bulk-…`. Raw files are never deleted."""

import re

from django.core.management.base import BaseCommand, CommandError

from travel.core import devcopy
from travel.history import rawstore
from travel.history.models import ImportBatch


class Command(BaseCommand):
    help = "Delete what the e2e smoke test leaves behind (synthetic rows only)."

    def add_arguments(self, parser):
        parser.add_argument("sha256")

    def handle(self, *_args, sha256: str, **_options):
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise CommandError("expected a lower-case hex sha256")
        # The checksum and the duplicate status scope this.
        deleted, _ = ImportBatch.objects.filter(
            raw_file__sha256=sha256, status=ImportBatch.Status.DUPLICATE
        ).delete()
        self.stdout.write(f"e2e cleanup: removed {deleted} duplicate import batch(es)")
        try:
            report = devcopy.remove_e2e_leftovers(rawstore.raw_root())
        except devcopy.Refused as exc:
            raise CommandError(f"refused: {exc}") from exc
        removed = ", ".join(f"{table} {n}" for table, n in sorted(report.removed.items()))
        self.stdout.write(f"e2e cleanup: removed {removed or 'no other e2e rows'}")
