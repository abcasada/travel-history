"""The database half of `./dev prod import-from-dev` (item 40b, travel.core.devcopy). Run as the
owner role in production's tools container:

  manage.py dev_copy check --dev-migrations FILE      refuse unless the copy may replace prod
  manage.py dev_copy prune --keep EMAIL --raw-dir DIR [--execute]   (in the staging copy only)
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from travel.core import devcopy


class Command(BaseCommand):
    help = "Checks and pruning for copying the development database into production."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        check = sub.add_parser("check")
        check.add_argument("--dev-migrations", required=True, type=Path)
        prune = sub.add_parser("prune")
        prune.add_argument("--keep", required=True, help="the one account to keep (email)")
        prune.add_argument("--raw-dir", required=True, type=Path, help="dev's raw archive")
        prune.add_argument("--execute", action="store_true", help="commit (default: dry run)")

    def handle(self, *_args, **options):
        try:
            if options["action"] == "check":
                lines = options["dev_migrations"].read_text().split()
                devcopy.check_target({line.strip() for line in lines if line.strip()})
                self.stdout.write("check passed: same migrations, no real identity in production")
            else:
                report = devcopy.prune(
                    options["keep"], options["raw_dir"], execute=options["execute"]
                )
                self.stdout.write(devcopy.format_inventory(report))
        except devcopy.Refused as exc:
            raise CommandError(f"refused: {exc}") from exc
