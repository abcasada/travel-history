"""import-from-dev's database half (item 40b, travel.core.devcopy): the refusals and the pruning
of the staging copy, on SYNTHETIC data. Runs as the owner role, as the command does."""

import io
from pathlib import Path

import pytest
import zstandard
from django.core.management import CommandError, call_command
from django.db import connection

from tests.factories import (
    LegFactory,
    LocationPointFactory,
    PersonFactory,
    RawFileFactory,
    TripFactory,
    UserFactory,
)
from travel.accounts.models import Person, User
from travel.core import devcopy
from travel.history.models import ImportBatch, LocationPoint, RawFile
from travel.trips.models import (
    Leg,
    Tag,
    Trip,
    TripParticipant,
    TripSheetLink,
    TripSheetRecord,
    TripTag,
)

pytestmark = [pytest.mark.django_db, pytest.mark.as_owner]

MOCK_ISSUER = "http://mock-oidc.example.test:8781/default"


def _user(email: str, issuer: str = MOCK_ISSUER) -> User:
    return UserFactory(email=email, oidc_issuer=issuer)


def _batch(owner: User, raw_dir, content: bytes, points: int) -> ImportBatch:
    raw = RawFileFactory(owner=owner)
    path = raw_dir / raw.storage_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zstandard.ZstdCompressor().compress(content))
    batch = ImportBatch.objects.create(
        owner=owner, kind="google_timeline", status="done", raw_file=raw
    )
    for _ in range(points):
        LocationPointFactory(owner=owner, import_batch=batch)
    return batch


@pytest.fixture
def world(tmp_path):
    raw_dir = tmp_path / "raw"
    keep = _user("dev-admin@example.test")
    other = _user("dev-member@example.test")
    real = _batch(keep, raw_dir, b'{"semanticSegments": []}', points=3)
    fake = _batch(keep, raw_dir, b'{"SYNTHETIC": "generated test data", "x": 1}', points=2)
    _batch(other, raw_dir, b'{"SYNTHETIC": "generated test data"}', points=4)
    LocationPointFactory(owner=keep)  # a tracker point (no batch)
    TripFactory(owner=keep, title="Synthetic real trip")
    TripFactory(owner=keep, title="E2E trip 123")
    TripFactory(owner=other)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO django_session VALUES ('synthetic-key', 'x', now() + interval '1 day')"
        )
    return {"raw_dir": raw_dir, "keep": keep, "other": other, "real": real, "fake": fake}


def test_dry_run_changes_nothing_and_reports(world):
    before = (User.objects.count(), LocationPoint.objects.count(), Trip.objects.count())
    report = devcopy.prune("dev-admin@example.test", world["raw_dir"], execute=False)
    assert not report.executed
    assert (User.objects.count(), LocationPoint.objects.count(), Trip.objects.count()) == before
    assert set(report.before) == {"dev-admin@example.test", "dev-member@example.test"}
    assert set(report.after) == {"dev-admin@example.test"}
    assert report.after["dev-admin@example.test"]["history_locationpoint.owner_id"] == 4
    assert report.synthetic_batches == [world["fake"].pk]
    assert report.operational["django_session"] == 1
    assert "DRY RUN" in devcopy.format_inventory(report)


def test_execute_keeps_only_the_real_data_of_one_account(world):
    keep, real = world["keep"], world["real"]
    report = devcopy.prune("DEV-ADMIN@example.test", world["raw_dir"], execute=True)
    assert report.executed
    assert list(User.objects.values_list("pk", flat=True)) == [keep.pk]
    assert list(ImportBatch.objects.values_list("pk", flat=True)) == [real.pk]
    assert list(RawFile.objects.values_list("pk", flat=True)) == [real.raw_file_id]
    assert LocationPoint.objects.filter(import_batch=real).count() == 3
    assert LocationPoint.objects.filter(import_batch__isnull=True).count() == 1
    assert LocationPoint.objects.count() == 4
    assert list(Trip.objects.values_list("title", flat=True)) == ["Synthetic real trip"]
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM django_session")
        assert cursor.fetchone()[0] == 0
    assert report.nulled == {}


def test_prune_refuses_in_the_live_database(world, monkeypatch):
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        monkeypatch.setattr(devcopy, "LIVE_DATABASE", cursor.fetchone()[0])
    with pytest.raises(devcopy.Refused, match="live database"):
        devcopy.prune("dev-admin@example.test", world["raw_dir"], execute=True)
    assert User.objects.count() == 2


def test_prune_refuses_an_unknown_account_or_a_missing_raw_file(world, tmp_path):
    with pytest.raises(devcopy.Refused, match="no account"):
        devcopy.prune("nobody@example.test", world["raw_dir"], execute=True)
    with pytest.raises(devcopy.Refused, match="missing"):
        devcopy.prune("dev-admin@example.test", tmp_path / "empty", execute=True)
    assert User.objects.count() == 2


def test_check_passes_with_same_migrations_and_no_real_identity(world):
    devcopy.check_target(devcopy.applied_migrations())


def test_check_refuses_different_migrations(world, tmp_path):
    dev = devcopy.applied_migrations() | {"trips.9999_not_in_production"}
    with pytest.raises(devcopy.Refused, match=r"only in dev: \['trips\.9999"):
        devcopy.check_target(dev)
    listing = tmp_path / "dev-migrations.txt"
    listing.write_text("\n".join(sorted(devcopy.applied_migrations())[1:]))
    with pytest.raises(CommandError, match="migrations differ"):
        call_command("dev_copy", "check", "--dev-migrations", str(listing))


def test_check_refuses_forever_once_production_has_a_real_identity(world):
    _user("someone@example.test", issuer="https://auth.example.test/application/o/travel/")
    with pytest.raises(devcopy.Refused, match="real sign-in identity"):
        devcopy.check_target(devcopy.applied_migrations())


# --- F-11: the trip-spreadsheet step's leftovers (D-110) -------------------------------------


def workbook(title: str) -> bytes:
    """An .xlsx with this title in docProps/core.xml (as openpyxl and Excel write it)."""
    import io

    from openpyxl import Workbook

    book = Workbook()
    book.active["A1"] = "SYNTHETIC"
    book.properties.title = title
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


E2E_SHEET = "SYNTHETIC e2e trip sheet"  # scripts/make_e2e_trip_sheet.py
TEMPLATE = "Trip spreadsheet template (SYNTHETIC example)"  # a real sheet made from the template


def test_synthetic_workbooks_are_recognised_by_their_title():
    assert devcopy.is_synthetic_workbook(workbook(E2E_SHEET))
    assert not devcopy.is_synthetic_workbook(workbook(TEMPLATE))
    assert not devcopy.is_synthetic_workbook(workbook(""))
    assert not devcopy.is_synthetic_workbook(b"SYNTHETIC but not a zip")
    for fixture in ("e2e/fixtures/trip-sheet-synthetic.xlsx", "docs/trips/trip-template.xlsx"):
        path = Path(__file__).resolve().parents[2] / fixture
        if path.exists():  # the backend container mounts backend/ only
            expected = fixture.startswith("e2e/")
            assert devcopy.is_synthetic_workbook(path.read_bytes()) is expected


def _sheet_batch(owner: User, raw_dir, title: str, key: str, trip_title: str) -> ImportBatch:
    raw = RawFileFactory(owner=owner, original_name="trips.xlsx")
    path = raw_dir / raw.storage_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zstandard.ZstdCompressor().compress(workbook(title)))
    batch = ImportBatch.objects.create(owner=owner, kind="trip_sheet", status="done", raw_file=raw)
    trip = TripFactory(owner=owner, title=trip_title)
    LegFactory(trip=trip, author=owner, import_batch=batch)  # sheet provenance (D-102)
    record = TripSheetRecord.objects.create(
        owner=owner,
        import_batch=batch,
        tab_name=key,
        position=1,
        key=key,
        content_hash="0" * 64,
        outcome="created",
        trip=trip,
    )
    TripSheetLink.objects.create(owner=owner, key=key, trip=trip, last_record=record)
    return batch


@pytest.fixture
def sheets(world):
    keep, raw_dir = world["keep"], world["raw_dir"]
    world["e2e_sheet"] = _sheet_batch(keep, raw_dir, E2E_SHEET, "e2e-sheet-trip", "E2E sheet trip")
    world["real_sheet"] = _sheet_batch(keep, raw_dir, TEMPLATE, "summer", "Summer trip")
    cousin = PersonFactory(created_by=keep, display_name="E2E Sheet Cousin")
    world["person"] = PersonFactory(created_by=keep, display_name="Synthetic Grandma")
    trip = Trip.objects.get(title="Synthetic real trip")
    TripParticipant.objects.create(trip=trip, person=cousin, added_by=keep)
    TripParticipant.objects.create(trip=trip, person=world["person"], added_by=keep)
    for name in ("e2e", "E2E-bulk-1700000000", "e2e-trip-ideas", "summer"):
        tag = Tag.objects.create(owner=keep, name=name)
        TripTag.objects.create(trip=trip, tag=tag, author=keep)
    # A SYNTHETIC raw file no batch uses (e2e_cleanup removed its batch) and a real one.
    for content in (b'{"SYNTHETIC": "fixture"}', b'{"semanticSegments": [1]}'):
        raw = RawFileFactory(owner=keep)
        (raw_dir / raw.storage_path).write_bytes(zstandard.ZstdCompressor().compress(content))
        world.setdefault("unused", []).append(raw)
    return world


def test_prune_removes_the_e2e_sheet_persons_and_tags(sheets):
    report = devcopy.prune("dev-admin@example.test", sheets["raw_dir"], execute=True)
    e2e, real = sheets["e2e_sheet"], sheets["real_sheet"]
    assert report.synthetic_batches == [sheets["fake"].pk, e2e.pk]
    assert set(ImportBatch.objects.values_list("pk", flat=True)) == {sheets["real"].pk, real.pk}
    assert list(TripSheetRecord.objects.values_list("key", flat=True)) == ["summer"]
    assert list(TripSheetLink.objects.values_list("key", flat=True)) == ["summer"]
    assert set(Trip.objects.values_list("title", flat=True)) == {
        "Synthetic real trip",
        "Summer trip",
    }
    assert list(Leg.objects.values_list("import_batch", flat=True)) == [real.pk]
    assert list(Person.objects.values_list("display_name", flat=True)) == ["Synthetic Grandma"]
    assert sorted(Tag.objects.values_list("name", flat=True)) == ["e2e-trip-ideas", "summer"]
    assert TripParticipant.objects.count() == 1
    synthetic_unused, real_unused = sheets["unused"]
    assert report.synthetic_raw_files == [synthetic_unused.pk]
    assert set(RawFile.objects.values_list("pk", flat=True)) == {
        sheets["real"].raw_file_id,
        real.raw_file_id,
        real_unused.pk,
    }
    assert "synthetic raw files no batch used" in devcopy.format_inventory(report)


def test_e2e_cleanup_removes_the_sheet_step_leftovers_in_every_account(sheets, settings):
    """The live-database cleanup (`./dev e2e` signs in as dev-member): by name and marker, in
    every account, keeping raw files and everything real."""
    other = sheets["other"]
    raw_dir = sheets["raw_dir"]
    settings.BULK_DIR = raw_dir.parent
    member_sheet = _sheet_batch(other, raw_dir, E2E_SHEET, "e2e-sheet-trip", "E2E sheet trip")
    PersonFactory(created_by=other, display_name="E2E Sheet Cousin")
    Tag.objects.create(owner=other, name="E2E")
    raw_files = set(RawFile.objects.values_list("pk", flat=True))
    points = LocationPoint.objects.count()

    out = io.StringIO()
    call_command("e2e_cleanup", "0" * 64, stdout=out)

    gone = {sheets["e2e_sheet"].pk, member_sheet.pk}
    assert not ImportBatch.objects.filter(pk__in=gone).exists()
    assert ImportBatch.objects.filter(pk=sheets["real_sheet"].pk).exists()
    assert sorted(TripSheetLink.objects.values_list("key", flat=True)) == ["summer"]
    assert not Person.objects.filter(display_name__istartswith="E2E ").exists()
    assert Person.objects.filter(display_name="Synthetic Grandma").exists()
    assert sorted(Tag.objects.values_list("name", flat=True)) == ["e2e-trip-ideas", "summer"]
    # The e2e's sheet trips themselves stay (the e2e deletes its own); their provenance goes.
    assert Trip.objects.filter(title="E2E sheet trip").count() == 2
    assert Leg.objects.filter(import_batch__in=gone).count() == 0
    assert Leg.objects.filter(import_batch=sheets["real_sheet"]).count() == 1
    assert set(RawFile.objects.values_list("pk", flat=True)) == raw_files  # rule 12
    assert LocationPoint.objects.count() == points
    assert "trips_tripsheetlink 2" in out.getvalue()
    # Nothing left: a second run removes nothing.
    out = io.StringIO()
    call_command("e2e_cleanup", "0" * 64, stdout=out)
    assert "no other e2e rows" in out.getvalue()
