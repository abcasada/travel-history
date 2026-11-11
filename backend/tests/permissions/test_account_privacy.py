"""Account privacy (D-72, D-76): an account's full row - email, OIDC issuer and subject, role -
is readable only by the account itself and the Admin; the family reads display names through
the `accounts_userdirectory` view. Checked at the SQL level as `travel_app`, through real
requests (middleware + API), and against the policy layer."""

import pytest
from django.db import ProgrammingError, connection, transaction

from tests.factories import PersonFactory
from tests.helpers import as_owner
from travel.accounts.models import Person, User, UserDirectory
from travel.core import policy
from travel.core.db_privileges import APP_READABLE_VIEWS
from travel.core.rls import rls_context, set_context

pytestmark = pytest.mark.django_db

DIRECTORY_COLUMNS = ["id", "display_name", "person_id", "is_active"]
POSTGIS_VIEWS = {"geometry_columns", "geography_columns"}


def everyone(f):
    return [f.admin, f.alice, f.bob, f.carol, f.victor, f.ivan]


def pks(users):
    return sorted(u.pk for u in users)


# --- SQL level, as travel_app ----------------------------------------------------------------


@pytest.mark.parametrize("actor", ["alice", "bob", "carol", "victor"])
def test_family_reads_only_their_own_account_row(family, actor):
    me = getattr(family, actor)
    set_context(me.pk)
    assert list(User.objects.values_list("pk", "email", "oidc_sub")) == [
        (me.pk, me.email, me.oidc_sub)
    ]


def test_admin_reads_every_account_row(family):
    set_context(family.admin.pk)
    assert sorted(User.objects.values_list("pk", flat=True)) == pks(everyone(family))


@pytest.mark.parametrize("actor", ["ivan", None])
def test_deactivated_or_anonymous_reads_no_account_and_no_directory(family, actor):
    set_context(getattr(family, actor).pk if actor else None)
    assert not User.objects.exists()
    assert not UserDirectory.objects.exists()


@pytest.mark.parametrize("actor", ["admin", "alice", "carol", "victor"])
def test_family_directory_lists_every_account_with_names_only(family, actor):
    set_context(getattr(family, actor).pk)
    rows = {r.pk: r for r in UserDirectory.objects.all()}
    assert sorted(rows) == pks(everyone(family))
    assert rows[family.bob.pk].display_name == "Bob"
    assert rows[family.bob.pk].person_id == family.bob.person_id
    assert rows[family.ivan.pk].is_active is False


def test_directory_has_no_identity_columns(family):
    set_context(family.bob.pk)
    for column in ("email", "oidc_sub", "oidc_issuer", "role", "last_login"):
        with pytest.raises(ProgrammingError), transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"SELECT {column} FROM accounts_userdirectory")  # noqa: S608


def test_member_cannot_probe_other_emails_by_filtering(family):
    """No oracle: a condition on a hidden row never matches."""
    set_context(family.bob.pk)
    assert not User.objects.filter(email=family.alice.email).exists()
    assert not User.objects.filter(oidc_sub=family.alice.oidc_sub).exists()


def test_member_cannot_change_another_account(family):
    set_context(family.bob.pk)
    assert User.objects.filter(pk=family.alice.pk).update(display_name="x") == 0


def test_login_context_still_finds_any_account_by_identity(family):
    with rls_context(None, ctx="auth"):
        found = User.objects.get(
            oidc_issuer=family.alice.oidc_issuer, oidc_sub=family.alice.oidc_sub
        )
    assert found.pk == family.alice.pk


def test_managing_user_follows_the_linked_account_not_the_creator(family):
    """The policy layer finds a person's account through the directory: a person Alice created
    but who is now Carol's own person is managed by Carol. Both layers agree."""
    with as_owner():
        person = PersonFactory(created_by=family.alice, display_name="Linked later")
        User.objects.filter(pk=family.carol.pk).update(person=person)
    for actor, expected in ((family.alice, False), (family.carol, True), (family.bob, False)):
        set_context(actor.pk)
        with as_owner():
            actor.refresh_from_db()
        assert policy.manages_person(actor, person) is expected
        with transaction.atomic():
            updated = Person.objects.filter(pk=person.pk).update(notes="n")
            transaction.set_rollback(True)
        assert (updated == 1) is expected


# --- Schema and grants -------------------------------------------------------------------------


@pytest.mark.as_owner
def test_directory_view_columns_and_security_barrier():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'accounts_userdirectory' "
            "ORDER BY ordinal_position"
        )
        assert [row[0] for row in cursor.fetchall()] == DIRECTORY_COLUMNS
        cursor.execute("SELECT reloptions FROM pg_class WHERE relname = 'accounts_userdirectory'")
        assert "security_barrier=true" in cursor.fetchone()[0]


@pytest.mark.as_owner
def test_runtime_roles_read_only_the_allowlisted_views():
    """Views bypass row-level security (they run as their owner), so each readable one is a
    deliberate, reviewed exception."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT viewname, has_table_privilege('travel_app', format('%I', viewname), 'SELECT'),"
            " has_table_privilege('travel_public', format('%I', viewname), 'SELECT') "
            "FROM pg_views WHERE schemaname = 'public'"
        )
        rows = {name: (app, public) for name, app, public in cursor.fetchall()}
    app_readable = {name for name, (app, _) in rows.items() if app} - POSTGIS_VIEWS
    assert app_readable == APP_READABLE_VIEWS
    assert not any(public for name, (_, public) in rows.items() if name not in POSTGIS_VIEWS)
    with connection.cursor() as cursor:
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            cursor.execute(
                "SELECT has_table_privilege('travel_app', 'accounts_userdirectory', %s)",
                [privilege],
            )
            assert cursor.fetchone()[0] is False, privilege


# --- Through real requests (middleware, session, API) ----------------------------------------


def login(client, user):
    with as_owner():
        client.force_login(user)


@pytest.mark.parametrize("actor", ["admin", "bob", "victor"])
def test_me_returns_the_callers_own_identity(client, family, actor):
    me = getattr(family, actor)
    login(client, me)
    data = client.get("/api/v1/me").json()
    assert (data["id"], data["email"], data["display_name"]) == (me.pk, me.email, me.display_name)


@pytest.mark.urls("tests.permissions.urls")
def test_member_request_sees_own_account_and_family_names(client, family):
    login(client, family.bob)
    data = client.get("/t/accounts").json()
    assert data["accounts"] == [
        {"pk": family.bob.pk, "email": family.bob.email, "oidc_sub": family.bob.oidc_sub}
    ]
    assert [row["pk"] for row in data["directory"]] == pks(everyone(family))
    assert all(set(row) == {"pk", "display_name", "is_active"} for row in data["directory"])


@pytest.mark.urls("tests.permissions.urls")
def test_admin_request_sees_every_account(client, family):
    login(client, family.admin)
    data = client.get("/t/accounts").json()
    assert [row["pk"] for row in data["accounts"]] == pks(everyone(family))
    emails = {row["pk"]: row["email"] for row in data["accounts"]}
    assert emails[family.alice.pk] == family.alice.email


@pytest.mark.urls("tests.permissions.urls")
@pytest.mark.parametrize("actor", ["ivan", None])
def test_anonymous_or_deactivated_request_sees_no_accounts(client, family, actor):
    if actor:
        login(client, getattr(family, actor))
    data = client.get("/t/accounts").json()
    assert data == {"accounts": [], "directory": []}
