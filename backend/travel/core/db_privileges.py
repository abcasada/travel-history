"""Table privileges for the runtime roles, applied after every `migrate` (which runs as the
owner role). Row-level security (policies) decides *which rows*; these grants decide *which
statements* a role may run at all. Keep this the single place that grants anything.

- travel_app: DML on everything, except read-only reference data and statements that would
  break append-only/immutable tables.
- travel_public: SELECT on the public snapshot tables only (PLAN.md §6.5).
"""

import logging

from django.db import connection

log = logging.getLogger(__name__)

APP_ROLE = "travel_app"
PUBLIC_ROLE = "travel_public"

# Reference datasets loaded by management commands running as the owner.
READ_ONLY_FOR_APP_PREFIXES = ("geo_",)
READ_ONLY_FOR_APP_TABLES = {"django_migrations"}

# Append-only / immutable tables: no UPDATE for the app role (triggers enforce it as well).
NO_UPDATE_FOR_APP = {
    "history_locationpoint",
    "history_rawfile",
    "trips_route",
}

# The only tables the public renderer may read.
PUBLIC_READABLE_TABLES = {
    "public_publictripsnapshot",
    "public_publicmediafile",
    "public_publicprofilesnapshot",
}


def _tables(cursor) -> list[str]:
    cursor.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename NOT IN ('spatial_ref_sys')"
    )
    return [row[0] for row in cursor.fetchall()]


def _roles_exist(cursor) -> bool:
    cursor.execute(
        "SELECT count(*) FROM pg_roles WHERE rolname IN (%s, %s)", [APP_ROLE, PUBLIC_ROLE]
    )
    return cursor.fetchone()[0] == 2


def apply(using: str = "default") -> None:
    from django.db import connections

    conn = connections[using]
    with conn.cursor() as cursor:
        if not _roles_exist(cursor):
            log.warning("runtime roles missing; skipping grants (expected only outside Docker)")
            return
        cursor.execute("SELECT current_user")
        owner = cursor.fetchone()[0]
        statements: list[str] = [
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public "
            "REVOKE ALL ON TABLES FROM PUBLIC",
            f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}, {PUBLIC_ROLE}",
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}",
            f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {PUBLIC_ROLE}",
            f"GRANT SELECT ON spatial_ref_sys TO {APP_ROLE}, {PUBLIC_ROLE}",
        ]
        for table in _tables(cursor):
            quoted = connection.ops.quote_name(table)
            read_only = table in READ_ONLY_FOR_APP_TABLES or table.startswith(
                READ_ONLY_FOR_APP_PREFIXES
            )
            if read_only:
                statements.append(f"REVOKE ALL ON {quoted} FROM {APP_ROLE}")
                statements.append(f"GRANT SELECT ON {quoted} TO {APP_ROLE}")
            else:
                statements.append(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {quoted} TO {APP_ROLE}")
                if table in NO_UPDATE_FOR_APP:
                    statements.append(f"REVOKE UPDATE ON {quoted} FROM {APP_ROLE}")
            if table in PUBLIC_READABLE_TABLES:
                statements.append(f"GRANT SELECT ON {quoted} TO {PUBLIC_ROLE}")
        # Our SECURITY DEFINER functions in `public` (trigger helpers) run with the owner's
        # rights; nobody needs to call them directly. Triggers still fire without EXECUTE.
        cursor.execute(
            "SELECT p.oid::regprocedure::text FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.prosecdef AND p.proowner = current_user::regrole"
        )
        for (signature,) in cursor.fetchall():
            statements.append(f"REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC")
        # Policy helper functions (schema `app`, PLAN.md §6.1) are callable by the app role only.
        cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'app'")
        if cursor.fetchone():
            statements += [
                "REVOKE ALL ON SCHEMA app FROM PUBLIC",
                f"GRANT USAGE ON SCHEMA app TO {APP_ROLE}",
                "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC",
                f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO {APP_ROLE}",
            ]
        for sql in statements:
            cursor.execute(sql)


def apply_after_migrate(sender, using="default", **kwargs) -> None:  # noqa: ARG001
    apply(using=using)
