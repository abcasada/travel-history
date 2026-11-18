"""Imported flights and the reference-data attribution list (PLAN.md §12, §17).

Flight records are their owner's raw history: row-level security returns only the caller's
rows (the queries never filter by owner for permission purposes)."""

import datetime as dt

from django.db.models import Case, IntegerField, Q, Value, When
from ninja import Field, Query, Router, Schema
from ninja.errors import HttpError

from travel.core import policy
from travel.geo.models import Airport, DatasetVersion

from .models import FlightRecord

router = Router(tags=["flights"])


class IssueOut(Schema):
    field: str
    reason: str
    detail: str = ""


class FlightRecordOut(Schema):
    id: int
    import_batch_id: int | None
    row_number: int
    status: str
    problems: list[IssueOut]
    warnings: list[IssueOut]
    trip_key: str
    date: dt.date | None
    date_precision: str
    dep_time: dt.time | None
    arr_time: dt.time | None
    arr_date: dt.date | None
    from_code: str
    to_code: str
    origin_airport_id: int | None
    destination_airport_id: int | None
    origin_iata: str | None
    destination_iata: str | None
    airline_text: str
    airline_id: int | None
    airline_name: str | None
    flight_number: str
    aircraft_text: str
    aircraft_type_id: int | None
    registration: str
    seat: str
    cabin_class: str
    seat_type: str
    purpose: str
    notes: str
    participants: list[str]

    @staticmethod
    def resolve_origin_iata(obj: FlightRecord) -> str | None:
        return (
            (obj.origin_airport.iata_code or obj.origin_airport.ident)
            if obj.origin_airport
            else None
        )

    @staticmethod
    def resolve_destination_iata(obj: FlightRecord) -> str | None:
        airport = obj.destination_airport
        return (airport.iata_code or airport.ident) if airport else None

    @staticmethod
    def resolve_airline_name(obj: FlightRecord) -> str | None:
        return obj.airline.name if obj.airline else None


class DatasetOut(Schema):
    name: str
    title: str
    version: str
    source_date: dt.date | None
    source_url: str
    homepage_url: str
    license: str
    license_url: str
    attribution: str
    row_count: int
    loaded_at: dt.datetime


@router.get("/flights/records", response=list[FlightRecordOut], operation_id="listFlightRecords")
def list_flight_records(
    request, status: FlightRecord.Status | None = None, import_batch: int | None = None
):
    if not policy.can_access_raw_history(request.user, request.user.pk):
        raise HttpError(403, "not allowed")
    records = FlightRecord.objects.select_related(
        "origin_airport", "destination_airport", "airline"
    )
    if status:
        records = records.filter(status=status)
    if import_batch is not None:
        records = records.filter(import_batch_id=import_batch)
    return records[:5000]


@router.get("/reference/datasets", response=list[DatasetOut], operation_id="listDatasets")
def list_datasets(request):
    """Loaded reference datasets with their licenses: the attribution page."""
    if not policy.is_family(request.user):
        raise HttpError(403, "not allowed")
    return DatasetVersion.objects.order_by("name")


class AirportOut(Schema):
    id: int
    iata_code: str
    icao_code: str
    ident: str
    name: str
    municipality: str
    iso_country: str
    type: str
    lon: float
    lat: float


class AirportSearchIn(Schema):
    q: str = Field(min_length=2, max_length=64, description="code, name or city")
    limit: int = Field(20, ge=1, le=50)


@router.get("/reference/airports", response=list[AirportOut], operation_id="searchAirports")
def search_airports(request, params: Query[AirportSearchIn]):
    """Airports by code (IATA, ICAO, ident: exact) or name/city (contains), for flight legs and
    stops. Exact code matches first, then airports with scheduled service, then by name."""
    if not policy.is_family(request.user):
        raise HttpError(403, "not allowed")
    term = params.q.strip()
    code = term.upper()
    exact = Q(iata_code=code) | Q(icao_code=code) | Q(ident=code)
    rows = (
        Airport.objects.filter(exact | Q(name__icontains=term) | Q(municipality__icontains=term))
        .exclude(type="closed", iata_code="")
        .annotate(
            exact_rank=Case(
                When(exact, then=Value(0)), default=Value(1), output_field=IntegerField()
            )
        )
        .order_by("exact_rank", "-scheduled_service", "name")[: params.limit]
    )
    return [
        {
            **{
                f: getattr(a, f)
                for f in (
                    "id",
                    "iata_code",
                    "icao_code",
                    "ident",
                    "name",
                    "municipality",
                    "iso_country",
                    "type",
                )
            },
            "lon": a.point.x,
            "lat": a.point.y,
        }
        for a in rows
    ]
