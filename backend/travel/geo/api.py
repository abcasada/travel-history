"""Gazetteer search for the stop editor ("find a city", D-94). Runs entirely on the server's
own copy of GeoNames: no place name a user types leaves the server (D-20, rule 13)."""

from ninja import Field, Query, Router, Schema
from ninja.errors import HttpError

from travel.core import policy

from . import gazetteer

router = Router(tags=["reference"])


class GazetteerPlaceOut(Schema):
    id: int  # GeoNames id
    name: str
    admin1: str  # state or province name ("" if unknown)
    admin1_code: str
    country_code: str
    country: str
    population: int
    feature_code: str
    timezone: str
    lon: float
    lat: float


class PlaceSearchIn(Schema):
    q: str = Field(min_length=2, max_length=64, description='city name, optionally ", state"')
    limit: int = Field(20, ge=1, le=50)


@router.get("/reference/places", response=list[GazetteerPlaceOut], operation_id="searchPlaces")
def search_places(request, params: Query[PlaceSearchIn]):
    """Cities and towns whose name starts with `q`, most populous first; "Paris, TX" narrows
    by state or country."""
    if not policy.is_family(request.user):
        raise HttpError(403, "not allowed")
    return [
        {
            "id": p.geonameid,
            "name": p.name,
            "admin1": p.admin1_name,
            "admin1_code": p.admin1_code,
            "country_code": p.country_code,
            "country": p.country_name,
            "population": p.population,
            "feature_code": p.feature_code,
            "timezone": p.timezone,
            "lon": p.point.x,
            "lat": p.point.y,
        }
        for p in gazetteer.search(params.q, params.limit)
    ]
