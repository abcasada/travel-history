"""GeoNames gazetteer (milestone 6.1, part 1; D-94): place names for finding a stop by city.

Loaded: `cities500` worldwide, the US populated places below 500 people from the `US` dump
(small Kansas towns matter), and the country and admin-1 names. Everything stays on the
server: searches run against these tables, never a hosted geocoder (D-20, rule 13).

GeoNames regenerates its dump files daily at unversioned URLs, so a pin cannot name a commit
the way the flight datasets do (D-88). Instead each file is pinned to a snapshot date and its
SHA-256: the verified copy cached in `/bulk/reference` is the pinned version, and a fresh
download is accepted only if it still matches. `--latest` downloads today's files, records
their checksums and dates, and caches them under that date. Requests carry a generic
User-Agent and nothing else.

Rows are upserted by `geonameid` and never deleted, like the other reference data.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

from django.contrib.gis.geos import Point
from django.db import connection, transaction
from django.db.models import Case, IntegerField, Q, Value, When

from .flight_reference import (
    TIMEOUT,
    DatasetError,
    Fetched,
    _batches,
    _session,
    cache_dir,
    sha256_file,
)
from .models import DatasetVersion, GeoNamesAdmin1, GeoNamesCountry, GeoNamesPlace

BASE_URL = "https://download.geonames.org/export/dump/"
HOMEPAGE = "https://www.geonames.org/"
LICENSE = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
ATTRIBUTION = "Place names: GeoNames (geonames.org), CC BY 4.0"

# Populated places from the US dump that a stop could be: not neighbourhoods (PPLX),
# abandoned, historical or destroyed places (PPLQ, PPLH, PPLW), or historical capitals (PPLCH).
US_FEATURE_CODES = frozenset(
    {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLL", "PPLS", "PPLF", "STLMT"}
)


@dataclass(frozen=True)
class DumpFile:
    name: str  # DatasetVersion name
    title: str
    filename: str  # under export/dump/
    member: str  # file inside the zip ("" for plain text files)
    snapshot: dt.date  # Last-Modified date of the pinned file
    sha256: str  # of the pinned file

    def url(self) -> str:
        return BASE_URL + self.filename


COUNTRIES = DumpFile(
    name="geonames_countries",
    title="GeoNames country names",
    filename="countryInfo.txt",
    member="",
    snapshot=dt.date(2026, 11, 18),
    sha256="79f8f59ea01cbb40438bf1856dd6c2ff201f03f8fc72d0530b2646aaf603ef04",
)
ADMIN1 = DumpFile(
    name="geonames_admin1",
    title="GeoNames state and province names",
    filename="admin1CodesASCII.txt",
    member="",
    snapshot=dt.date(2026, 11, 18),
    sha256="2e4867f5397acb056ea26377601b57af37cb4c81399770225018e9e439e91ad3",
)
CITIES = DumpFile(
    name="geonames_cities500",
    title="GeoNames places with 500+ people",
    filename="cities500.zip",
    member="cities500.txt",
    snapshot=dt.date(2026, 11, 18),
    sha256="682a5f7e48463d64663755b3a4e17219dc4f27cea35d4b88c194d73a9bf453d1",
)
US_PLACES = DumpFile(
    name="geonames_us_places",
    title="GeoNames US populated places",
    filename="US.zip",
    member="US.txt",
    snapshot=dt.date(2026, 11, 18),
    sha256="3434a3a5c5c4d19193f5a975d8ab5a61f56d2a7392a72a2cdf751c9e0d973ca9",
)
# Load order matters only for speed: names are copied onto places once at the end.
SOURCES = {source.name: source for source in (COUNTRIES, ADMIN1, CITIES, US_PLACES)}


def _target(directory: Path, source: DumpFile, snapshot: dt.date) -> Path:
    suffix = source.filename.rsplit(".", 1)[1]
    return directory / f"{source.name}-{snapshot.isoformat()}.{suffix}"


def fetch(source: DumpFile, *, latest: bool = False, directory: Path | None = None) -> Fetched:
    """The pinned snapshot (cached copy, else a download that must still match), or with
    `latest` today's file, recorded with its own checksum and Last-Modified date."""
    directory = directory or cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    pinned = _target(directory, source, source.snapshot)
    if not latest and pinned.exists() and sha256_file(pinned) == source.sha256:
        return Fetched(pinned, "pinned", source.snapshot, source.sha256)
    temporary = directory / f"{source.name}.part"
    with _session().get(source.url(), stream=True, timeout=TIMEOUT) as response:
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
            f"{source.name}: upstream changed since the pinned snapshot "
            f"{source.snapshot} ({digest[:16]} != {source.sha256[:16]}); "
            "run with --latest to load today's file and record its checksum"
        )
    snapshot = parsedate_to_datetime(modified).date() if modified else dt.date.today()
    target = _target(directory, source, snapshot)
    temporary.rename(target)
    return Fetched(target, "latest", snapshot, digest)


def from_local_file(source: DumpFile, path: Path) -> Fetched:
    """A file supplied by hand (tests, offline loads), recorded with its own checksum."""
    digest = sha256_file(path)
    if digest == source.sha256:
        return Fetched(path, "pinned", source.snapshot, digest)
    return Fetched(path, "local", None, digest)


def _record(source: DumpFile, fetched: Fetched, rows: int) -> DatasetVersion:
    version, _ = DatasetVersion.objects.update_or_create(
        name=source.name,
        defaults={
            "title": source.title,
            "source_url": source.url(),
            "homepage_url": HOMEPAGE,
            "version": f"{fetched.commit_date.isoformat() if fetched.commit_date else 'local'}"
            f" (sha256 {fetched.sha256[:12]})",
            "source_commit": "",
            "source_date": fetched.commit_date,
            "checksum": fetched.sha256,
            "license": LICENSE,
            "license_url": LICENSE_URL,
            "attribution": ATTRIBUTION,
            "row_count": rows,
        },
    )
    return version


# --- Parsing ---------------------------------------------------------------------------------


def _text_lines(fetched: Fetched, member: str) -> Iterator[str]:
    """Lines of a plain file, or of `member` inside a zip; comment lines ('#') skipped."""
    if member and zipfile.is_zipfile(fetched.path):
        with zipfile.ZipFile(fetched.path) as archive, archive.open(member) as raw:
            for line in io.TextIOWrapper(raw, encoding="utf-8"):
                if not line.startswith("#"):
                    yield line.rstrip("\n")
        return
    with fetched.path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("#"):
                yield line.rstrip("\n")


def _int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _places(fetched: Fetched, member: str, *, us_filter: bool) -> Iterator[GeoNamesPlace]:
    for line in _text_lines(fetched, member):
        f = line.split("\t")
        if len(f) < 19 or _int(f[0]) is None:
            continue
        if us_filter and (f[6] != "P" or f[7] not in US_FEATURE_CODES):
            continue
        try:
            point = Point(float(f[5]), float(f[4]), srid=4326)
        except ValueError:
            continue
        yield GeoNamesPlace(
            geonameid=int(f[0]),
            name=f[1][:200],
            asciiname=f[2][:200],
            point=point,
            feature_class=f[6][:1],
            feature_code=f[7][:10],
            country_code=f[8][:2],
            admin1_code=f[10][:20],
            admin2_code=f[11][:80],
            population=_int(f[14]) or 0,
            timezone=f[17][:40],
        )


PLACE_FIELDS = [
    "name",
    "asciiname",
    "point",
    "feature_class",
    "feature_code",
    "country_code",
    "admin1_code",
    "admin2_code",
    "population",
    "timezone",
]


# --- Loaders ---------------------------------------------------------------------------------


def load_countries(fetched: Fetched) -> DatasetVersion:
    rows = []
    for line in _text_lines(fetched, ""):
        f = line.split("\t")
        if len(f) < 17 or len(f[0]) != 2:
            continue
        rows.append(
            GeoNamesCountry(iso_a2=f[0], iso_a3=f[1][:3], name=f[4][:200], geonameid=_int(f[16]))
        )
    with transaction.atomic():
        GeoNamesCountry.objects.bulk_create(
            rows,
            update_conflicts=True,
            unique_fields=["iso_a2"],
            update_fields=["iso_a3", "name", "geonameid"],
        )
        return _record(COUNTRIES, fetched, len(rows))


def load_admin1(fetched: Fetched) -> DatasetVersion:
    rows = []
    for line in _text_lines(fetched, ""):
        f = line.split("\t")
        if len(f) < 4 or "." not in f[0]:
            continue
        rows.append(
            GeoNamesAdmin1(
                code=f[0][:32], name=f[1][:200], asciiname=f[2][:200], geonameid=_int(f[3])
            )
        )
    with transaction.atomic():
        GeoNamesAdmin1.objects.bulk_create(
            rows,
            batch_size=2000,
            update_conflicts=True,
            unique_fields=["code"],
            update_fields=["name", "asciiname", "geonameid"],
        )
        return _record(ADMIN1, fetched, len(rows))


def _load_places(source: DumpFile, fetched: Fetched, *, us_filter: bool) -> DatasetVersion:
    count = 0
    with transaction.atomic():
        for batch in _batches(_places(fetched, source.member, us_filter=us_filter), 5000):
            GeoNamesPlace.objects.bulk_create(
                batch,
                update_conflicts=True,
                unique_fields=["geonameid"],
                update_fields=PLACE_FIELDS,
            )
            count += len(batch)
        return _record(source, fetched, count)


def load_cities(fetched: Fetched) -> DatasetVersion:
    return _load_places(CITIES, fetched, us_filter=False)


def load_us_places(fetched: Fetched) -> DatasetVersion:
    return _load_places(US_PLACES, fetched, us_filter=True)


LOADERS = {
    COUNTRIES.name: load_countries,
    ADMIN1.name: load_admin1,
    CITIES.name: load_cities,
    US_PLACES.name: load_us_places,
}


def copy_names() -> int:
    """Copy admin-1 and country names onto places (run after any load). Returns rows changed."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE geo_geonamesplace p
               SET admin1_name = coalesce(a.name, ''), country_name = coalesce(c.name, '')
              FROM geo_geonamesplace q
              LEFT JOIN geo_geonamesadmin1 a ON a.code = q.country_code || '.' || q.admin1_code
              LEFT JOIN geo_geonamescountry c ON c.iso_a2 = q.country_code
             WHERE p.geonameid = q.geonameid
               AND (p.admin1_name IS DISTINCT FROM coalesce(a.name, '')
                    OR p.country_name IS DISTINCT FROM coalesce(c.name, ''))
            """
        )
        return cursor.rowcount


# --- Search ----------------------------------------------------------------------------------


def search(q: str, limit: int) -> list[GeoNamesPlace]:
    """Places whose name starts with `q`, most populous first (an exact name first of all).
    "Paris, TX" narrows by state or country: a code (TX, US) or the start of a name (Tex,
    United)."""
    term, _, qualifier = q.partition(",")
    term, qualifier = term.strip(), qualifier.strip()
    if len(term) < 2:
        return []
    places = GeoNamesPlace.objects.filter(
        Q(name__istartswith=term) | Q(asciiname__istartswith=term)
    )
    if qualifier:
        places = places.filter(
            Q(admin1_code__iexact=qualifier)
            | Q(admin1_name__istartswith=qualifier)
            | Q(country_code__iexact=qualifier)
            | Q(country_name__istartswith=qualifier)
        )
    exact = Q(name__iexact=term) | Q(asciiname__iexact=term)
    return list(
        places.annotate(
            exact_rank=Case(
                When(exact, then=Value(0)), default=Value(1), output_field=IntegerField()
            )
        ).order_by("exact_rank", "-population", "name", "geonameid")[:limit]
    )
