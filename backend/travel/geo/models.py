"""Reference datasets (PLAN.md §5.8). Loaded by management commands running as the owner role;
read-only for the app role (table prefix `geo_`, see travel/core/db_privileges.py). No RLS."""

from django.contrib.gis.db import models as gis
from django.contrib.postgres.indexes import OpClass
from django.db import models
from django.db.models.functions import Upper


class Airport(models.Model):
    """OurAirports `airports.csv` row, including closed airports."""

    ourairports_id = models.IntegerField(unique=True, null=True, blank=True)
    ident = models.CharField(max_length=16, db_index=True)
    type = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    point = gis.PointField(srid=4326)
    elevation_ft = models.IntegerField(null=True, blank=True)
    continent = models.CharField(max_length=2, blank=True)
    iso_country = models.CharField(max_length=2, blank=True)
    iso_region = models.CharField(max_length=8, blank=True)
    municipality = models.CharField(max_length=100, blank=True)
    scheduled_service = models.BooleanField(default=False)
    icao_code = models.CharField(max_length=4, blank=True, db_index=True)
    iata_code = models.CharField(max_length=3, blank=True, db_index=True)
    gps_code = models.CharField(max_length=8, blank=True)
    local_code = models.CharField(max_length=8, blank=True)
    keywords = models.TextField(blank=True)
    closed_on = models.DateField(null=True, blank=True)  # entered manually where known

    def __str__(self) -> str:
        return f"{self.iata_code or self.ident} {self.name}"


class AirportCodeHistory(models.Model):
    """Which airport a code meant at a given date: derived from OurAirports keywords for closed
    airports, plus manual overrides (PLAN.md §12.2)."""

    class Source(models.TextChoices):
        KEYWORDS = "keywords", "OurAirports keywords"
        BUNDLED = "bundled", "Bundled override"  # geo/data/airport_code_overrides.csv
        MANUAL = "manual", "Manual override"

    code = models.CharField(max_length=4, db_index=True)
    airport = models.ForeignKey(Airport, on_delete=models.DB_CASCADE, related_name="code_history")
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices)
    note = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return f"{self.code} → {self.airport_id}"


class Airline(models.Model):
    """OpenFlights `airlines.dat` (ODbL); defunct airlines kept for old flights."""

    openflights_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=200)
    alias = models.CharField(max_length=200, blank=True)
    iata = models.CharField(max_length=3, blank=True, db_index=True)
    icao = models.CharField(max_length=4, blank=True, db_index=True)
    callsign = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    active = models.BooleanField(default=False)
    manual = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name


class AircraftType(models.Model):
    """OpenFlights `planes.dat` (ODbL)."""

    name = models.CharField(max_length=200)
    iata = models.CharField(max_length=4, blank=True, db_index=True)
    icao = models.CharField(max_length=4, blank=True, db_index=True)

    def __str__(self) -> str:
        return self.name


class Country(models.Model):
    """Natural Earth admin-0 (public domain). `iso_a2` comes from ISO_A2_EH."""

    iso_a2 = models.CharField(max_length=2, db_index=True)
    iso_a3 = models.CharField(max_length=3, blank=True)
    name = models.CharField(max_length=200)
    geom = gis.MultiPolygonField(srid=4326)

    def __str__(self) -> str:
        return self.name


class Region(models.Model):
    """Natural Earth admin-1 states/provinces (public domain)."""

    iso_3166_2 = models.CharField(max_length=16, db_index=True)
    name = models.CharField(max_length=200)
    country_iso_a2 = models.CharField(max_length=2, db_index=True)
    adm1_code = models.CharField(max_length=16, blank=True)
    geonames_id = models.BigIntegerField(null=True, blank=True)
    geom = gis.MultiPolygonField(srid=4326)

    def __str__(self) -> str:
        return self.name


class UsCounty(models.Model):
    """US Census cartographic boundary counties (public domain)."""

    geoid = models.CharField(max_length=5, unique=True)
    name = models.CharField(max_length=100)
    name_lsad = models.CharField(max_length=150, blank=True)
    state_fips = models.CharField(max_length=2)
    state_abbr = models.CharField(max_length=2, blank=True)
    geom = gis.MultiPolygonField(srid=4326)

    def __str__(self) -> str:
        return f"{self.name_lsad or self.name}, {self.state_abbr}"


class GeoNamesPlace(models.Model):
    """GeoNames cities500 plus the US populated places below 500 people (CC BY 4.0, attribution
    required). `admin1_name` and `country_name` are copied from the two tables below at load
    time so the city search needs no joins (travel/geo/gazetteer.py)."""

    geonameid = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=200)
    asciiname = models.CharField(max_length=200, blank=True)
    point = gis.PointField(srid=4326)
    feature_class = models.CharField(max_length=1, blank=True)
    feature_code = models.CharField(max_length=10, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    admin1_code = models.CharField(max_length=20, blank=True)
    admin2_code = models.CharField(max_length=80, blank=True)
    population = models.BigIntegerField(default=0)
    timezone = models.CharField(max_length=40, blank=True)
    admin1_name = models.CharField(max_length=200, blank=True)
    country_name = models.CharField(max_length=200, blank=True)
    # `name` lower-cased without accents ("Zürich" -> "zurich"; GeoNames' own asciiname is
    # "Zuerich"), set by the loader: gazetteer.fold().
    name_folded = models.CharField(max_length=200, blank=True)

    class Meta:
        # Prefix search ("wich" -> Wichita): `startswith` on the folded name and `istartswith`
        # (UPPER(col) LIKE 'X%') on asciiname, served by pattern-ops indexes whatever the
        # database collation is.
        indexes = [
            models.Index(
                OpClass("name_folded", name="varchar_pattern_ops"),
                name="geo_gnplace_folded_prefix",
            ),
            models.Index(
                OpClass(Upper("asciiname"), name="text_pattern_ops"),
                name="geo_gnplace_ascii_prefix",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class GeoNamesCountry(models.Model):
    """GeoNames `countryInfo.txt`: country names for the city search (CC BY 4.0)."""

    iso_a2 = models.CharField(max_length=2, primary_key=True)
    iso_a3 = models.CharField(max_length=3, blank=True)
    name = models.CharField(max_length=200)
    geonameid = models.BigIntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name


class GeoNamesAdmin1(models.Model):
    """GeoNames `admin1CodesASCII.txt`: states and provinces, keyed "US.KS" (country code and
    GeoNames' admin-1 code, which is often a FIPS number outside the US)."""

    code = models.CharField(max_length=32, primary_key=True)
    name = models.CharField(max_length=200)
    asciiname = models.CharField(max_length=200, blank=True)
    geonameid = models.BigIntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name


class AirlineCodeHistory(models.Model):
    """Which airline an IATA code meant at a given date, for codes that were reused (Pan Am's
    and TWA's codes, PLAN.md §12.2). Manual overrides only: OpenFlights has no dates."""

    code = models.CharField(max_length=3, db_index=True)
    airline = models.ForeignKey(Airline, on_delete=models.DB_CASCADE, related_name="code_history")
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return f"{self.code} → {self.airline_id}"


class DatasetVersion(models.Model):
    """The loaded version of each reference dataset, shown on the attribution page."""

    name = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=100, blank=True)
    source_url = models.URLField(max_length=500)
    homepage_url = models.URLField(max_length=500, blank=True)
    version = models.CharField(max_length=64, blank=True)
    source_commit = models.CharField(max_length=40, blank=True)
    source_date = models.DateField(null=True, blank=True)
    checksum = models.CharField(max_length=64, blank=True)
    license = models.CharField(max_length=100)
    license_url = models.URLField(max_length=500, blank=True)
    attribution = models.CharField(max_length=255, blank=True)
    row_count = models.IntegerField(default=0)
    loaded_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} {self.version}"
