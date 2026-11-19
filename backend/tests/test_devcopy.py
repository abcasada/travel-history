"""import-from-dev's database half (item 40b, travel.core.devcopy): the refusals and the pruning
of the staging copy, on SYNTHETIC data. Runs as the owner role, as the command does."""

import pytest
import zstandard
from django.core.management import CommandError, call_command
from django.db import connection

from tests.factories import LocationPointFactory, RawFileFactory, TripFactory, UserFactory
from travel.accounts.models import User
from travel.core import devcopy
from travel.history.models import ImportBatch, LocationPoint, RawFile
from travel.trips.models import Trip

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
