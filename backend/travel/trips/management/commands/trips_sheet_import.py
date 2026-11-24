"""Import a trip spreadsheet as a user's trips (docs/design/trip-sheet.md §28.8):

    ./dev manage trips_sheet_import <email> data/private/trips.xlsx [--commit]

The same path as an upload through the app: the file is archived read-only as the user's raw
file, parsed into a preview, and with --commit every importable tab is applied. Every step runs
as the runtime role under row-level security in the user's context, never as the owner role
this command connects with. The issue report is written next to the input as
<name>.report.csv."""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from travel.accounts.models import User
from travel.core import policy
from travel.core.rls import rls_context
from travel.flights.management.commands._paths import repo_path
from travel.history import importers, rawstore
from travel.history.models import ImportBatch, RawFile
from travel.history.uploads import reparse_identical
from travel.trips.models import TripSheetRecord
from travel.trips.sheet import plan as p
from travel.trips.sheet.commit import CommitError, Options, commit_batch
from travel.trips.sheet.importer import report_csv


class Command(BaseCommand):
    help = "Preview (and with --commit apply) a trip spreadsheet for a user, under RLS."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("path")
        parser.add_argument("--commit", action="store_true", help="apply every importable tab")
        parser.add_argument(
            "--create-people",
            action="store_true",
            help="create the unknown people the preview lists (Q-20)",
        )
        parser.add_argument(
            "--recreate",
            action="store_true",
            help="bring back trips that were deleted in the app",
        )

    def handle(self, *_args, email, path, commit, create_people, recreate, **_options):
        source = repo_path(path)
        # The only owner-role read: which account the email belongs to.
        user = User.objects.filter(email__iexact=email).first()
        if user is None or not policy.can_import(user):
            raise CommandError("no active Admin or Member account with that email")
        digest = rawstore.sha256_file(source)
        with connection.cursor() as cursor:
            cursor.execute("SET ROLE travel_app")
        try:
            batch = self._parse(user.pk, source, digest)
            self._report(user, batch, source)
            if commit and batch.status == ImportBatch.Status.PREVIEW:
                self._commit(user, batch, create_people=create_people, recreate=recreate)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("RESET ROLE")

    def _parse(self, owner_id: int, source, digest: str) -> ImportBatch:
        with rls_context(owner_id):
            existing = rawstore.find_existing(owner_id, digest)
            batch = ImportBatch(owner_id=owner_id, kind=ImportBatch.Kind.TRIP_SHEET)
            if existing is not None and not reparse_identical(batch, existing):
                first = (
                    ImportBatch.objects.filter(raw_file=existing, status=ImportBatch.Status.PREVIEW)
                    .order_by("created_at")
                    .first()
                )
                self.stdout.write(f"identical file: showing the open preview, batch {first.pk}")
                return first
            raw = existing or rawstore.store_file(
                owner_id,
                source,
                original_name=source.name,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                uploaded_via=RawFile.UploadedVia.API,
                sha256=digest,
            )
            batch.raw_file = raw
            batch.status = ImportBatch.Status.PROCESSING
            batch.started_at = timezone.now()
            batch.save()
        return importers.run(batch.pk, owner_id)

    def _report(self, user, batch: ImportBatch, source) -> None:
        if batch.status != ImportBatch.Status.PREVIEW:
            raise CommandError(f"batch {batch.pk}: {batch.status} {batch.error or batch.summary}")
        with rls_context(user.pk):
            records = list(TripSheetRecord.objects.filter(import_batch=batch).order_by("position"))
            plans = [p.plan_record(user, record) for record in records]
        self.stdout.write(f"batch {batch.pk}: {len(records)} trip tab(s)")
        for issue in batch.summary.get("workbook_issues", []):
            self.stdout.write(f"  {issue['severity']}: {issue['message']}")
        for plan in plans:
            record, diff = plan.record, plan.diff or {}
            parts = []
            for part in ("stops", "legs"):
                found = diff.get(part, {})
                counts = [f"{len(found.get(k, []))} {k}" for k in ("added", "changed", "kept")]
                parts.append(f"{part}: " + ", ".join(counts))
            self.stdout.write(
                f"- {record.tab_name!r} (key {record.key!r}): {plan.outcome}"
                + (f"; {'; '.join(parts)}" if diff else "")
            )
            for issue in record.issues:
                if issue["severity"] == "info":
                    continue
                where = f"row {issue['row']} {issue['column']}".strip() if issue["row"] else ""
                self.stdout.write(
                    f"    {issue['severity']} {where} {issue['reason']}: {issue['message']}"
                )
        report = source.with_name(f"{source.stem}.report.csv")
        report.write_text(
            report_csv(records, batch.summary.get("workbook_issues", [])), encoding="utf-8"
        )
        self.stdout.write(f"report: {report.name}")

    def _commit(self, user, batch: ImportBatch, *, create_people: bool, recreate: bool) -> None:
        with rls_context(user.pk):
            ids = set(
                TripSheetRecord.objects.filter(import_batch=batch).values_list("pk", flat=True)
            )
            options = Options(
                create_people=ids if create_people else set(),
                recreate=ids if recreate else set(),
            )
            try:
                results = commit_batch(user, batch, options)
            except CommitError as error:
                raise CommandError(error.message) from None
        for result in results:
            suffix = f" ({result.message})" if result.message else ""
            self.stdout.write(
                f"  {result.tab!r}: {result.outcome} trip {result.trip_id or '-'}{suffix}"
            )
        self.stdout.write(self.style.SUCCESS(f"batch {batch.pk}: committed {len(results)} tab(s)"))
