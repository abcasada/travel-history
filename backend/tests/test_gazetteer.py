"""GeoNames gazetteer (item 14, D-94): loaders on SYNTHETIC subsets, pinned snapshots with a
generic User-Agent, the city search's ranking and limits, and read-only access for the app
role. Who may call the search is in tests/permissions/test_catalog_ui_api.py."""

import hashlib
import zipfile
from pathlib import Path

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.models import Q

from tests.factories import UserFactory
from tests.helpers import as_owner
from tests.permissions.test_trips_api import API, call, login
from travel.geo import gazetteer as gaz
from travel.geo.flight_reference import DatasetError
from travel.geo.models import DatasetVersion, GeoNamesAdmin1, GeoNamesCountry, GeoNamesPlace

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "geonames"
FILES = {
    gaz.COUNTRIES: "countryInfo.txt",
    gaz.ADMIN1: "admin1CodesASCII.txt",
    gaz.CITIES: "cities500.txt",
    gaz.US_PLACES: "US.txt",
}


def load_gazetteer() -> None:
    with as_owner():
        for source, filename in FILES.items():
            gaz.LOADERS[source.name](gaz.from_local_file(source, FIXTURES / filename))
        gaz.copy_names()


def test_load_records_versions_filters_us_places_and_copies_names():
    load_gazetteer()
    assert GeoNamesCountry.objects.count() == 2
    assert GeoNamesAdmin1.objects.count() == 5
    ids = set(GeoNamesPlace.objects.values_list("geonameid", flat=True))
    # cities500 (7, one also in the US file) + small US towns; not neighbourhoods (PPLX),
    # abandoned places (PPLQ) or streams.
    assert ids == {*range(9000001, 9000008), 9000101, 9000105}
    town = GeoNamesPlace.objects.get(geonameid=9000101)
    assert (town.admin1_name, town.country_name, town.population) == ("Kansas", "United States", 40)
    assert (town.point.x, town.point.y, town.timezone) == (-99.0, 38.5, "America/Chicago")
    synth = GeoNamesPlace.objects.get(geonameid=9000006)
    assert (synth.admin1_name, synth.country_name) == ("Île-de-Synth", "Synthetic Republic")
    versions = {v.name: v for v in DatasetVersion.objects.all()}
    assert set(versions) == set(gaz.SOURCES)
    cities = versions["geonames_cities500"]
    assert cities.row_count == 7 and cities.license == "CC BY 4.0"
    assert cities.attribution == "Place names: GeoNames (geonames.org), CC BY 4.0"
    assert cities.checksum == hashlib.sha256((FIXTURES / "cities500.txt").read_bytes()).hexdigest()
    assert cities.version.startswith("local")  # a hand-supplied file is not the pinned one


def test_reload_is_idempotent_and_reads_zipped_dumps(tmp_path):
    load_gazetteer()
    archive = tmp_path / "cities500.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(FIXTURES / "cities500.txt", "cities500.txt")
    with as_owner():
        gaz.load_cities(gaz.from_local_file(gaz.CITIES, archive))
        assert gaz.copy_names() == 0  # nothing changed
        assert GeoNamesPlace.objects.count() == 9


def test_app_role_reads_but_cannot_write_gazetteer():
    load_gazetteer()
    assert GeoNamesPlace.objects.filter(name="Synthville").exists()
    for statement in (
        lambda: GeoNamesPlace.objects.filter(name="Synthville").update(population=1),
        lambda: GeoNamesAdmin1.objects.all().delete(),
        lambda: GeoNamesCountry.objects.create(iso_a2="ZZ", name="x"),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            statement()


# --- Downloads ---------------------------------------------------------------------------------


class _Response:
    def __init__(self, body: bytes, modified: str = "Wed, 18 Nov 2026 02:56:31 GMT"):
        self.body = body
        self.headers = {"Last-Modified": modified}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield self.body


def test_fetch_pins_snapshot_checks_sha_and_sends_no_personal_data(monkeypatch, tmp_path):
    body = (FIXTURES / "admin1CodesASCII.txt").read_bytes()
    seen = []

    def fake_get(self, url, **kwargs):
        seen.append((url, dict(self.headers)))
        return _Response(body)

    monkeypatch.setattr("requests.Session.get", fake_get)
    source = gaz.DumpFile(**{**gaz.ADMIN1.__dict__, "sha256": hashlib.sha256(body).hexdigest()})
    fetched = gaz.fetch(source, directory=tmp_path)
    url, headers = seen[0]
    assert url == "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
    assert headers["User-Agent"] == "travel-history-reference-loader/1.0"
    assert not {"Cookie", "Authorization", "From"} & set(headers)
    assert fetched.path.name == "geonames_admin1-2026-11-18.txt"
    assert fetched.commit == "pinned" and fetched.path.read_bytes() == body

    # The verified cached copy is the pin: no second download.
    assert gaz.fetch(source, directory=tmp_path).path == fetched.path
    assert len(seen) == 1

    # Upstream changed: the pinned load refuses and leaves nothing behind...
    monkeypatch.setattr(
        "requests.Session.get",
        lambda self, url, **kw: _Response(b"newer", "Thu, 19 Nov 2026 03:00:00 GMT"),
    )
    other = gaz.DumpFile(**{**source.__dict__, "name": "other"})
    with pytest.raises(DatasetError, match="--latest"):
        gaz.fetch(other, directory=tmp_path)
    assert not list(tmp_path.glob("other*"))
    # ...and --latest accepts today's file, dated by Last-Modified, with its own checksum.
    latest = gaz.fetch(other, latest=True, directory=tmp_path)
    assert latest.path.name == "other-2026-11-19.txt"
    assert latest.commit == "latest" and latest.sha256 == hashlib.sha256(b"newer").hexdigest()


# --- Search ------------------------------------------------------------------------------------


def search(client, q: str, limit: int | None = None):
    path = f"{API}/reference/places?q={q}" + (f"&limit={limit}" if limit else "")
    return call(client, "GET", path)


@pytest.fixture
def member_client(client):
    load_gazetteer()
    with as_owner():
        member = UserFactory()
    login(client, member)
    return client


def test_search_ranks_exact_name_then_population(member_client):
    rows = search(member_client, "synthv").json()
    assert [r["id"] for r in rows] == [9000002, 9000001, 9000003, 9000101]
    exact = search(member_client, "Synthville").json()
    assert [r["id"] for r in exact][:2] == [9000001, 9000003]  # exact names before "Falls"
    first = exact[0]
    assert first == {
        "id": 9000001,
        "name": "Synthville",
        "admin1": "Kansas",
        "admin1_code": "KS",
        "country_code": "US",
        "country": "United States",
        "population": 48000,
        "feature_code": "PPLA2",
        "timezone": "America/Chicago",
        "lon": -97.5,
        "lat": 37.5,
    }


def test_search_matches_ascii_names_and_narrows_by_state_or_country(member_client):
    assert [r["id"] for r in search(member_client, "zurichsee").json()] == [9000005]
    assert [r["id"] for r in search(member_client, "Zürich").json()] == [9000005]
    both = search(member_client, "paristown").json()
    assert [r["id"] for r in both] == [9000006, 9000007]
    for qualifier in ("TX", "tex", "us", "United"):
        rows = search(member_client, f"paristown, {qualifier}").json()
        assert [r["id"] for r in rows] == [9000007], qualifier
    assert search(member_client, "paristown, synthetic").json()[0]["id"] == 9000006
    assert search(member_client, "s, KS").json() == []  # one letter is too short


def test_search_limits(member_client):
    assert len(search(member_client, "synthv", limit=2).json()) == 2
    assert search(member_client, "s").status_code == 422
    assert search(member_client, "synthv", limit=51).status_code == 422
    assert search(member_client, "x" * 65).status_code == 422
    assert search(member_client, "100%").json() == []  # LIKE wildcards are matched literally
    assert search(member_client, "__").json() == []


def test_search_uses_the_prefix_indexes():
    load_gazetteer()
    places = GeoNamesPlace.objects.filter(
        Q(name__istartswith="wich") | Q(asciiname__istartswith="wich")
    )
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")  # the fixture is tiny
        plan = places.explain()
    assert "geo_gnplace_name_prefix" in plan and "geo_gnplace_ascii_prefix" in plan, plan
