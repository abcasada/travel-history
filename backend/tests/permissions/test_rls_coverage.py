"""Every user-owned table is protected by row-level security, for every command, and policies
target only the runtime role. A new table fails these tests until it gets policies (or is added
to the exemption list with a reason)."""

import pytest
from django.db import connection

pytestmark = [pytest.mark.django_db, pytest.mark.as_owner]

# Tables without user data, or readable by design.
EXEMPT_PREFIXES = (
    "django_",  # migrations, content types, sessions (keyed by unguessable session keys)
    "auth_",  # unused contrib.auth permission tables
    "procrastinate_",  # job queue
    "geo_",  # public reference datasets, read-only to the app
    "public_",  # public snapshots: allowlisted, public by design
)
EXEMPT_TABLES = {"spatial_ref_sys", "core_ratelimitbucket"}

# Commands deliberately left without a policy (denied for travel_app).
DELIBERATELY_DENIED = {
    ("accounts_user", "DELETE"),  # accounts are deactivated, never deleted by the app
    ("accounts_auditlog", "UPDATE"),
    ("accounts_auditlog", "DELETE"),
    ("trips_route", "UPDATE"),  # frozen routes
    ("trips_routesimplified", "UPDATE"),
    ("trips_triptag", "UPDATE"),
    ("history_rawfile", "UPDATE"),  # immutable originals
    ("history_locationpoint", "UPDATE"),  # append-only
}

COMMANDS = {"SELECT", "INSERT", "UPDATE", "DELETE"}


def _tables():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname, c.relrowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
        )
        return dict(cursor.fetchall())


def _protected():
    return {
        name: rls
        for name, rls in _tables().items()
        if name not in EXEMPT_TABLES and not name.startswith(EXEMPT_PREFIXES)
    }


def test_rls_is_enabled_on_every_user_table():
    missing = sorted(name for name, rls in _protected().items() if not rls)
    assert missing == []


def test_every_command_has_a_policy_unless_deliberately_denied():
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename, cmd FROM pg_policies WHERE schemaname = 'public'")
        covered: dict[str, set[str]] = {}
        for table, cmd in cursor.fetchall():
            covered.setdefault(table, set()).update(COMMANDS if cmd == "ALL" else {cmd})
    gaps = sorted(
        (table, cmd)
        for table in _protected()
        for cmd in COMMANDS - covered.get(table, set())
        if (table, cmd) not in DELIBERATELY_DENIED
    )
    assert gaps == []


def test_deliberate_denials_really_have_no_policy():
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename, cmd FROM pg_policies WHERE schemaname = 'public'")
        rows = cursor.fetchall()
    for table, cmd in DELIBERATELY_DENIED:
        assert (table, cmd) not in rows and (table, "ALL") not in rows


def test_policies_apply_only_to_the_runtime_role():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT unnest(roles)::text FROM pg_policies WHERE schemaname = 'public'"
        )
        roles = {row[0] for row in cursor.fetchall()}
    assert roles == {"travel_app"}


def test_tables_are_not_owned_by_runtime_roles_and_not_forced():
    """ENABLE (not FORCE) is deliberate: the owner role runs migrations and backups and must
    see everything; the runtime role never owns tables (PLAN.md D-23)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relforcerowsecurity"
        )
        assert cursor.fetchall() == []
