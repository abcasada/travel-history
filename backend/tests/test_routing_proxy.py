"""Routing proxy (docs/design/routing.md §13.1; work-order item 25): providers, OSRM
normalization, the provider chain, throttles and the per-user cache.

No test talks to a real provider: `requests` is replaced by a recorder that answers with
synthetic payloads and remembers exactly what would have left the server (rule 13).
"""

import datetime as dt

import pytest
import requests

from tests.factories import UserFactory
from tests.helpers import as_owner
from tests.routing_fakes import (
    DENVER,
    LINE,
    OMAHA,
    SALINA,
    STATUS,
    WICHITA,
    FakeResponse,
    ors_answer,
    osrm_answer,
)
from travel.core.ratelimit import RateLimited
from travel.core.rls import set_context
from travel.routing import providers, services
from travel.routing.models import RouteRequestCache

LIMITER = pytest.mark.django_db(databases=["default", "ratelimit"])

# --- Providers and normalization ------------------------------------------------------------


def test_valhalla_answer_is_reduced_to_the_shared_osrm_shape(fake):
    rec = fake({"/route": FakeResponse(200, osrm_answer()), "/status": STATUS})
    answer, prov = providers.valhalla([WICHITA, SALINA])
    route = answer["routes"][0]
    assert set(route) == {"geometry", "distance", "duration", "legs"}  # no weights or steps
    assert route["geometry"]["type"] == "LineString"
    assert route["legs"] == [{"distance": 144672.4, "duration": 4653.2, "summary": ""}]
    assert answer["waypoints"][0] == {"location": LINE[0], "name": "Synthetic Avenue"}
    assert (prov.engine, prov.engine_version) == ("valhalla", "3.9.1")
    assert prov.data_date == dt.date(2025, 11, 18)
    body = rec.calls[0]["json"]
    assert body["format"] == "osrm" and body["shape_format"] == "geojson"
    assert body["locations"] == [
        {"lon": -97.3301, "lat": 37.6872},
        {"lon": -97.6114, "lat": 38.8403},
    ]


def test_valhalla_data_date_setting_wins(fake, settings):
    settings.VALHALLA_DATA_DATE = "2026-11-15"
    fake({"/route": FakeResponse(200, osrm_answer()), "/status": STATUS})
    assert providers.valhalla([WICHITA, SALINA])[1].data_date == dt.date(2026, 11, 15)


def test_valhalla_no_route_is_an_answer_and_a_500_is_unavailable(fake):
    fake({"/route": FakeResponse(400, {"code": "NoRoute", "error_code": 442})})
    with pytest.raises(providers.NoRoute):
        providers.valhalla([WICHITA, SALINA])
    fake({"/route": FakeResponse(503, None)})
    with pytest.raises(providers.Unavailable):
        providers.valhalla([WICHITA, SALINA])
    fake({"/route": requests.ConnectionError("down")})
    with pytest.raises(providers.Unavailable):
        providers.valhalla([WICHITA, SALINA])


def test_ors_is_skipped_without_a_key(fake):
    rec = fake({})
    assert not providers.ors_configured()
    with pytest.raises(providers.Unavailable):
        providers.ors([DENVER, OMAHA])
    assert rec.calls == []


def test_ors_polyline_becomes_a_geojson_line_and_sends_only_waypoints(fake, settings):
    settings.ORS_API_KEY = "synthetic-key"
    rec = fake({"/v2/directions/driving-car": FakeResponse(200, ors_answer())})
    answer, prov = providers.ors([DENVER, OMAHA])
    route = answer["routes"][0]
    assert route["geometry"]["coordinates"] == LINE
    assert (route["distance"], route["duration"]) == (150000.0, 5000.0)
    assert [w["location"] for w in answer["waypoints"]] == [LINE[0], LINE[2]]
    assert (prov.engine, prov.engine_version, prov.data_date) == (
        "ors",
        "9.0.0",
        dt.date(2026, 11, 1),
    )
    assert "openrouteservice" in prov.as_dict()["attribution"]
    call = rec.calls[0]
    assert call["json"] == {"coordinates": [list(DENVER), list(OMAHA)], "instructions": False}
    assert call["headers"]["Authorization"] == "synthetic-key"


@pytest.mark.parametrize(
    ("status", "payload", "error"),
    [
        (404, {"error": {"code": 2009}}, providers.NoRoute),
        (400, {"error": {"code": 2010}}, providers.NoRoute),
        (429, {"error": "quota"}, providers.Unavailable),
        (403, {"error": "bad key"}, providers.Unavailable),
    ],
)
def test_ors_errors(fake, settings, status, payload, error):
    settings.ORS_API_KEY = "synthetic-key"
    fake({"/v2/directions": FakeResponse(status, payload)})
    with pytest.raises(error):
        providers.ors([DENVER, OMAHA])


def test_fossgis_request_shape(fake):
    rec = fake({"/route/v1/driving/": FakeResponse(200, osrm_answer())})
    answer, prov = providers.fossgis([DENVER, OMAHA])
    assert prov.engine == "osrm-fossgis"
    assert answer["routes"][0]["geometry"]["coordinates"] == LINE
    assert rec.urls() == [
        "https://fossgis.invalid/routed-car/route/v1/driving/-104.9903,39.7392;-95.9345,41.2565"
    ]
    assert rec.calls[0]["params"]["geometries"] == "geojson"


def test_outbound_requests_carry_no_identity(fake, settings):
    """Rule 13 and the ORS terms: only waypoints leave; headers are a generic client name."""
    settings.ORS_API_KEY = "synthetic-key"
    rec = fake(
        {
            "/route/v1/": FakeResponse(200, osrm_answer()),
            "/v2/directions": FakeResponse(200, ors_answer()),
            "/route": FakeResponse(200, osrm_answer()),
            "/status": STATUS,
        }
    )
    providers.valhalla([WICHITA, SALINA])
    providers.ors([DENVER, OMAHA])
    providers.fossgis([DENVER, OMAHA])
    for call in rec.calls:
        headers = call["headers"]
        assert set(headers) <= {"User-Agent", "Accept", "Authorization"}
        assert "@" not in headers["User-Agent"]
        assert "cookies" not in call and "auth" not in call


# --- The chain, cache and throttles -----------------------------------------------------------


@pytest.fixture
def member(db):
    with as_owner():
        user = UserFactory()
    set_context(user.pk)
    return user


@LIMITER
def test_inside_coverage_uses_valhalla(fake, member):
    rec = fake({"valhalla:8002/route": FakeResponse(200, osrm_answer()), "/status": STATUS})
    result = services.propose_route(member, [WICHITA, SALINA])
    assert result["provenance"]["engine"] == "valhalla"
    assert result["provenance"]["attribution"].startswith("Route: Valhalla")
    assert result["cached"] is False
    assert not any("fossgis" in u or "ors" in u for u in rec.urls())


@LIMITER
def test_outside_coverage_without_ors_key_goes_to_fossgis(fake, member):
    rec = fake({"fossgis.invalid": FakeResponse(200, osrm_answer())})
    result = services.propose_route(member, [DENVER, OMAHA])
    assert result["provenance"]["engine"] == "osrm-fossgis"
    assert all("valhalla" not in u for u in rec.urls())


@LIMITER
def test_outside_coverage_with_a_key_uses_ors(fake, member, settings):
    settings.ORS_API_KEY = "synthetic-key"
    rec = fake({"ors.invalid": FakeResponse(200, ors_answer())})
    assert services.propose_route(member, [DENVER, OMAHA])["provenance"]["engine"] == "ors"
    assert len(rec.calls) == 1


@LIMITER
def test_valhalla_down_falls_back_to_ors(fake, member, settings):
    settings.ORS_API_KEY = "synthetic-key"
    fake(
        {
            "valhalla:8002/route": requests.ConnectionError("down"),
            "ors.invalid": FakeResponse(200, ors_answer()),
        }
    )
    assert services.propose_route(member, [WICHITA, SALINA])["provenance"]["engine"] == "ors"


@LIMITER
def test_no_route_ends_the_chain(fake, member, settings):
    settings.ORS_API_KEY = "synthetic-key"
    rec = fake({"valhalla:8002/route": FakeResponse(400, {"code": "NoRoute"})})
    with pytest.raises(services.RoutingFailed) as failed:
        services.propose_route(member, [WICHITA, SALINA])
    assert failed.value.status == 422
    assert len(rec.calls) == 1  # nobody else got the waypoints


@LIMITER
def test_fossgis_is_limited_to_one_request_per_second_for_everyone(fake, member):
    fake({"fossgis.invalid": FakeResponse(200, osrm_answer())})
    services.propose_route(member, [DENVER, OMAHA])
    with as_owner():
        other = UserFactory()
    set_context(other.pk)
    with pytest.raises(services.RoutingFailed) as failed:
        services.propose_route(other, [OMAHA, DENVER])
    assert failed.value.status == 503
    assert failed.value.retry_after == 1


@LIMITER
def test_fossgis_can_be_switched_off(fake, member, settings):
    settings.ROUTING_FOSSGIS_ENABLED = False
    rec = fake({})
    with pytest.raises(services.RoutingFailed) as failed:
        services.propose_route(member, [DENVER, OMAHA])
    assert failed.value.status == 503
    assert rec.calls == []


@LIMITER
def test_identical_requests_are_served_from_the_users_cache(fake, member):
    rec = fake({"valhalla:8002/route": FakeResponse(200, osrm_answer()), "/status": STATUS})
    first = services.propose_route(member, [WICHITA, SALINA])
    second = services.propose_route(member, [WICHITA, SALINA])
    assert second["cached"] is True
    assert second["routes"] == first["routes"]
    assert [u for u in rec.urls() if u.endswith("/route")] == ["http://valhalla:8002/route"]
    assert services.cached_proposal(member, [WICHITA, SALINA]) is not None
    assert services.cached_proposal(member, [SALINA, WICHITA]) is None


@LIMITER
def test_expired_proposals_are_purged(fake, member):
    fake({"valhalla:8002/route": FakeResponse(200, osrm_answer()), "/status": STATUS})
    services.propose_route(member, [WICHITA, SALINA])
    RouteRequestCache.objects.filter(owner=member).update(
        expires_at=dt.datetime(2000, 1, 1, tzinfo=dt.UTC)
    )
    assert services.cached_proposal(member, [WICHITA, SALINA]) is None
    assert services.purge_expired_cache(member.pk) == 1


@LIMITER
def test_a_user_routing_too_fast_is_throttled(fake, member):
    fake({"valhalla:8002/route": FakeResponse(200, osrm_answer()), "/status": STATUS})
    for _ in range(5):
        services.propose_route(member, [WICHITA, SALINA])
    with pytest.raises(RateLimited):
        for _ in range(10):
            services.propose_route(member, [WICHITA, SALINA])
