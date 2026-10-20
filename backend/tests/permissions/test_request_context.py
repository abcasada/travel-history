"""The request middleware sets the RLS context from the session (and clears it otherwise)."""

import pytest

from tests.helpers import as_owner
from travel.accounts.models import User
from travel.core.rls import get_context, rls_context, set_context
from travel.trips.models import Trip

pytestmark = [pytest.mark.django_db, pytest.mark.urls("tests.permissions.urls")]


def login(client, user):
    with as_owner():
        client.force_login(user)


def test_anonymous_request_has_no_context_and_sees_nothing(client, family):
    data = client.get("/t/probe").json()
    assert data == {"user": None, "rls_user": None, "ctx": "", "trips": []}


def test_logged_in_request_sees_exactly_what_rls_allows(client, family):
    login(client, family.bob)
    data = client.get("/t/probe").json()
    assert data["user"] == data["rls_user"] == family.bob.pk
    expected = {t.pk for k, t in family.trips.items() if k != "private"}
    assert set(data["trips"]) == expected


def test_deactivated_user_session_is_treated_as_anonymous(client, family):
    login(client, family.ivan)
    data = client.get("/t/probe").json()
    assert data["user"] is None
    assert data["rls_user"] is None
    assert data["trips"] == []


@pytest.mark.django_db(transaction=True)
def test_context_requires_a_transaction():
    """Outside a transaction, set_config(..., true) would vanish immediately; refuse instead."""
    with pytest.raises(RuntimeError):
        set_context(1)


def test_nested_rls_context_restores_previous_user(family):
    set_context(family.alice.pk)
    with rls_context(family.bob.pk):
        assert get_context() == (family.bob.pk, "")
        assert not Trip.objects.filter(pk=family.trips["private"].pk).exists()
    assert get_context() == (family.alice.pk, "")
    assert Trip.objects.filter(pk=family.trips["private"].pk).exists()


def test_unknown_system_context_is_rejected():
    with pytest.raises(ValueError):
        set_context(None, ctx="superuser")


def test_login_context_can_create_and_find_users_but_nothing_else(family):
    with rls_context(None, ctx="auth"):
        user = User.objects.create(
            email="new@example.test", oidc_sub="new-sub", oidc_issuer="https://idp.example.test/"
        )
        assert User.objects.filter(pk=user.pk).exists()
        assert not Trip.objects.exists()
