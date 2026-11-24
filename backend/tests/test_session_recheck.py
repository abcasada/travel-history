"""The hourly provider check and the grace for saves (F-3; D-108, D-122), per method: a session
the provider vouched for recently, one whose check fell due within the grace, one past it, and
one never stamped. Sign-ins through the provider itself are in test_authentik.py."""

import json
import time

import pytest

from tests.factories import TripFactory, UserFactory
from tests.helpers import as_owner
from travel.accounts import sessions
from travel.accounts.models import UserPreference
from travel.trips.models import Trip

pytestmark = pytest.mark.django_db

HOUR = 3600  # compose.prod.yaml's OIDC_SESSION_RECHECK_SECONDS
READS = ["GET", "HEAD", "OPTIONS"]
WRITES = ["POST", "PUT", "PATCH", "DELETE"]
DUE = {"detail": sessions.DUE_DETAIL}
SIGNED_OUT = {"detail": "authentication required"}
SAVED_TITLE = "SYNTHETIC saved"


@pytest.fixture
def member(settings):
    settings.OIDC_SESSION_RECHECK_SECONDS = HOUR
    with as_owner():
        user = UserFactory()
        trip = TripFactory(owner=user)
    return user, trip


def signed_in(client, user, age: int | None) -> None:
    """A session the provider vouched for `age` seconds ago (None: never stamped)."""
    with as_owner():
        client.force_login(user)
    if age is not None:
        session = client.session
        session[sessions.CHECKED_AT] = int(time.time()) - age
        session.save()


def send(client, method: str, trip: Trip):
    """One request per method, each a real save for the writes."""
    path, body = {
        "GET": ("/api/v1/me", None),
        "HEAD": ("/api/v1/me", None),
        "OPTIONS": ("/api/v1/me", None),
        "POST": (
            "/api/v1/trips",
            {"title": SAVED_TITLE, "start_date": "2024-01-01", "end_date": "2024-01-02"},
        ),
        "PUT": ("/api/v1/preferences/grace_check", {"value": 1}),
        "PATCH": (f"/api/v1/trips/{trip.pk}", {"title": SAVED_TITLE}),
        "DELETE": (f"/api/v1/trips/{trip.pk}", None),
    }[method]
    data = json.dumps(body) if body is not None else ""
    return client.generic(method, path, data, content_type="application/json")


def landed(method: str, user, trip: Trip) -> bool:
    with as_owner():
        if method == "POST":
            return Trip.objects.filter(owner=user, title=SAVED_TITLE).exists()
        if method == "PUT":
            return UserPreference.objects.filter(user=user, key="grace_check").exists()
        if method == "PATCH":
            return Trip.objects.get(pk=trip.pk).title == SAVED_TITLE
        return not Trip.objects.filter(pk=trip.pk).exists()


def me(client):
    response = client.get("/api/v1/me")
    return response.status_code, response.json()


@pytest.mark.parametrize("method", READS + WRITES)
def test_a_session_checked_within_the_hour_passes(client, member, method):
    user, trip = member
    signed_in(client, user, HOUR - 10)
    assert send(client, method, trip).status_code != 401
    if method in WRITES:
        assert landed(method, user, trip)
    assert me(client)[0] == 200


@pytest.mark.parametrize("age", [HOUR + 10, 2 * HOUR - 10], ids=["just-due", "end-of-grace"])
@pytest.mark.parametrize("method", WRITES)
def test_a_save_within_the_grace_lands(client, member, method, age):
    user, trip = member
    signed_in(client, user, age)
    assert send(client, method, trip).status_code in (200, 201, 204)
    assert landed(method, user, trip)
    # The provider still hasn't vouched: the next read starts the sign-in (the SPA's redirect).
    assert me(client) == (401, DUE)


@pytest.mark.parametrize("method", READS)
def test_a_read_within_the_grace_starts_the_sign_in(client, member, method):
    user, trip = member
    signed_in(client, user, HOUR + 10)
    response = send(client, method, trip)
    assert response.status_code == 401
    if method != "HEAD":  # no body
        assert response.json() == DUE
    page = client.get("/app/trips")
    assert (page.status_code, page["Location"]) == (302, "/auth/login?next=/app/trips")
    # Refused, not ended: a save still on its way (another tab, the next step of a save that
    # refetched in between) lands, and every read keeps saying why.
    assert send(client, "PATCH", trip).status_code == 200
    assert landed("PATCH", user, trip)
    assert me(client) == (401, DUE)


@pytest.mark.parametrize("method", READS + WRITES)
def test_past_the_grace_every_method_is_signed_out(client, member, method):
    user, trip = member
    signed_in(client, user, 2 * HOUR + 10)
    response = send(client, method, trip)
    assert response.status_code == 401
    if method != "HEAD":
        assert response.json() == DUE
    if method in WRITES:
        assert not landed(method, user, trip)
    assert me(client) == (401, SIGNED_OUT)  # the session ended


@pytest.mark.parametrize("method", READS + WRITES)
def test_a_session_never_stamped_has_no_grace(client, member, method):
    user, trip = member
    signed_in(client, user, None)
    assert send(client, method, trip).status_code == 401
    if method in WRITES:
        assert not landed(method, user, trip)
    assert me(client) == (401, SIGNED_OUT)


@pytest.mark.parametrize(("interval", "grace"), [(60, 60), (HOUR, HOUR), (86_400, HOUR)], ids=str)
def test_the_grace_is_the_interval_but_at_most_an_hour(settings, interval, grace):
    settings.OIDC_SESSION_RECHECK_SECONDS = interval
    assert sessions.grace_seconds() == grace


def test_a_day_long_interval_still_ends_writes_an_hour_later(client, member, settings):
    settings.OIDC_SESSION_RECHECK_SECONDS = 86_400  # production's maximum
    user, trip = member
    signed_in(client, user, 86_400 + HOUR - 10)
    assert send(client, "PUT", trip).status_code == 200
    signed_in(client, user, 86_400 + HOUR + 10)
    assert send(client, "PATCH", trip).status_code == 401
    assert not landed("PATCH", user, trip)


@pytest.mark.parametrize("method", ["PROPFIND", "TRACE"])
def test_other_methods_count_as_reads(client, member, method):
    user, _ = member
    signed_in(client, user, HOUR + 10)
    assert client.generic(method, "/api/v1/me").status_code == 401
    assert me(client) == (401, DUE)


def test_sign_out_is_never_held_up(client, member):
    user, _ = member
    signed_in(client, user, HOUR + 10)
    client.get("/api/v1/me")
    assert client.post("/auth/logout").status_code == 302
    assert me(client) == (401, SIGNED_OUT)


def test_development_has_no_check(client, settings):
    assert settings.OIDC_SESSION_RECHECK_SECONDS == 0
    with as_owner():
        user = UserFactory()
        trip = TripFactory(owner=user)
    signed_in(client, user, None)
    for method in READS + WRITES:
        assert send(client, method, trip).status_code != 401
