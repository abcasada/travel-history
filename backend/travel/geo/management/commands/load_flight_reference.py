"""Load the flight reference datasets (PLAN.md §12.1, milestone 3.1). Runs as the owner role.

./dev manage load_flight_reference              # pinned versions (checksums verified)
./dev manage load_flight_reference --latest     # newest upstream commit of each file
./dev manage load_flight_reference --only ourairports_airports --file /path/airports.csv
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from travel.geo import flight_reference as ref


class Command(BaseCommand):
    help = "Download (pinned) and load OurAirports airports and OpenFlights airlines/aircraft."

    def add_arguments(self, parser):
        parser.add_argument("--only", choices=sorted(ref.SOURCES), action="append")
        parser.add_argument("--latest", action="store_true", help="follow the default branch")
        parser.add_argument("--file", type=Path, help="load this local file (needs one --only)")
        parser.add_argument(
            "--overrides-only",
            action="store_true",
            help="re-apply the bundled code overrides without downloading anything",
        )

    def handle(self, *_args, only, latest, file, overrides_only, **_options):
        if overrides_only:
            ref.apply_airport_overrides()
            ref.apply_airline_overrides()
            self.stdout.write(self.style.SUCCESS("overrides re-applied"))
            return
        names = only or list(ref.SOURCES)
        if file is not None and len(names) != 1:
            raise CommandError("--file needs exactly one --only")
        for name in names:
            source = ref.SOURCES[name]
            try:
                fetched = (
                    ref.from_local_file(source, file)
                    if file is not None
                    else ref.fetch(source, latest=latest)
                )
            except (ref.DatasetError, OSError) as exc:
                raise CommandError(f"{name}: {exc}") from exc
            version = ref.LOADERS[name](fetched)
            self.stdout.write(
                self.style.SUCCESS(f"{name}: {version.row_count} rows, {ref.describe(fetched)}")
            )
