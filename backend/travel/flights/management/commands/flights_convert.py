"""Convert a flight spreadsheet (CSV/XLSX) to the import template (docs/flights/README.md):

    ./dev manage flights_convert data/private/flights.xlsx [--redetect]

Writes flights.mapping.yaml (first run; edit and re-run), flights.template.csv and
flights.unmatched.csv next to the input, which is only read. Needs the reference data
(`load_flight_reference`)."""

from django.core.management.base import BaseCommand, CommandError

from travel.flights import convert
from travel.geo.models import Airport

from ._paths import repo_path


class Command(BaseCommand):
    help = "Convert a flight spreadsheet to the flight import template, with an unmatched report."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--redetect", action="store_true", help="guess the mapping again")

    def handle(self, *_args, path, redetect, **_options):
        source = repo_path(path)
        if not Airport.objects.exists():
            raise CommandError("no airports loaded: run `./dev manage load_flight_reference`")
        try:
            result, paths, guessed = convert.convert_file(source, redetect=redetect)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        rows = result.rows
        unmatched = [row for row in rows if not row.ok]
        mapping = result.mapping
        self.stdout.write(
            f"sheet {mapping.sheet or '(csv)'!r}, header row {mapping.header_row}; columns: "
            + ", ".join(f"{k}<-{v!r}" for k, v in mapping.columns.items())
        )
        if mapping.append_to_notes:
            self.stdout.write("copied into notes: " + ", ".join(mapping.append_to_notes))
        if guessed:
            self.stdout.write(f"mapping guessed and saved to {paths['mapping'].name}; check it")
        self.stdout.write(
            f"{len(rows)} rows ({result.skipped_blank} blank skipped): "
            f"{len(rows) - len(unmatched)} resolved, {len(unmatched)} need attention, "
            f"{sum(1 for row in rows if row.warnings)} with warnings"
        )
        self.stdout.write(f"template: {paths['template'].name}; report: {paths['unmatched'].name}")
