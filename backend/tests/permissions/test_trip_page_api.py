"""Endpoints added for the complete trip page (work-order item 21b, D-113): editing people
(`PATCH /persons/{id}`), managing one's own purposes (`POST/PATCH /purposes`), airline search
(`GET /reference/airlines`), the airport and airline labels on legs, and the trip status enum
under its own schema name - every endpoint for every actor of the synthetic family
(tests/permissions/conftest.py).

Same conventions as test_trips_api.py: 401 signed out or deactivated, 403 for a role that may
not act, 404 for what the caller can't see. The SQL layer is in test_matrix.py
(`edit_own_person`, `edit_alice_person`, `edit_kid`, `create_purpose`, `edit_alice_purpose`).
"""

import pytest
from django.contrib.gis.geos import Point

from config.api import api
from tests.helpers import as_owner
from tests.permissions.test_trips_api import (
    ACTORS,
    API,
    as_actor,
    assert_no_identity,
    call,
    trip_path,
)
from travel.accounts.models import Person
from travel.geo.models import Airline, Airport
from travel.trips.models import Leg, Purpose, Trip

pytestmark = pytest.mark.django_db

R = (401, 401)  # ivan (deactivated) and anonymous

# name -> (method, path builder, body, expected per actor)
CASES = {
    # The Admin manages the kid; everyone sees the kid (family-visible).
    "rename_kid": (
        "PATCH", lambda f, a: f"{API}/persons/{f.kid.pk}", {"display_name": "Synthetic kid"},
        (200, 403, 403, 403, 403, *R),
    ),
    # Alice's private person: only she sees it (the Admin too can't, so 404).
    "rename_alices_private_person": (
        "PATCH", lambda f, a: f"{API}/persons/{f.alices_private_person.pk}",
        {"visibility": "family"},
        (404, 200, 404, 404, 404, *R),
    ),
    # Another account's person: its own account, or the Admin.
    "rename_alice": (
        "PATCH", lambda f, a: f"{API}/persons/{f.alice.person.pk}", {"display_name": "A."},
        (200, 200, 403, 403, 403, *R),
    ),
    # One's own person; a Viewer is read-only even here.
    "rename_own_person": (
        "PATCH",
        lambda f, a: f"{API}/persons/{(getattr(f, a).person if a != 'anon' else f.bob.person).pk}",
        {"display_name": "Synthetic me"},
        (200, 200, 200, 200, 403, *R),
    ),
    "create_purpose": (
        "POST", lambda f, a: f"{API}/purposes", {"name": "Synthetic conference"},
        (201, 201, 201, 201, 403, *R),
    ),
    "update_alices_purpose": (
        "PATCH", lambda f, a: f"{API}/purposes/{f.alice_purpose.pk}", {"archived": True},
        (404, 200, 404, 404, 404, *R),
    ),
    "search_airlines": (
        "GET", lambda f, a: f"{API}/reference/airlines?q=SY", None,
        (200, 200, 200, 200, 200, *R),
    ),
    "list_trips_by_status": (
        "GET", lambda f, a: f"{API}/trips?status=confirmed", None,
        (200, 200, 200, 200, 200, *R),
    ),
}  # fmt: skip

PARAMS = [
    pytest.param(name, actor, status, id=f"{name}-{actor}")
    for name, (_, _, _, row) in CASES.items()
    for actor, status in zip(ACTORS, row, strict=True)
]


@pytest.mark.parametrize(("name", "actor", "expected"), PARAMS)
def test_api_matrix(client, scenario, name, actor, expected):
    f = scenario
    method, path, body, _ = CASES[name]
    response = call(as_actor(client, f, actor), method, path(f, actor), body)
    assert response.status_code == expected, response.content[:300]
    if expected < 300 and response.content:
        assert_no_identity(f, response.content)


# --- People ----------------------------------------------------------------------------------


def test_rename_and_hide_a_person_you_manage(client, scenario):
    f = scenario
    as_actor(client, f, "alice")
    path = f"{API}/persons/{f.alices_private_person.pk}"
    response = call(client, "PATCH", path, {"display_name": "  Synthetic colleague "})
    assert response.status_code == 200
    body = response.json()
    assert (body["display_name"], body["visibility"]) == ("Synthetic colleague", "private")
    assert body["can_edit"] and body["manages"]
    response = call(client, "PATCH", path, {"visibility": "family"})
    assert response.json()["visibility"] == "family"
    with as_owner():
        person = Person.objects.get(pk=f.alices_private_person.pk)
        assert (person.display_name, person.visibility) == ("Synthetic colleague", "family")
    # Family-visible now: Carol sees the new name.
    carol = call(as_actor(client, f, "carol"), "GET", f"{API}/persons").json()
    assert "Synthetic colleague" in {p["display_name"] for p in carol}


@pytest.mark.parametrize(
    "body",
    [
        {"display_name": ""},
        {"display_name": "   "},
        {"display_name": "x" * 151},
        {"display_name": None},
        {"visibility": "public"},
        {"visibility": None},
    ],
)
def test_person_patch_validation(client, scenario, body):
    f = scenario
    path = f"{API}/persons/{f.alices_private_person.pk}"
    assert call(as_actor(client, f, "alice"), "PATCH", path, body).status_code == 422


def test_missing_person_is_404(client, scenario):
    response = call(as_actor(client, scenario, "admin"), "PATCH", f"{API}/persons/999999", {})
    assert response.status_code == 404


def test_people_list_says_who_may_edit(client, scenario):
    f = scenario
    admin = {
        p["display_name"]: p
        for p in call(as_actor(client, f, "admin"), "GET", f"{API}/persons").json()
    }
    # The Admin may rename anyone they see, but manages only the kid and themself.
    assert admin["Alice"]["can_edit"] and not admin["Alice"]["manages"]
    assert admin["Kid"]["can_edit"] and admin["Kid"]["manages"]
    victor = {
        p["display_name"]: p
        for p in call(as_actor(client, f, "victor"), "GET", f"{API}/persons").json()
    }
    assert victor["Victor"]["manages"] and not victor["Victor"]["can_edit"]
    assert not any(p["can_edit"] for p in victor.values())


# --- Purposes --------------------------------------------------------------------------------


def test_create_purpose_goes_last_and_defaults_to_participants(client, scenario):
    f = scenario
    as_actor(client, f, "alice")
    response = call(client, "POST", f"{API}/purposes", {"name": " Synthetic retreat "})
    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["default_visibility"], body["archived"]) == (
        "Synthetic retreat",
        "participants",
        False,
    )
    rows = call(client, "GET", f"{API}/purposes").json()
    assert rows[-1]["id"] == body["id"] and body["sort"] > rows[0]["sort"]
    with as_owner():
        assert Purpose.objects.get(pk=body["id"]).owner_id == f.alice.pk


def test_purpose_names_are_unique_per_user(client, scenario):
    f = scenario
    as_actor(client, f, "alice")
    assert call(client, "POST", f"{API}/purposes", {"name": "VACATION"}).status_code == 409
    # Bob has his own list: the same name is fine for him.
    as_actor(client, f, "bob")
    assert call(client, "POST", f"{API}/purposes", {"name": "Vacation"}).status_code == 201


def test_update_purpose(client, scenario):
    f = scenario
    as_actor(client, f, "alice")
    path = f"{API}/purposes/{f.alice_purpose.pk}"
    response = call(
        client,
        "PATCH",
        path,
        {"name": "Holiday", "default_visibility": "family", "sort": 9, "archived": True},
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": f.alice_purpose.pk,
        "name": "Holiday",
        "default_visibility": "family",
        "sort": 9,
        "archived": True,
    }
    # The trip that had it keeps it.
    with as_owner():
        trip = Trip.objects.get(pk=f.trips["family"].pk)
        trip.purpose = f.alice_purpose
        trip.save(update_fields=["purpose"])
    detail = call(client, "GET", trip_path(f, "family")).json()
    assert detail["purpose"]["name"] == "Holiday"


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "x" * 65},
        {"name": None},
        {"default_visibility": "public"},
        {"sort": -1},
        {"archived": None},
    ],
)
def test_purpose_validation(client, scenario, body):
    f = scenario
    as_actor(client, f, "alice")
    path = f"{API}/purposes/{f.alice_purpose.pk}"
    assert call(client, "PATCH", path, body).status_code == 422
    if "name" in body and body["name"] is not None:
        assert call(client, "POST", f"{API}/purposes", body).status_code == 422


def test_public_is_never_a_purpose_default(client, scenario):
    response = call(
        as_actor(client, scenario, "alice"),
        "POST",
        f"{API}/purposes",
        {"name": "Synthetic", "default_visibility": "public"},
    )
    assert response.status_code == 422


# --- Airlines and airports on legs ------------------------------------------------------------


@pytest.fixture
def airlines():
    with as_owner():
        return {
            "syn": Airline.objects.create(name="Synthetic Air", iata="SY", icao="SYN", active=True),
            "old": Airline.objects.create(name="Old Synthetic Airways", iata="SO", icao="OSY"),
            "alias": Airline.objects.create(
                name="Fictional Lines", alias="Synthetic Express", active=True
            ),
            "other": Airline.objects.create(name="Unrelated Air", iata="UA", active=True),
        }


def test_airline_search_by_code_then_active_then_name(client, scenario, airlines):
    as_actor(client, scenario, "victor")
    rows = call(client, "GET", f"{API}/reference/airlines?q=synthetic").json()
    assert [r["name"] for r in rows] == [
        "Fictional Lines",
        "Synthetic Air",
        "Old Synthetic Airways",
    ]
    assert rows[1] == {
        "id": airlines["syn"].pk,
        "name": "Synthetic Air",
        "iata": "SY",
        "icao": "SYN",
        "country": "",
        "active": True,
    }
    by_code = call(client, "GET", f"{API}/reference/airlines?q=osy").json()
    assert [r["name"] for r in by_code] == ["Old Synthetic Airways"]
    assert call(client, "GET", f"{API}/reference/airlines?q=s").status_code == 422
    assert call(client, "GET", f"{API}/reference/airlines?q=sy&limit=51").status_code == 422


def test_legs_show_airline_and_airport_codes(client, scenario, airlines):
    f = scenario
    with as_owner():
        origin = Airport.objects.create(
            ident="KSYN", iata_code="SYN", name="Synthetic Intl", point=Point(-97, 37)
        )
        destination = Airport.objects.create(
            ident="XS01", name="Synthetic Strip", point=Point(-98, 38)
        )
        Leg.objects.filter(pk=f.core_leg.pk).update(
            mode="flight",
            airline=airlines["syn"],
            origin_airport=origin,
            destination_airport=destination,
        )
    detail = call(as_actor(client, f, "carol"), "GET", trip_path(f, "family")).json()
    leg = next(g for g in detail["legs"] if g["id"] == f.core_leg.pk)
    assert leg["airline"] == {"id": airlines["syn"].pk, "name": "Synthetic Air", "code": "SY"}
    assert leg["origin_airport"] == {"id": origin.pk, "name": "Synthetic Intl", "code": "SYN"}
    assert leg["destination_airport"]["code"] == "XS01"
    other = next(g for g in detail["legs"] if g["id"] == f.bob_leg.pk)
    assert other["airline"] is None and other["origin_airport"] is None


def test_a_leg_takes_an_airline_seat_and_cabin(client, scenario, airlines):
    f = scenario
    as_actor(client, f, "alice")
    response = call(
        client,
        "PATCH",
        f"{API}/legs/{f.core_leg.pk}",
        {
            "mode": "flight",
            "airline_id": airlines["old"].pk,
            "seat": "12A",
            "cabin_class": "economy",
        },
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["airline"]["code"], body["seat"], body["cabin_class"]) == ("SO", "12A", "economy")


# --- Trip status: its own enum in the schema ---------------------------------------------------


def test_trip_status_has_its_own_schema_name():
    schema = api.get_openapi_schema()
    enums = schema["components"]["schemas"]
    assert enums["TripStatus"]["enum"] == ["candidate", "confirmed"]
    trip_out = enums["TripOut"]["properties"]["status"]
    assert trip_out["$ref"].endswith("/TripStatus")
    param = next(
        p for p in schema["paths"][f"{API}/trips"]["get"]["parameters"] if p["name"] == "status"
    )
    assert "TripStatus" in str(param["schema"])


def test_list_filters_by_status(client, scenario):
    f = scenario
    with as_owner():
        Trip.objects.filter(pk=f.trips["family"].pk).update(status="candidate")
    as_actor(client, f, "alice")
    confirmed = call(client, "GET", f"{API}/trips?status=confirmed").json()
    candidates = call(client, "GET", f"{API}/trips?status=candidate").json()
    assert f.trips["family"].pk not in {t["id"] for t in confirmed["items"]}
    assert [t["id"] for t in candidates["items"]] == [f.trips["family"].pk]
    assert candidates["items"][0]["status"] == "candidate"
    assert call(client, "GET", f"{API}/trips?status=resolved").status_code == 422
