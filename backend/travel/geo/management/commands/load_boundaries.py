"""Load Natural Earth admin-0/admin-1 and US Census county boundaries (milestone 6.1, item
14a-1, D-107). Runs as the owner role.

./dev manage load_boundaries                   # pinned files (cached copy or verified download)
./dev manage load_boundaries --latest          # newest upstream files, checksums recorded
./dev manage load_boundaries --only census_counties --file /path/cb_2025_us_county_500k.zip
"""

import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from travel.geo import boundaries as bnd
from travel.geo.flight_reference import DatasetError, describe


class Command(BaseCommand):
    help = "Download (pinned) and load country, state/province and US county boundaries."

    def add_arguments(self, parser):
        parser.add_argument("--only", choices=bnd.SOURCE_NAMES, action="append")
        parser.add_argument("--latest", action="store_true", help="newest upstream files")
        parser.add_argument("--file", type=Path, help="load this local file (needs one --only)")

    def handle(self, *_args, only, latest, file, **_options):
        names = only or bnd.SOURCE_NAMES
        if file is not None and len(names) != 1:
            raise CommandError("--file needs exactly one --only")
        for name in names:
            started = time.monotonic()
            try:
                fetched = (
                    bnd.from_local_file(name, file)
                    if file is not None
                    else bnd.fetch(name, latest=latest)
                )
            except (DatasetError, OSError) as exc:
                raise CommandError(f"{name}: {exc}") from exc
            version = bnd.LOADERS[name](fetched)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{name}: {version.row_count} rows in {time.monotonic() - started:.0f} s, "
                    f"{describe(fetched)}"
                )
            )
