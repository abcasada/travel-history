"""Natural Earth admin-0/admin-1 and US Census county boundaries (milestone 6.1, item 14a-1;
D-112): the polygons offline reverse geocoding (travel/geo/reverse.py) and the territory
statistics (statistics.md §15.2) look points up in.

Natural Earth comes from its official GitHub repository, pinned to the v5.1.2 release commit
and checked against a known SHA-256, the same way as the flight datasets (D-88;
flight_reference.fetch). The Census file sits at a URL named by its vintage year, so it is
pinned like the GeoNames dumps (D-94): URL + SHA-256, the verified copy in `/bulk/reference`
is the pin, and `--latest` accepts a reissued file and records its own checksum. Requests carry
a generic User-Agent and nothing else (rule 13).

Rows are upserted by Natural Earth's `ne_id` and the Census GEOID and never deleted, like the
other reference data. Invalid polygons are repaired in the database after each load.
"""

from __future__ import annotations

import datetime as dt
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

from django.contrib.gis.gdal import CoordTransform, DataSource, SpatialReference
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.db import connection, transaction

from .flight_reference import (
    TIMEOUT,
    DatasetError,
    Fetched,
    Source,
    _batches,
    _record,
    _session,
    cache_dir,
    sha256_file,
)
from .flight_reference import fetch as fetch_github
from .flight_reference import from_local_file as github_local_file
from .models import Country, DatasetVersion, Region, UsCounty

PUBLIC_DOMAIN = "Public domain"
NE_LICENSE_URL = "https://www.naturalearthdata.com/about/terms-of-use/"
NE_ATTRIBUTION = "Boundaries: Natural Earth (public domain)"
NE_HOMEPAGE = "https://www.naturalearthdata.com/"
NE_REPO = "nvkelso/natural-earth-vector"
NE_COMMIT = "f1890d9f152c896d250a77557a5751a93d494776"  # tag v5.1.2
NE_COMMIT_DATE = dt.date(2022, 5, 13)

ADMIN0 = Source(
    name="naturalearth_admin0",
    title="Natural Earth countries (1:10m, v5.1.2)",
    repo=NE_REPO,
    path="geojson/ne_10m_admin_0_countries.geojson",
    commit=NE_COMMIT,
    commit_date=NE_COMMIT_DATE,
    sha256="239eec57ac17f100a11e2536cffc56752c318b50ae765b0918ff7aab4ce8f255",
    license=PUBLIC_DOMAIN,
    license_url=NE_LICENSE_URL,
    attribution=NE_ATTRIBUTION,
    homepage_url=NE_HOMEPAGE,
)
ADMIN1 = Source(
    name="naturalearth_admin1",
    title="Natural Earth states and provinces (1:10m, v5.1.2)",
    repo=NE_REPO,
    path="geojson/ne_10m_admin_1_states_provinces.geojson",
    commit=NE_COMMIT,
    commit_date=NE_COMMIT_DATE,
    sha256="22d0e3ad85eb3e27f17cabf8ba2d50e554fbc27a87796ff891d958185da62fb5",
    license=PUBLIC_DOMAIN,
    license_url=NE_LICENSE_URL,
    attribution=NE_ATTRIBUTION,
    homepage_url=NE_HOMEPAGE,
)


@dataclass(frozen=True)
class UrlFile:
    """A file at a stable URL that is not a git commit (the Census vintage)."""

    name: str
    title: str
    url: str
    snapshot: dt.date  # Last-Modified of the pinned file
    sha256: str
    license: str
    license_url: str
    attribution: str
    homepage_url: str


COUNTIES = UrlFile(
    name="census_counties",
    title="US Census cartographic boundary counties (2025, 1:500k)",
    url="https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_500k.zip",
    snapshot=dt.date(2026, 4, 23),
    sha256="aa976c00b181939755d0da757f4c7c2dc0103c3b3b4530fb2a91c2bb62fc777c",
    license="Public domain (US federal government work)",
    license_url="https://www.census.gov/about/policies/open-gov/open-data.html",
    attribution="US counties: US Census Bureau cartographic boundary files (public domain)",
    homepage_url="https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html",
)

GITHUB_SOURCES = {ADMIN0.name: ADMIN0, ADMIN1.name: ADMIN1}
SOURCE_NAMES = [ADMIN0.name, ADMIN1.name, COUNTIES.name]


# --- Fetching ---------------------------------------------------------------------------------


def _url_target(directory: Path, source: UrlFile, digest: str) -> Path:
    suffix = Path(source.url).suffix
    return directory / f"{source.name}-{digest[:12]}{suffix}"


def fetch_url_file(
    source: UrlFile, *, latest: bool = False, directory: Path | None = None
) -> Fetched:
    """The pinned file (cached copy, else a download that must still match), or with `latest`
    whatever the URL serves now, recorded with its own checksum and Last-Modified date."""
    directory = directory or cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    pinned = _url_target(directory, source, source.sha256)
    if not latest and pinned.exists() and sha256_file(pinned) == source.sha256:
        return Fetched(pinned, "pinned", source.snapshot, source.sha256)
    temporary = directory / f"{source.name}.part"
    with _session().get(source.url, stream=True, timeout=TIMEOUT) as response:
        response.raise_for_status()
        modified = response.headers.get("Last-Modified")
        with temporary.open("wb") as handle:
            for block in response.iter_content(1 << 20):
                handle.write(block)
    digest = sha256_file(temporary)
    if digest == source.sha256:
        temporary.rename(pinned)
        return Fetched(pinned, "pinned", source.snapshot, digest)
    if not latest:
        temporary.unlink()
        raise DatasetError(
            f"{source.name}: upstream changed since the pinned file of {source.snapshot} "
            f"({digest[:16]} != {source.sha256[:16]}); run with --latest to load it and "
            "record its checksum"
        )
    snapshot = parsedate_to_datetime(modified).date() if modified else dt.date.today()
    target = _url_target(directory, source, digest)
    temporary.rename(target)
    return Fetched(target, "latest", snapshot, digest)


def fetch(name: str, *, latest: bool = False, directory: Path | None = None) -> Fetched:
    if name == COUNTIES.name:
        return fetch_url_file(COUNTIES, latest=latest, directory=directory)
    return fetch_github(GITHUB_SOURCES[name], latest=latest, directory=directory)


def from_local_file(name: str, path: Path) -> Fetched:
    """A file supplied by hand (tests, offline loads), recorded with its own checksum."""
    if name in GITHUB_SOURCES:
        return github_local_file(GITHUB_SOURCES[name], path)
    digest = sha256_file(path)
    if digest == COUNTIES.sha256:
        return Fetched(path, "pinned", COUNTIES.snapshot, digest)
    return Fetched(path, "local", None, digest)


def _record_url_file(source: UrlFile, fetched: Fetched, rows: int) -> DatasetVersion:
    when = fetched.commit_date.isoformat() if fetched.commit_date else "local"
    version, _ = DatasetVersion.objects.update_or_create(
        name=source.name,
        defaults={
            "title": source.title,
            "source_url": source.url,
            "homepage_url": source.homepage_url,
            "version": f"{when} (sha256 {fetched.sha256[:12]})",
            "source_commit": "",
            "source_date": fetched.commit_date,
            "checksum": fetched.sha256,
            "license": source.license,
            "license_url": source.license_url,
            "attribution": source.attribution,
            "row_count": rows,
        },
    )
    return version


# --- Reading ----------------------------------------------------------------------------------


def _ogr_path(path: Path) -> str:
    """What GDAL should open: the file itself, or the shapefile (else GeoJSON) inside a zip,
    read in place through /vsizip/."""
    if not zipfile.is_zipfile(path):
        return str(path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    for suffix in (".shp", ".geojson", ".json"):
        member = next((n for n in names if n.lower().endswith(suffix)), None)
        if member:
            return f"/vsizip/{path}/{member}"
    raise DatasetError(f"{path.name}: no shapefile or GeoJSON inside the zip")


def _features(path: Path) -> Iterator[tuple[dict[str, object], MultiPolygon]]:
    """(attributes, MultiPolygon in SRID 4326) per feature; features without an areal
    geometry are skipped."""
    source = DataSource(_ogr_path(path), encoding="utf-8")
    layer = source[0]
    fields = list(layer.fields)
    wgs84 = SpatialReference(4326)
    # One transformation for the whole layer (the Census file is NAD83): building it per
    # feature, as GEOSGeometry.transform(4326) does, took most of the load time.
    to_wgs84 = (
        CoordTransform(layer.srs, wgs84)
        if layer.srs is not None and layer.srs.srid not in (None, 4326)
        else None
    )
    for feature in layer:
        ogr = feature.geom
        if ogr is None:
            continue
        if to_wgs84 is not None:
            ogr.transform(to_wgs84)
        geom: GEOSGeometry = ogr.geos
        geom.srid = 4326
        if isinstance(geom, Polygon):
            geom = MultiPolygon(geom, srid=4326)
        if not isinstance(geom, MultiPolygon):
            continue
        yield {name: feature.get(name) for name in fields}, geom


def _text(value: object, length: int) -> str:
    """Natural Earth writes "no value" as -99 (and some empty fields as None)."""
    text = "" if value is None else str(value).strip()
    return "" if text in {"-99", "None"} else text[:length]


def _bigint(value: object) -> int | None:
    try:
        number = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _get(attributes: dict[str, object], *names: str) -> object:
    """The first attribute present among `names` (Natural Earth's admin-0 fields are upper
    case, its admin-1 fields lower case)."""
    for name in names:
        if name in attributes:
            return attributes[name]
    return None


def repair(table: str) -> int:
    """Make invalid polygons valid (keeping only their areal parts) so containment tests are
    reliable. Returns the number of rows repaired."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {table}
               SET geom = ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3))
             WHERE NOT ST_IsValid(geom)
            """  # noqa: S608 (table names are constants below)
        )
        return cursor.rowcount


# --- Loaders ----------------------------------------------------------------------------------

BATCH = 200  # rows per INSERT: admin-1 polygons run to megabytes each


def _upsert(model, rows: Iterator, unique: str, fields: list[str]) -> int:
    count = 0
    for batch in _batches(rows, BATCH):
        model.objects.bulk_create(
            batch, update_conflicts=True, unique_fields=[unique], update_fields=fields
        )
        count += len(batch)
    return count


def _countries(path: Path) -> Iterator[Country]:
    for a, geom in _features(path):
        ne_id = _bigint(_get(a, "NE_ID", "ne_id"))
        if ne_id is None:
            continue
        iso_a2 = _text(_get(a, "ISO_A2_EH", "iso_a2_eh"), 2)
        yield Country(
            ne_id=ne_id,
            iso_a2=iso_a2 if len(iso_a2) == 2 else "",
            iso_a3=_text(_get(a, "ISO_A3_EH", "iso_a3_eh"), 3),
            adm0_a3=_text(_get(a, "ADM0_A3", "adm0_a3"), 3),
            name=_text(_get(a, "NAME", "name"), 200),
            geom=geom,
        )


def _regions(path: Path) -> Iterator[Region]:
    for a, geom in _features(path):
        ne_id = _bigint(_get(a, "ne_id", "NE_ID"))
        if ne_id is None:
            continue
        iso_a2 = _text(_get(a, "iso_a2", "ISO_A2"), 2)
        yield Region(
            ne_id=ne_id,
            iso_3166_2=_text(_get(a, "iso_3166_2", "ISO_3166_2"), 16),
            name=_text(_get(a, "name", "NAME"), 200),
            country_iso_a2=iso_a2 if len(iso_a2) == 2 else "",
            adm1_code=_text(_get(a, "adm1_code", "ADM1_CODE"), 16),
            geonames_id=_bigint(_get(a, "gn_id", "GN_ID")),
            geom=geom,
        )


def _counties(path: Path) -> Iterator[UsCounty]:
    for a, geom in _features(path):
        geoid = _text(_get(a, "GEOID"), 5)
        if len(geoid) != 5:
            continue
        yield UsCounty(
            geoid=geoid,
            name=_text(_get(a, "NAME"), 100),
            name_lsad=_text(_get(a, "NAMELSAD"), 150),
            state_fips=_text(_get(a, "STATEFP"), 2),
            state_abbr=_text(_get(a, "STUSPS"), 2),
            geom=geom,
        )


def load_admin0(fetched: Fetched) -> DatasetVersion:
    with transaction.atomic():
        rows = _upsert(
            Country,
            _countries(fetched.path),
            "ne_id",
            ["iso_a2", "iso_a3", "adm0_a3", "name", "geom"],
        )
        repair("geo_country")
        return _record(ADMIN0, fetched, rows)


def load_admin1(fetched: Fetched) -> DatasetVersion:
    with transaction.atomic():
        rows = _upsert(
            Region,
            _regions(fetched.path),
            "ne_id",
            ["iso_3166_2", "name", "country_iso_a2", "adm1_code", "geonames_id", "geom"],
        )
        repair("geo_region")
        return _record(ADMIN1, fetched, rows)


def load_counties(fetched: Fetched) -> DatasetVersion:
    with transaction.atomic():
        rows = _upsert(
            UsCounty,
            _counties(fetched.path),
            "geoid",
            ["name", "name_lsad", "state_fips", "state_abbr", "geom"],
        )
        repair("geo_uscounty")
        return _record_url_file(COUNTIES, fetched, rows)


LOADERS = {ADMIN0.name: load_admin0, ADMIN1.name: load_admin1, COUNTIES.name: load_counties}
