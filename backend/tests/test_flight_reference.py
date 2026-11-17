"""Flight reference loaders (milestone 3.1): dataset versions, upserts, keyword code history,
bundled overrides, pinned downloads with a generic User-Agent, read-only for the app role."""

import hashlib
from pathlib import Path

import pytest
from django.db import DatabaseError, transaction

from tests.flight_data import FIXTURES, load_reference
from tests.helpers import as_owner
from travel.geo import flight_reference as ref
from travel.geo.models import (
    AircraftType,
    Airline,
    AirlineCodeHistory,
    Airport,
    AirportCodeHistory,
    DatasetVersion,
)

pytestmark = pytest.mark.django_db


def test_keyword_codes():
    assert ref.keyword_codes("DEN KDEN, X-KDEN") == ["DEN", "KDEN"]
    assert ref.keyword_codes("checkerboard, RAF Kai Tak, HKG, VHHX") == ["HKG", "VHHX"]
    assert ref.keyword_codes("") == []


def test_load_records_versions_and_history():
    load_reference()
    assert Airport.objects.count() == 22
    assert Airline.objects.count() == 15
    assert AircraftType.objects.count() == 6
    versions = {v.name: v for v in DatasetVersion.objects.all()}
    assert set(versions) == set(ref.SOURCES)
    airlines = versions["openflights_airlines"]
    assert airlines.attribution == "Airline and aircraft data: OpenFlights.org (ODbL)"
    assert airlines.license.startswith("ODbL") and airlines.license_url
    expected = hashlib.sha256((FIXTURES / "airlines.dat").read_bytes()).hexdigest()
    assert airlines.checksum == expected
    assert airlines.source_commit == "local"  # a hand-supplied file is not the pinned one
    stapleton = Airport.objects.get(ident="US-12484")
    assert str(stapleton.closed_on) == "1995-02-27"
    sources = set(
        AirportCodeHistory.objects.filter(code="DEN", airport=stapleton).values_list(
            "source", flat=True
        )
    )
    assert sources == {"keywords", "bundled"}
    assert AirlineCodeHistory.objects.filter(code="PA").count() == 1


def test_reload_is_idempotent_and_keeps_manual_rows():
    load_reference()
    with as_owner():
        den = Airport.objects.get(ident="KDEN")
        AirportCodeHistory.objects.create(code="XYZ", airport=den, source="manual")
        manual_airline = Airline.objects.create(name="Hand-entered Air", manual=True)
        ids = set(Airport.objects.values_list("pk", flat=True))
    load_reference()
    with as_owner():
        assert set(Airport.objects.values_list("pk", flat=True)) == ids
        assert AirportCodeHistory.objects.filter(source="manual").count() == 1
        assert Airline.objects.filter(pk=manual_airline.pk).exists()
        assert AirportCodeHistory.objects.filter(code="DEN", source="bundled").count() == 2


def test_app_role_reads_but_cannot_write_reference_data():
    load_reference()
    assert Airport.objects.filter(iata_code="DEN").exists()
    for statement in (
        lambda: Airport.objects.filter(iata_code="DEN").update(name="x"),
        lambda: DatasetVersion.objects.all().delete(),
        lambda: AirportCodeHistory.objects.create(
            code="ABC", airport=Airport.objects.first(), source="manual"
        ),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            statement()


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield self.body


def test_fetch_pins_commit_checks_sha_and_sends_no_personal_data(monkeypatch, tmp_path):
    body = (FIXTURES / "planes.dat").read_bytes()
    seen = {}

    def fake_get(self, url, **kwargs):
        seen["url"], seen["headers"] = url, dict(self.headers)
        return _Response(body)

    monkeypatch.setattr("requests.Session.get", fake_get)
    source = ref.Source(**{**ref.AIRCRAFT.__dict__, "sha256": hashlib.sha256(body).hexdigest()})
    fetched = ref.fetch(source, directory=tmp_path)
    assert seen["url"] == (
        "https://raw.githubusercontent.com/jpatokal/openflights/"
        f"{ref.AIRCRAFT.commit}/data/planes.dat"
    )
    assert seen["headers"]["User-Agent"] == "travel-history-reference-loader/1.0"
    assert not {"Cookie", "Authorization", "From"} & set(seen["headers"])
    assert fetched.commit == ref.AIRCRAFT.commit and fetched.path.read_bytes() == body

    # A changed upstream file fails the pinned checksum and leaves nothing behind.
    monkeypatch.setattr("requests.Session.get", lambda self, url, **kw: _Response(b"tampered"))
    other = ref.Source(**{**source.__dict__, "name": "other"})
    with pytest.raises(ref.DatasetError):
        ref.fetch(other, directory=tmp_path)
    assert not list(Path(tmp_path).glob("other-*"))
