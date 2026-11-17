"""Flight template importer (ImportBatch kind flights_template): records land as the owner's
data under row-level security; re-imports skip identical rows, update changed ones and never
delete absent ones (CLAUDE.md rule 6); the command-line import runs as the runtime role."""

import shutil

import pytest
from django.core.management import call_command

from tests.factories import UserFactory
from tests.flight_data import SPREADSHEET, load_reference
from tests.helpers import as_owner
from travel.accounts.models import Role
from travel.core.rls import rls_context
from travel.flights import convert
from travel.flights.models import FlightRecord
from travel.history import importers, rawstore
from travel.history.models import ImportBatch

pytestmark = pytest.mark.django_db

HEADER = ",".join(convert.COLUMNS) + "\n"


@pytest.fixture(autouse=True)
def setup(settings, tmp_path):
    settings.BULK_DIR = tmp_path / "bulk"
    load_reference()


@pytest.fixture
def alice():
    with as_owner():
        return UserFactory()


@pytest.fixture
def bob():
    with as_owner():
        return UserFactory()


def run(user, text, tmp_path, name="flights.template.csv") -> ImportBatch:
    path = tmp_path / f"t-{hash(text)}.csv"
    path.write_text(text, encoding="utf-8")
    with rls_context(user.pk):
        raw = rawstore.find_existing(user.pk, rawstore.sha256_file(path))
        raw = raw or rawstore.store_file(user.pk, path, original_name=name)
        batch = ImportBatch.objects.create(owner=user, kind="flights_template", raw_file=raw)
    return importers.run(batch.pk, user.pk)


def records(user):
    with rls_context(user.pk):
        return list(FlightRecord.objects.order_by("row_number"))


def row(date="1998-03-14", origin="MCI", dest="DEN", airline="UA", number="1234", notes=""):
    values = dict.fromkeys(convert.COLUMNS, "")
    values.update(
        {
            "date": date,
            "from": origin,
            "to": dest,
            "airline": airline,
            "flight_number": number,
            "notes": notes,
        }
    )
    return ",".join(values[c] for c in convert.COLUMNS) + "\n"


def test_converted_spreadsheet_imports_as_owner(alice, bob, tmp_path):
    source = tmp_path / "flights.csv"
    shutil.copy(SPREADSHEET, source)
    _, paths, _ = convert.convert_file(source)
    batch = run(alice, paths["template"].read_text(encoding="utf-8"), tmp_path)
    assert batch.status == ImportBatch.Status.DONE
    assert batch.summary["rows"] == 15
    assert batch.summary["resolved"] == 8 and batch.summary["unmatched"] == 7
    assert batch.summary["records"] == {"new": 15, "changed": 0, "identical": 0}
    # Row numbers of the template file (header is row 1; the blank source row is gone).
    assert {r["row"] for r in batch.summary["unmatched_rows"]} == {6, 7, 9, 11, 12, 13, 16}
    mine = records(alice)
    assert len(mine) == 15 and all(r.owner_id == alice.pk for r in mine)
    first = mine[0]
    assert first.origin_airport.ident == "KMCI" and first.destination_airport.ident == "KDEN"
    assert first.airline.name == "United Airlines" and first.aircraft_type.icao == "B733"
    assert first.participants == ["Pat Example", "Sam Example"]
    stapleton = next(r for r in mine if r.date_precision == "month")
    assert stapleton.destination_airport.ident == "US-12484"
    unmatched = [r for r in mine if r.status == FlightRecord.Status.UNMATCHED]
    assert {p["reason"] for r in unmatched for p in r.problems} >= {
        "ambiguous_airport",
        "airport_closed",
        "bad_date",
        "unknown_airport",
        "ambiguous_airline",
    }
    twins = [r for r in mine if r.date_precision == "year" and r.from_code == "MCI"]
    assert len(twins) == 2  # identical rows stay two flights
    assert records(bob) == []  # RLS: nobody else sees them


def test_reimport_skips_identical_updates_changed_keeps_absent(alice, tmp_path):
    first = run(alice, HEADER + row() + row("1999-01-01", number="9"), tmp_path)
    assert first.summary["records"] == {"new": 2, "changed": 0, "identical": 0}
    second = run(alice, HEADER + row(notes="window seat") + row("2001-01-01"), tmp_path)
    assert second.summary["records"] == {"new": 1, "changed": 1, "identical": 0}
    mine = records(alice)
    assert len(mine) == 3  # the 1999 flight is absent from the second file and stays
    assert next(r for r in mine if r.date.year == 1998).notes == "window seat"
    third = run(alice, HEADER + row(notes="window seat") + row("2001-01-01") + "\n", tmp_path)
    assert third.summary["records"] == {"new": 0, "changed": 0, "identical": 2}


def test_rejects_files_that_are_not_templates(alice, tmp_path):
    with pytest.raises(Exception, match="not a flight template"):
        run(alice, "Date Flown,From,To\n1998-01-01,MCI,DEN\n", tmp_path)
    with rls_context(alice.pk):
        batch = ImportBatch.objects.get(owner=alice)
    assert batch.status == ImportBatch.Status.FAILED and "flights_convert" in batch.error


def test_command_imports_as_the_user_under_rls(alice, tmp_path, capsys):
    path = tmp_path / "flights.template.csv"
    path.write_text(HEADER + row(), encoding="utf-8")
    with as_owner():
        call_command("flights_import", alice.email, str(path))
        call_command("flights_import", alice.email, str(path))  # same file again
    out = capsys.readouterr().out
    assert "1 resolved, 0 unmatched" in out and "duplicate" in out
    with rls_context(alice.pk):
        batches = list(ImportBatch.objects.filter(owner=alice).order_by("pk"))
        raw = batches[0].raw_file
    assert [b.status for b in batches] == ["done", "duplicate"]
    assert raw.uploaded_via == "api" and raw.original_name == "flights.template.csv"
    assert len(records(alice)) == 1


def test_command_refuses_viewers(tmp_path):
    from django.core.management.base import CommandError

    with as_owner():
        viewer = UserFactory(role=Role.VIEWER)
    path = tmp_path / "flights.template.csv"
    path.write_text(HEADER + row(), encoding="utf-8")
    with as_owner(), pytest.raises(CommandError):
        call_command("flights_import", viewer.email, str(path))
