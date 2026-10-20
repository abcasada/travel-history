"""Preferences API: per-user, per-device-class settings (e.g. the desktop split-pane layout)."""

import pytest

from tests.factories import UserFactory
from tests.helpers import as_owner
from travel.accounts.models import UserPreference

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice_client(client):
    with as_owner():
        alice = UserFactory()
        client.force_login(alice)
    client.user = alice
    return client


def put(client, key, value, device_class="any"):
    return client.put(
        f"/api/v1/preferences/{key}",
        {"value": value, "device_class": device_class},
        content_type="application/json",
    )


def test_device_class_values_override_any(alice_client):
    assert put(alice_client, "split_layout", {"list": 30, "map": 70}).status_code == 200
    assert put(alice_client, "split_layout", {"list": 45, "map": 55}, "desktop").status_code == 200
    assert put(alice_client, "theme", "dark").status_code == 200
    desktop = alice_client.get("/api/v1/preferences?device_class=desktop").json()
    mobile = alice_client.get("/api/v1/preferences?device_class=mobile").json()
    assert desktop == {"split_layout": {"list": 45, "map": 55}, "theme": "dark"}
    assert mobile == {"split_layout": {"list": 30, "map": 70}, "theme": "dark"}


def test_updates_replace_the_stored_value(alice_client):
    put(alice_client, "theme", "dark")
    put(alice_client, "theme", "light")
    assert alice_client.get("/api/v1/preferences").json() == {"theme": "light"}


@pytest.mark.parametrize("key", ["Bad-Key", "1abc", "a" * 65, "with space"])
def test_invalid_keys_are_rejected(alice_client, key):
    assert put(alice_client, key, 1).status_code in (404, 422)


def test_oversized_values_are_rejected(alice_client):
    assert put(alice_client, "big", "x" * 5000).status_code == 422


def test_users_never_see_each_others_preferences(alice_client):
    with as_owner():
        bob = UserFactory()
        UserPreference.objects.create(user=bob, key="secret", value="bob's")
    assert alice_client.get("/api/v1/preferences").json() == {}
