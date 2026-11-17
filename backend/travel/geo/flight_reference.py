"""Flight reference datasets (PLAN.md §12.1, milestone 3.1): OurAirports airports and
OpenFlights airlines and aircraft types.

Downloads come only from each project's official GitHub repository, pinned to a commit and
checked against a known SHA-256 (`--latest` follows the default branch instead and records
whatever commit it got). Requests carry a generic User-Agent and nothing else (CLAUDE.md rule
13). Loading runs as the owner role: the app role can only read `geo_` tables.

Rows are upserted by their dataset id and never deleted, because legs and flight records point
at them; a row that disappears upstream simply stays.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.gis.geos import Point
from django.db import transaction

from .models import (
    AircraftType,
    Airline,
    AirlineCodeHistory,
    Airport,
    AirportCodeHistory,
    DatasetVersion,
)

USER_AGENT = "travel-history-reference-loader/1.0"
TIMEOUT = 60
DATA_DIR = Path(__file__).resolve().parent / "data"
AIRPORT_OVERRIDES = DATA_DIR / "airport_code_overrides.csv"
AIRLINE_OVERRIDES = DATA_DIR / "airline_code_overrides.csv"

ODBL = "ODbL 1.0 (database), DbCL 1.0 (contents)"
ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
OPENFLIGHTS_ATTRIBUTION = "Airline and aircraft data: OpenFlights.org (ODbL)"


class DatasetError(Exception):
    pass


@dataclass(frozen=True)
class Source:
    name: str
    title: str
    repo: str  # GitHub owner/name
    path: str  # file path inside the repository
    commit: str  # pinned commit
    commit_date: dt.date
    sha256: str  # of the file at the pinned commit
    license: str
    license_url: str
    attribution: str
    homepage_url: str

    def url(self, commit: str | None = None) -> str:
        return f"https://raw.githubusercontent.com/{self.repo}/{commit or self.commit}/{self.path}"


AIRPORTS = Source(
    name="ourairports_airports",
    title="OurAirports airports",
    repo="davidmegginson/ourairports-data",
    path="airports.csv",
    commit="845fd124acca9a13d076f3ab957d3eecf46721fc",
    commit_date=dt.date(2026, 11, 17),
    sha256="3d7eeb55961be0f1691e3420ec0e05d4a58be4597c61540511e3e838d7e486f9",
    license="Public domain (Unlicense)",
    license_url="https://unlicense.org/",
    attribution="Airport data: OurAirports (public domain)",
    homepage_url="https://ourairports.com/data/",
)
AIRLINES = Source(
    name="openflights_airlines",
    title="OpenFlights airlines",
    repo="jpatokal/openflights",
    path="data/airlines.dat",
    commit="5d623a6969a1adee7961cf1c9a8a212c4a784713",
    commit_date=dt.date(2017, 2, 2),
    sha256="39be1a432e8b04ebc12860c29281c974a9cb52169c82b2456a835d66ab1548a1",
    license=ODBL,
    license_url=ODBL_URL,
    attribution=OPENFLIGHTS_ATTRIBUTION,
    homepage_url="https://openflights.org/data.php",
)
AIRCRAFT = Source(
    name="openflights_planes",
    title="OpenFlights aircraft types",
    repo="jpatokal/openflights",
    path="data/planes.dat",
    commit="48478874649ebe1d92887ae52fefda2e3d331e32",
    commit_date=dt.date(2019, 5, 7),
    sha256="04ba419335a6ff1fd0e0383d0454ff5162b9e39fc76c0a02271b5fc57483d3ce",
    license=ODBL,
    license_url=ODBL_URL,
    attribution=OPENFLIGHTS_ATTRIBUTION,
    homepage_url="https://openflights.org/data.php",
)
SOURCES = {source.name: source for source in (AIRPORTS, AIRLINES, AIRCRAFT)}


@dataclass(frozen=True)
class Fetched:
    path: Path
    commit: str
    commit_date: dt.date | None
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def cache_dir() -> Path:
    return Path(settings.BULK_DIR) / "reference"


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def _latest_commit(session: requests.Session, source: Source) -> tuple[str, dt.date | None]:
    response = session.get(
        f"https://api.github.com/repos/{source.repo}/commits",
        params={"path": source.path, "per_page": 1},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    entry = response.json()[0]
    when = entry.get("commit", {}).get("committer", {}).get("date", "")
    return entry["sha"], dt.date.fromisoformat(when[:10]) if when else None


def fetch(source: Source, *, latest: bool = False, directory: Path | None = None) -> Fetched:
    """Download the file (or reuse a verified cached copy) and return where it is."""
    directory = directory or cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    session = _session()
    commit, commit_date = (
        _latest_commit(session, source) if latest else (source.commit, source.commit_date)
    )
    suffix = Path(source.path).suffix
    target = directory / f"{source.name}-{commit[:12]}{suffix}"
    expected = source.sha256 if commit == source.commit else None
    if target.exists() and (expected is None or sha256_file(target) == expected):
        return Fetched(target, commit, commit_date, sha256_file(target))
    temporary = target.with_suffix(suffix + ".part")
    with session.get(source.url(commit), stream=True, timeout=TIMEOUT) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for block in response.iter_content(1 << 20):
                handle.write(block)
    digest = sha256_file(temporary)
    if expected is not None and digest != expected:
        temporary.unlink()
        raise DatasetError(f"{source.name}: checksum mismatch ({digest} != pinned {expected})")
    temporary.rename(target)
    return Fetched(target, commit, commit_date, digest)


# --- Parsing helpers ------------------------------------------------------------------------


def _lines(handle) -> Iterator[str]:
    """Lines not starting with '#': comments in the bundled override files and test subsets
    (no dataset row starts with one)."""
    return (line for line in handle if not line.startswith("#"))


def _rows_without_comments(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(_lines(handle))


def _int(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _date(value: str) -> dt.date | None:
    value = (value or "").strip()
    return dt.date.fromisoformat(value) if value else None


def _openflights(value: str) -> str:
    """OpenFlights writes missing values as \\N, and some codes as '-' or 'N/A'."""
    value = (value or "").strip()
    return "" if value in {"\\N", "-", "N/A", "n/a"} else value


CODE_TOKEN = re.compile(r"[A-Z]{3,4}")


def keyword_codes(keywords: str) -> list[str]:
    """Former IATA (3 letters) and ICAO (4 letters) codes listed in OurAirports `keywords`.
    Comma-separated items count when the whole item is a code, or every word of it is (e.g.
    "DEN KDEN"); words inside names ("RAF Kai Tak") don't."""
    codes: list[str] = []
    for item in keywords.split(","):
        words = item.split()
        if words and all(CODE_TOKEN.fullmatch(word) for word in words):
            codes.extend(word for word in words if word not in codes)
    return codes


def _record(source: Source, fetched: Fetched, rows: int) -> DatasetVersion:
    version, _ = DatasetVersion.objects.update_or_create(
        name=source.name,
        defaults={
            "title": source.title,
            "source_url": source.homepage_url
            if fetched.commit == "local"
            else source.url(fetched.commit),
            "homepage_url": source.homepage_url,
            "version": (fetched.commit_date.isoformat() if fetched.commit_date else "")
            + f" ({fetched.commit[:7]})",
            "source_commit": fetched.commit,
            "source_date": fetched.commit_date,
            "checksum": fetched.sha256,
            "license": source.license,
            "license_url": source.license_url,
            "attribution": source.attribution,
            "row_count": rows,
        },
    )
    return version


# --- Airports -------------------------------------------------------------------------------

AIRPORT_FIELDS = [
    "ident",
    "type",
    "name",
    "point",
    "elevation_ft",
    "continent",
    "iso_country",
    "iso_region",
    "municipality",
    "scheduled_service",
    "icao_code",
    "iata_code",
    "gps_code",
    "local_code",
    "keywords",
]


def _airports(path: Path) -> Iterator[Airport]:
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(_lines(handle)):
            try:
                point = Point(float(row["longitude_deg"]), float(row["latitude_deg"]), srid=4326)
            except (TypeError, ValueError):
                continue
            yield Airport(
                ourairports_id=int(row["id"]),
                ident=row["ident"][:16],
                type=row["type"][:32],
                name=row["name"][:200],
                point=point,
                elevation_ft=_int(row["elevation_ft"]),
                continent=row["continent"][:2],
                iso_country=row["iso_country"][:2],
                iso_region=row["iso_region"][:8],
                municipality=row["municipality"][:100],
                scheduled_service=row["scheduled_service"] == "yes",
                icao_code=row.get("icao_code", "")[:4],
                iata_code=row["iata_code"][:3],
                gps_code=row["gps_code"][:8],
                local_code=row["local_code"][:8],
                keywords=row["keywords"],
            )


def _batches(items: Iterable, size: int) -> Iterator[list]:
    batch: list = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def load_airports(fetched: Fetched, overrides: Path = AIRPORT_OVERRIDES) -> DatasetVersion:
    count = 0
    with transaction.atomic():
        for batch in _batches(_airports(fetched.path), 5000):
            Airport.objects.bulk_create(
                batch,
                update_conflicts=True,
                unique_fields=["ourairports_id"],
                update_fields=AIRPORT_FIELDS,
            )
            count += len(batch)
        apply_airport_overrides(overrides)
        return _record(AIRPORTS, fetched, count)


def apply_airport_overrides(overrides: Path = AIRPORT_OVERRIDES) -> None:
    """Closure dates and bundled overrides first, then the keyword-derived history (whose
    validity ends at the closure date). Manual rows entered in the app are left alone."""
    rows = list(_rows_without_comments(overrides))
    by_ident = {
        airport.ident: airport
        for airport in Airport.objects.filter(ident__in={row["ident"] for row in rows})
    }
    AirportCodeHistory.objects.filter(
        source__in=[AirportCodeHistory.Source.BUNDLED, AirportCodeHistory.Source.KEYWORDS]
    ).delete()
    bundled = []
    for row in rows:
        airport = by_ident.get(row["ident"])
        if airport is None:
            continue  # not in this dataset version
        if last := _date(row["last_service"]):
            Airport.objects.filter(pk=airport.pk).update(closed_on=last)
        bundled.append(
            AirportCodeHistory(
                code=row["code"].strip().upper(),
                airport=airport,
                valid_from=_date(row["valid_from"]),
                valid_to=_date(row["valid_to"]),
                source=AirportCodeHistory.Source.BUNDLED,
                note=row["note"][:255],
            )
        )
    AirportCodeHistory.objects.bulk_create(bundled)
    derived = []
    for airport_id, keywords, closed_on in (
        Airport.objects.filter(type="closed")
        .exclude(keywords="")
        .values_list("pk", "keywords", "closed_on")
    ):
        for code in keyword_codes(keywords):
            derived.append(
                AirportCodeHistory(
                    code=code,
                    airport_id=airport_id,
                    valid_to=closed_on,
                    source=AirportCodeHistory.Source.KEYWORDS,
                )
            )
    AirportCodeHistory.objects.bulk_create(derived, batch_size=5000)


# --- Airlines and aircraft ------------------------------------------------------------------


def load_airlines(fetched: Fetched, overrides: Path = AIRLINE_OVERRIDES) -> DatasetVersion:
    airlines = []
    with fetched.path.open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(_lines(handle)):
            if len(row) < 8 or _int(row[0]) is None or int(row[0]) < 1:
                continue  # "-1 Unknown" is a placeholder, not an airline
            airlines.append(
                Airline(
                    openflights_id=int(row[0]),
                    name=_openflights(row[1])[:200],
                    alias=_openflights(row[2])[:200],
                    iata=_openflights(row[3]).upper()[:3],
                    icao=_openflights(row[4]).upper()[:4],
                    callsign=_openflights(row[5])[:100],
                    country=_openflights(row[6])[:100],
                    active=row[7].strip().upper() == "Y",
                )
            )
    with transaction.atomic():
        Airline.objects.bulk_create(
            airlines,
            batch_size=2000,
            update_conflicts=True,
            unique_fields=["openflights_id"],
            update_fields=["name", "alias", "iata", "icao", "callsign", "country", "active"],
        )
        apply_airline_overrides(overrides)
        return _record(AIRLINES, fetched, len(airlines))


def apply_airline_overrides(overrides: Path = AIRLINE_OVERRIDES) -> None:
    rows = list(_rows_without_comments(overrides))
    ids = dict(
        Airline.objects.filter(
            openflights_id__in={int(row["openflights_id"]) for row in rows}
        ).values_list("openflights_id", "pk")
    )
    AirlineCodeHistory.objects.all().delete()
    AirlineCodeHistory.objects.bulk_create(
        AirlineCodeHistory(
            code=row["code"].strip().upper(),
            airline_id=ids[int(row["openflights_id"])],
            valid_from=_date(row["valid_from"]),
            valid_to=_date(row["valid_to"]),
            note=row["note"][:255],
        )
        for row in rows
        if int(row["openflights_id"]) in ids
    )


def load_aircraft(fetched: Fetched) -> DatasetVersion:
    with fetched.path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.reader(_lines(handle)) if len(row) >= 3 and row[0].strip()]
    with transaction.atomic():
        existing = {aircraft.name: aircraft for aircraft in AircraftType.objects.all()}
        for row in rows:
            name = row[0].strip()[:200]
            iata = _openflights(row[1]).upper()[:4]
            icao = _openflights(row[2]).upper()[:4]
            current = existing.get(name)
            if current is None:
                existing[name] = AircraftType.objects.create(name=name, iata=iata, icao=icao)
            elif (current.iata, current.icao) != (iata, icao):
                current.iata, current.icao = iata, icao
                current.save(update_fields=["iata", "icao"])
        return _record(AIRCRAFT, fetched, len(rows))


LOADERS = {
    AIRPORTS.name: load_airports,
    AIRLINES.name: load_airlines,
    AIRCRAFT.name: load_aircraft,
}


def from_local_file(source: Source, path: Path) -> Fetched:
    """A file supplied by hand (tests, offline loads): recorded with its own checksum and the
    pinned commit only if it matches the pinned file."""
    digest = sha256_file(path)
    if digest == source.sha256:
        return Fetched(path, source.commit, source.commit_date, digest)
    return Fetched(path, "local", None, digest)


def describe(fetched: Fetched) -> str:
    when = f" ({fetched.commit_date.isoformat()})" if fetched.commit_date else ""
    return f"{fetched.path.name} commit {fetched.commit[:12]}{when} sha256 {fetched.sha256[:16]}"
