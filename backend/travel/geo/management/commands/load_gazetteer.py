"""Load the GeoNames gazetteer (milestone 6.1 part 1, D-94). Runs as the owner role.

./dev manage load_gazetteer                    # pinned snapshots (cached copy or verified download)
./dev manage load_gazetteer --latest           # today's GeoNames files, checksums recorded
./dev manage load_gazetteer --only geonames_cities500 --file /path/cities500.zip
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from travel.geo import gazetteer as gaz
from travel.geo.flight_reference import DatasetError, describe


class Command(BaseCommand):
    help = "Download (pinned) and load GeoNames places, countries and admin-1 names."

    def add_arguments(self, parser):
        parser.add_argument("--only", choices=sorted(gaz.SOURCES), action="append")
        parser.add_argument("--latest", action="store_true", help="today's files, not the pin")
        parser.add_argument("--file", type=Path, help="load this local file (needs one --only)")

    def handle(self, *_args, only, latest, file, **_options):
        names = only or list(gaz.SOURCES)
        if file is not None and len(names) != 1:
            raise CommandError("--file needs exactly one --only")
        for name in names:
            source = gaz.SOURCES[name]
            try:
                fetched = (
                    gaz.from_local_file(source, file)
                    if file is not None
                    else gaz.fetch(source, latest=latest)
                )
            except (DatasetError, OSError) as exc:
                raise CommandError(f"{name}: {exc}") from exc
            version = gaz.LOADERS[name](fetched)
            self.stdout.write(
                self.style.SUCCESS(f"{name}: {version.row_count} rows, {describe(fetched)}")
            )
        changed = gaz.copy_names()
        self.stdout.write(self.style.SUCCESS(f"state and country names copied to {changed} places"))
