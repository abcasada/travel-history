"""Boundary loaders and offline reverse geocoding (item 14a-1, D-112): Natural Earth and Census
loaders on SYNTHETIC boxes, pinned downloads with a generic User-Agent, and the "near <town>"
labels from the boundaries plus the gazetteer, read as the app role."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from django.contrib.gis.geos import Point
from django.db import DatabaseError, transaction

from tests.helpers import as_owner, current_role
from tests.test_gazetteer import _Response, load_gazetteer
from travel.geo import boundaries as bnd
from travel.geo.flight_reference import DatasetError
from travel.geo.models import Country, DatasetVersion, GeoNamesPlace, Region, UsCounty
from travel.geo.reverse import reverse_geocode

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "boundaries"
FILES = {
    bnd.ADMIN0.name: "admin0.geojson",
    bnd.ADMIN1.name: "admin1.geojson",
    bnd.COUNTIES.name: "counties.geojson",
}


def load_boundaries(directory: Path = FIXTURES) -> None:
    with as_owner():
        for name, filename in FILES.items():
            bnd.LOADERS[name](bnd.from_local_file(name, directory / filename))


# --- Loaders -----------------------------------------------------------------------------------


def test_load_records_versions_codes_and_repairs_invalid_polygons():
    load_boundaries()
    # The feature without a Natural Earth id and the county with a short GEOID are skipped.
    assert set(Country.objects.values_list("ne_id", "iso_a2", "adm0_a3")) == {
        (9200001, "US", "USA"),
        (9200002, "XS", "XSY"),
        (9200003, "", "XDZ"),  # ISO_A2_EH -99: no code
        (9200004, "XE", "XSE"),
    }
    assert Country.objects.get(ne_id=9200003).iso_a3 == ""
    # A single Polygon is stored as a MultiPolygon; the bow-tie is made valid (two triangles).
    disputed = Country.objects.get(ne_id=9200003).geom
    assert disputed.geom_type == "MultiPolygon" and disputed.valid and len(disputed) == 2
    kansas = Region.objects.get(iso_3166_2="US-KS")
    assert (kansas.name, kansas.country_iso_a2, kansas.adm1_code, kansas.geonames_id) == (
        "Kansas",
        "US",
        "USA-9001",
        4273857,
    )
    assert Region.objects.get(iso_3166_2="XS-01").geonames_id is None  # gn_id -99
    assert set(UsCounty.objects.values_list("geoid", "name_lsad", "state_abbr")) == {
        ("20901", "Synth County", "KS"),
        ("20903", "", "KS"),
    }
    versions = {v.name: v for v in DatasetVersion.objects.all()}
    assert set(versions) == set(bnd.SOURCE_NAMES)
    ne = versions["naturalearth_admin0"]
    assert (ne.row_count, ne.license, ne.attribution) == (
        4,
        "Public domain",
        "Boundaries: Natural Earth (public domain)",
    )
    assert ne.checksum == hashlib.sha256((FIXTURES / "admin0.geojson").read_bytes()).hexdigest()
    assert ne.source_commit == "local"  # a hand-supplied file is not the pinned one
    census = versions["census_counties"]
    assert census.row_count == 2 and census.license.startswith("Public domain")
    assert census.attribution.startswith("US counties: US Census Bureau")
    assert census.version.startswith("local")


def test_reload_is_idempotent_updates_in_place_and_reads_zipped_files(tmp_path):
    load_boundaries()
    ids = dict(Country.objects.values_list("ne_id", "id"))
    data = json.loads((FIXTURES / "admin0.geojson").read_text())
    data["features"][0]["properties"]["NAME"] = "Synthetic States (renamed)"
    renamed = tmp_path / "admin0.geojson"
    renamed.write_text(json.dumps(data))
    counties = tmp_path / "cb_synthetic_county.zip"
    with zipfile.ZipFile(counties, "w") as zf:
        zf.write(FIXTURES / "counties.geojson", "cb_synthetic_county.geojson")
    with as_owner():
        bnd.load_admin0(bnd.from_local_file(bnd.ADMIN0.name, renamed))
        bnd.load_admin0(bnd.from_local_file(bnd.ADMIN0.name, renamed))
        bnd.load_counties(bnd.from_local_file(bnd.COUNTIES.name, counties))
    assert dict(Country.objects.values_list("ne_id", "id")) == ids  # same rows, upserted
    assert Country.objects.get(ne_id=9200001).name == "Synthetic States (renamed)"
    assert UsCounty.objects.count() == 2


def test_rows_missing_upstream_are_kept(tmp_path):
    load_boundaries()
    data = json.loads((FIXTURES / "admin1.geojson").read_text())
    data["features"] = data["features"][:1]
    smaller = tmp_path / "admin1.geojson"
    smaller.write_text(json.dumps(data))
    with as_owner():
        version = bnd.load_admin1(bnd.from_local_file(bnd.ADMIN1.name, smaller))
    assert version.row_count == 1
    assert Region.objects.count() == 3  # reference rows are never deleted


def test_app_role_reads_but_cannot_write_boundaries():
    load_boundaries()
    assert current_role() == "travel_app"
    assert Country.objects.filter(iso_a2="US").exists()
    for statement in (
        lambda: Country.objects.filter(iso_a2="US").update(name="x"),
        lambda: Region.objects.all().delete(),
        lambda: UsCounty.objects.filter(geoid="20901").update(name="x"),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            statement()


# --- Downloads ---------------------------------------------------------------------------------


def test_github_fetch_is_pinned_to_the_release_commit(monkeypatch, tmp_path):
    body = (FIXTURES / "admin0.geojson").read_bytes()
    seen = []

    def fake_get(self, url, **kwargs):
        seen.append((url, dict(self.headers)))
        return _Response(body)

    monkeypatch.setattr("requests.Session.get", fake_get)
    monkeypatch.setitem(
        bnd.GITHUB_SOURCES,
        bnd.ADMIN0.name,
        bnd.Source(**{**bnd.ADMIN0.__dict__, "sha256": hashlib.sha256(body).hexdigest()}),
    )
    fetched = bnd.fetch(bnd.ADMIN0.name, directory=tmp_path)
    url, headers = seen[0]
    assert url == (
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
        "f1890d9f152c896d250a77557a5751a93d494776/geojson/ne_10m_admin_0_countries.geojson"
    )
    assert headers["User-Agent"] == "travel-history-reference-loader/1.0"
    assert not {"Cookie", "Authorization", "From"} & set(headers)
    assert fetched.path.name == "naturalearth_admin0-f1890d9f152c.geojson"
    assert bnd.fetch(bnd.ADMIN0.name, directory=tmp_path).path == fetched.path
    assert len(seen) == 1  # the verified cached copy is used

    monkeypatch.setattr("requests.Session.get", lambda self, url, **kw: _Response(b"tampered"))
    with pytest.raises(DatasetError, match="checksum mismatch"):
        bnd.fetch(bnd.ADMIN0.name, directory=tmp_path / "fresh")


def test_census_fetch_is_pinned_by_checksum(monkeypatch, tmp_path):
    body = (FIXTURES / "counties.geojson").read_bytes()
    seen = []

    def fake_get(self, url, **kwargs):
        seen.append((url, dict(self.headers)))
        return _Response(body, "Thu, 23 Apr 2026 13:45:35 GMT")

    monkeypatch.setattr("requests.Session.get", fake_get)
    source = bnd.UrlFile(**{**bnd.COUNTIES.__dict__, "sha256": hashlib.sha256(body).hexdigest()})
    fetched = bnd.fetch_url_file(source, directory=tmp_path)
    url, headers = seen[0]
    assert url == "https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_500k.zip"
    assert headers["User-Agent"] == "travel-history-reference-loader/1.0"
    assert not {"Cookie", "Authorization", "From"} & set(headers)
    assert fetched.commit == "pinned" and fetched.path.read_bytes() == body
    assert bnd.fetch_url_file(source, directory=tmp_path).path == fetched.path
    assert len(seen) == 1

    # Reissued upstream: the pinned load refuses and leaves nothing behind; --latest accepts it.
    monkeypatch.setattr(
        "requests.Session.get",
        lambda self, url, **kw: _Response(b"reissued", "Mon, 01 Jun 2026 10:00:00 GMT"),
    )
    other = bnd.UrlFile(**{**source.__dict__, "name": "other"})
    with pytest.raises(DatasetError, match="--latest"):
        bnd.fetch_url_file(other, directory=tmp_path)
    assert not list(tmp_path.glob("other*"))
    latest = bnd.fetch_url_file(other, latest=True, directory=tmp_path)
    digest = hashlib.sha256(b"reissued").hexdigest()
    assert latest.commit == "latest" and latest.sha256 == digest
    assert latest.path.name == f"other-{digest[:12]}.zip"
    assert latest.commit_date.isoformat() == "2026-06-01"


# --- Reverse geocoding -------------------------------------------------------------------------


@pytest.fixture
def geodata():
    load_gazetteer()
    load_boundaries()


def add_place(geonameid, name, lon, lat, population, feature_code="PPL", **extra):
    with as_owner():
        GeoNamesPlace.objects.create(
            geonameid=geonameid,
            name=name,
            asciiname=name,
            name_folded=name.lower(),
            point=Point(lon, lat, srid=4326),
            feature_class="P",
            feature_code=feature_code,
            population=population,
            **extra,
        )


def test_label_names_the_town_its_state_and_country(geodata):
    # Synthville Heights (PPLX, 1 km away) is a neighbourhood, not a town.
    result = reverse_geocode(-97.41, 37.6)
    assert result.label == "near Synthville, Kansas, United States"
    assert result.place.geonameid == 9000001 and 13_000 < result.place.distance_m < 14_500
    assert (result.country.code, result.country.name) == ("US", "Synthetic States")
    assert (result.region.code, result.region.name, result.region_geonames_id) == (
        "US-KS",
        "Kansas",
        4273857,
    )
    assert (result.county.code, result.county.name) == ("20901", "Synth County")
    # A county without NAMELSAD falls back to NAME.
    assert reverse_geocode(-96.5, 37.5).county.name == "Fake"


def test_a_bigger_town_a_little_farther_beats_a_hamlet_next_door(geodata):
    add_place(9800001, "Hamlet", -97.55, 37.5, 0, country_code="US", admin1_name="Kansas")
    # 0.9 km from the hamlet, 3.5 km from Synthville (48,000): Synthville.
    assert reverse_geocode(-97.54, 37.5).place.name == "Synthville"
    # 0.7 km from the hamlet, 5 km from Synthville: the hamlet.
    assert reverse_geocode(-97.5565, 37.4965).place.name == "Hamlet"
    add_place(9800002, "Village", -99.5, 35.0, 600, admin1_name="Oklahoma")
    add_place(9800003, "Big City", -99.3, 35.0, 500_000, admin1_name="Oklahoma")
    # 10.5 km from Big City, 7.8 km from the village: Big City.
    assert reverse_geocode(-99.415, 35.0).place.name == "Big City"
    # A village beats a city more than twice its distance off (5.5 km against 12.8 km).
    assert reverse_geocode(-99.44, 35.0).place.name == "Village"


def test_without_a_town_the_label_comes_from_the_boundaries(geodata):
    result = reverse_geocode(-100.5, 34.0)  # nothing within 25 km
    assert result.place is None and result.county is None
    assert result.label == "Oklahoma, Synthetic States"
    sea = reverse_geocode(-30.0, 0.0)
    assert (sea.country, sea.region, sea.county, sea.place) == (None, None, None, None)
    assert sea.label == ""


def test_smallest_containing_area_and_coastal_slack(geodata):
    assert reverse_geocode(4.5, 47.5).country.code == "XE"  # the enclave, not its surround
    assert reverse_geocode(9.0, 47.0).country.code == "XS"
    # 1 km off the (synthetic) coast still counts; 5 km does not.
    assert reverse_geocode(10.013, 47.0).country.code == "XS"
    assert reverse_geocode(10.07, 47.0).country is None
    # Repeated parts are dropped: a town named like its state.
    add_place(9800004, "Synth Canton", 9.9, 47.0, 1000, admin1_name="Synth Canton")
    label = reverse_geocode(9.9, 47.0).label
    assert label == "near Synth Canton, Synthetic Republic"


def test_places_across_the_antimeridian_are_found(geodata):
    add_place(9800005, "Dateline", 179.95, -17.0, 5000, country_name="Synthetic Isles")
    result = reverse_geocode(-179.95, -17.0)
    assert result.place.name == "Dateline" and result.place.distance_m < 11_000
    assert result.label == "near Dateline, Synthetic Isles"


def test_rejects_coordinates_outside_wgs84():
    with pytest.raises(ValueError):
        reverse_geocode(181.0, 0.0)
    with pytest.raises(ValueError):
        reverse_geocode(0.0, -91.0)
