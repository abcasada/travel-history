"""Flights API (work-order item 10) for every actor of the synthetic family: imported flight
records are their owner's raw history (only alice sees hers; not even the Admin), and the
attribution list is open to every signed-in family member."""

import pytest

from tests.helpers import as_owner
from travel.geo.models import DatasetVersion

pytestmark = pytest.mark.django_db

ACTORS = ("admin", "alice", "bob", "carol", "victor", "ivan", "anon")
API = "/api/v1"


def client_for(client, f, actor):
    if actor != "anon":
        with as_owner():
            client.force_login(getattr(f, actor))
    return client


@pytest.mark.parametrize("actor", ACTORS)
def test_flight_records(client, scenario, actor):
    response = client_for(client, scenario, actor).get(f"{API}/flights/records")
    if actor in ("ivan", "anon"):
        assert response.status_code == 401
        return
    assert response.status_code == 200
    ids = [record["id"] for record in response.json()]
    assert ids == ([scenario.alice_flight.pk] if actor == "alice" else [])


def test_flight_record_filters(client, scenario):
    client = client_for(client, scenario, "alice")
    unmatched = client.get(f"{API}/flights/records?status=unmatched").json()
    assert [r["id"] for r in unmatched] == [scenario.alice_flight.pk]
    assert client.get(f"{API}/flights/records?status=resolved").json() == []
    assert client.get(f"{API}/flights/records?import_batch=999999").json() == []


@pytest.mark.parametrize("actor", ACTORS)
def test_datasets(client, scenario, actor):
    with as_owner():
        DatasetVersion.objects.create(
            name="openflights_airlines",
            source_url="https://example.invalid/airlines.dat",
            license="ODbL 1.0",
            attribution="Airline and aircraft data: OpenFlights.org (ODbL)",
        )
    response = client_for(client, scenario, actor).get(f"{API}/reference/datasets")
    if actor in ("ivan", "anon"):
        assert response.status_code == 401
        return
    assert response.status_code == 200
    assert response.json()[0]["attribution"].startswith("Airline and aircraft data")
