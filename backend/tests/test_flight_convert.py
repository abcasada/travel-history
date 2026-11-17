"""Spreadsheet → template conversion (milestone 3.2) on the synthetic spreadsheet and a
generated XLSX: header detection, the saved mapping, normalisation, the unmatched report, and
that the input file is never written."""

import csv
import datetime as dt
import hashlib
import shutil

import pytest
import yaml
from django.core.management import call_command

from tests.flight_data import SPREADSHEET, load_reference
from tests.helpers import as_owner
from travel.flights import convert

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def reference():
    load_reference()


def _rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_synthetic_csv(tmp_path):
    source = tmp_path / "flights.csv"
    shutil.copy(SPREADSHEET, source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result, paths, guessed = convert.convert_file(source)
    assert guessed and result.mapping.header_row == 2  # the title row is skipped
    assert result.mapping.columns["flight_number"] == "Flight #"
    assert result.mapping.append_to_notes == ["Miles"]
    assert result.skipped_blank == 1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before

    template = _rows(paths["template"])
    assert list(template[0]) == convert.COLUMNS
    assert len(template) == 15  # unmatched rows are kept too, with reasons in the report
    first = template[0]
    assert first["date"] == "1998-03-14" and first["dep_time"] == "19:05"
    assert first["airline"] == "United" and first["flight_number"] == "UA1234"
    assert first["cabin_class"] == "economy" and first["seat_type"] == "window"
    assert first["registration"] == "N123EX" and first["seat"] == "12A"
    assert first["notes"] == "first leg; Miles: 533"
    assert first["participants"] == "Pat Example; Sam Example"
    assert template[2]["date"] == "1994-06" and template[2]["from"] == "MCI"
    assert template[8]["airline"] == "PA"  # taken from the flight number

    problems = {
        (int(r["source_row"]), r["field"], r["reason"])
        for r in _rows(paths["unmatched"])
        if r["kind"] == "problem"
    }
    assert problems == {
        (7, "from", "ambiguous_airport"),  # HKG in 1998
        (8, "from", "ambiguous_airport"),  # BER in 2015
        (10, "from", "airport_closed"),  # TXL in 2021
        (12, "airline", "ambiguous_airline"),  # PA in 1995
        (13, "date", "bad_date"),
        (14, "from", "unknown_airport"),
        (18, "to", "ambiguous_airport"),  # "Chicago"
    }


def test_edited_mapping_is_used(tmp_path):
    source = tmp_path / "flights.csv"
    shutil.copy(SPREADSHEET, source)
    _, paths, _ = convert.convert_file(source)
    mapping = yaml.safe_load(paths["mapping"].read_text())
    mapping["append_to_notes"] = []
    mapping["dayfirst"] = True
    del mapping["columns"]["participants"]
    paths["mapping"].write_text(yaml.safe_dump(mapping))
    result, _, guessed = convert.convert_file(source)
    assert not guessed
    rows = _rows(paths["template"])
    assert rows[0]["notes"] == "first leg" and rows[0]["participants"] == ""
    assert rows[5]["date"] == "2015-02-08"  # 08/02/2015 read day first
    assert result.rows[11].ok is False  # 31/31/2001 is still no date


def test_xlsx_with_route_column_and_typed_cells(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Flights"
    sheet.append(["SYNTHETIC test workbook"])
    sheet.append([])
    sheet.append(["Flight Date", "Route", "Airline", "Flight No", "Departure Time", "Cabin"])
    sheet.append([dt.datetime(1998, 3, 14), "MCI-DEN", "UA", 1234, dt.time(7, 5), "J"])
    sheet.append([1990, "HKG / LAX", "United Airlines", "UA 1", None, "Coach"])
    source = tmp_path / "flights.xlsx"
    workbook.save(source)
    result, paths, _ = convert.convert_file(source)
    assert result.mapping.sheet == "Flights" and result.mapping.header_row == 3
    rows = _rows(paths["template"])
    assert rows[0]["from"] == "MCI" and rows[0]["to"] == "DEN"
    assert rows[0]["flight_number"] == "1234" and rows[0]["dep_time"] == "07:05"
    assert rows[0]["cabin_class"] == "business"
    assert rows[1]["date"] == "1990" and rows[1]["from"] == "HKG"
    assert all(row.ok for row in result.rows)


def test_refuses_unrecognisable_sheets(tmp_path):
    source = tmp_path / "list.csv"
    source.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ValueError, match="header row"):
        convert.convert_file(source)


def test_command(tmp_path, capsys):
    source = tmp_path / "flights.csv"
    shutil.copy(SPREADSHEET, source)
    with as_owner():
        call_command("flights_convert", str(source))
    out = capsys.readouterr().out
    assert "15 rows (1 blank skipped): 8 resolved, 7 need attention" in out
    assert (tmp_path / "flights.template.csv").exists()
    assert (tmp_path / "flights.unmatched.csv").exists()
