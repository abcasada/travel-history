"""Moving the real data from the development database into production (work-order item 40b,
docs/production.md "Copying the data from development").

`./dev prod import-from-dev` restores a dump of the dev database into a staging database next to
production's, then runs these functions there through `manage.py dev_copy` (owner role):

- `check_target`: refuses when the two databases' applied migrations differ, and forever once
  any production account has a real identity (an https issuer: production refuses any other
  issuer, and the dev mock provider's is http), because the copy would erase it;
- `prune`: every account but the kept one goes with all its rows, the kept account's synthetic
  rows (batches whose raw file carries the SYNTHETIC fixture marker, the e2e smoke test's
  leftovers) too, and the operational tables (sessions, the job queue, rate-limit counters, the
  routing cache) are emptied. One transaction; a dry run rolls back.

All of it is generic over the foreign keys PostgreSQL knows, not over Django's `on_delete`
(most user foreign keys are DO_NOTHING): a NOT NULL reference to a removed row removes the
referencing row, a nullable one is set to NULL, repeated until nothing changes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import zstandard
from django.db import connection, transaction

# The live database's name in both stacks: pruning never runs there (only in the staging copy).
LIVE_DATABASE = "travel"
SYNTHETIC_MARKER = b"SYNTHETIC"
E2E_PREFIX = "E2E %"
# Emptied in the copy: nothing in them belongs to a person or survives a restart meaningfully.
OPERATIONAL_TABLES = (
    "django_session",
    "procrastinate_events",
    "procrastinate_jobs",
    "procrastinate_periodic_defers",
    "procrastinate_workers",
    "core_ratelimitbucket",
    "routing_routerequestcache",
)
# The e2e smoke test (e2e/smoke.mjs) names what it creates "E2E …".
E2E_ROWS = (
    ("trips_trip", "owner_id", "title"),
    ("trips_place", "owner_id", "name"),
    ("accounts_devicetoken", "user_id", "name"),
)

_FKS_SQL = """
SELECT ch.relname, ca.attname, ca.attnotnull, pr.relname, pa.attname
FROM pg_constraint co
JOIN pg_class ch ON ch.oid = co.conrelid
JOIN pg_namespace n ON n.oid = ch.relnamespace
JOIN pg_attribute ca ON ca.attrelid = co.conrelid AND ca.attnum = co.conkey[1]
JOIN pg_class pr ON pr.oid = co.confrelid
JOIN pg_attribute pa ON pa.attrelid = co.confrelid AND pa.attnum = co.confkey[1]
WHERE co.contype = 'f' AND n.nspname = 'public' AND array_length(co.conkey, 1) = 1
ORDER BY 1, 2
"""


class Refused(Exception):
    """The copy must not go ahead (the message says why)."""


@dataclass(frozen=True)
class ForeignKey:
    table: str
    column: str
    not_null: bool
    parent: str
    parent_column: str


@dataclass
class PruneReport:
    keep_id: int
    before: dict[str, dict[str, int]]
    after: dict[str, dict[str, int]]
    synthetic_batches: list[int] = field(default_factory=list)
    operational: dict[str, int] = field(default_factory=dict)
    nulled: dict[str, int] = field(default_factory=dict)
    executed: bool = False


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def foreign_keys() -> list[ForeignKey]:
    with connection.cursor() as cursor:
        cursor.execute(_FKS_SQL)
        return [ForeignKey(*row) for row in cursor.fetchall()]


def real_identities() -> list[tuple[int, str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, email, oidc_issuer FROM accounts_user "
            "WHERE oidc_issuer <> '' AND oidc_issuer NOT LIKE 'http://%%' ORDER BY id"
        )
        return list(cursor.fetchall())


def applied_migrations() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT app || '.' || name FROM django_migrations")
        return {row[0] for row in cursor.fetchall()}


def check_target(dev_migrations: set[str]) -> None:
    """Raises Refused unless this (production) database may be replaced by the dev copy."""
    real = real_identities()
    if real:
        accounts = ", ".join(f"account {pk} ({issuer})" for pk, _email, issuer in real)
        raise Refused(
            f"production has a real sign-in identity ({accounts}): copying from dev would erase "
            "it, so import-from-dev is refused for good"
        )
    mine = applied_migrations()
    if mine != dev_migrations:
        only_dev = sorted(dev_migrations - mine)
        only_prod = sorted(mine - dev_migrations)
        raise Refused(
            "the applied migrations differ; deploy the commit dev runs (or migrate dev) first. "
            f"only in dev: {only_dev or 'none'}; only in production: {only_prod or 'none'}"
        )


def inventory(fks: list[ForeignKey] | None = None) -> dict[str, dict[str, int]]:
    """Rows per account (email) and table, over every foreign key to accounts_user."""
    fks = foreign_keys() if fks is None else fks
    counts: dict[str, dict[str, int]] = defaultdict(dict)
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, email FROM accounts_user")
        emails = dict(cursor.fetchall())
        for fk in fks:
            if fk.parent != "accounts_user":
                continue
            cursor.execute(
                f"SELECT {_q(fk.column)}, count(*) FROM {_q(fk.table)} "  # noqa: S608 - catalog names
                f"WHERE {_q(fk.column)} IS NOT NULL GROUP BY 1"
            )
            for user_id, count in cursor.fetchall():
                key = f"{fk.table}.{fk.column}"
                counts[emails.get(user_id, f"#{user_id} (missing)")][key] = count
        for email in emails.values():
            counts.setdefault(email, {})
    return dict(counts)


def _is_synthetic(raw_dir: Path, storage_path: str) -> bool:
    path = raw_dir / storage_path
    if not path.is_file():
        raise Refused(f"the kept account's raw file {storage_path} is missing from {raw_dir}")
    with path.open("rb") as handle:
        head = zstandard.ZstdDecompressor().stream_reader(handle).read(4096)
    return SYNTHETIC_MARKER in head


def synthetic_batches(keep_id: int, raw_dir: Path) -> list[int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT b.id, r.storage_path FROM history_importbatch b "
            "JOIN history_rawfile r ON r.id = b.raw_file_id WHERE b.owner_id = %s ORDER BY b.id",
            [keep_id],
        )
        return [pk for pk, path in cursor.fetchall() if _is_synthetic(raw_dir, path)]


def _remove_orphans(cursor, fks: list[ForeignKey], nulled: dict[str, int]) -> None:
    """A NOT NULL reference to a removed row removes its row; a nullable one becomes NULL."""
    while True:
        changed = 0
        for fk in fks:
            orphan = (
                f"{_q(fk.column)} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {_q(fk.parent)} p "  # noqa: S608
                f"WHERE p.{_q(fk.parent_column)} = {_q(fk.table)}.{_q(fk.column)})"
            )
            if fk.not_null:
                cursor.execute(f"DELETE FROM {_q(fk.table)} WHERE {orphan}")  # noqa: S608
            else:
                cursor.execute(
                    f"UPDATE {_q(fk.table)} SET {_q(fk.column)} = NULL WHERE {orphan}"  # noqa: S608
                )
                if cursor.rowcount:
                    key = f"{fk.table}.{fk.column}"
                    nulled[key] = nulled.get(key, 0) + cursor.rowcount
            changed += cursor.rowcount
        if not changed:
            return


class _DryRun(Exception):
    pass


def prune(keep_email: str, raw_dir: Path, *, execute: bool) -> PruneReport:
    """Prune the staging copy down to one account's real data (see the module docstring)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        if cursor.fetchone()[0] == LIVE_DATABASE:
            raise Refused(f"pruning never runs in the live database {LIVE_DATABASE!r}")
        cursor.execute("SELECT id FROM accounts_user WHERE lower(email) = lower(%s)", [keep_email])
        row = cursor.fetchone()
    if row is None:
        raise Refused(f"no account {keep_email!r} in the copy")
    keep_id = row[0]
    fks = foreign_keys()
    report = PruneReport(keep_id=keep_id, before=inventory(fks), after={})
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
            # 1. Every other account's rows (references from the kept account's rows to them
            #    are set to NULL when nullable), then the accounts themselves.
            for fk in fks:
                if fk.parent != "accounts_user" or fk.table == "accounts_user":
                    continue
                if fk.not_null:
                    sql = f"DELETE FROM {_q(fk.table)} WHERE {_q(fk.column)} <> %s"  # noqa: S608
                else:
                    sql = f"UPDATE {_q(fk.table)} SET {_q(fk.column)} = NULL WHERE {_q(fk.column)} <> %s"  # noqa: E501, S608
                cursor.execute(sql, [keep_id])
                if not fk.not_null and cursor.rowcount:
                    report.nulled[f"{fk.table}.{fk.column}"] = cursor.rowcount
            cursor.execute("DELETE FROM accounts_user WHERE id <> %s", [keep_id])
            # 2. The kept account's synthetic batches with everything imported by them, and the
            #    e2e leftovers.
            report.synthetic_batches = synthetic_batches(keep_id, raw_dir)
            if report.synthetic_batches:
                for fk in fks:
                    if fk.parent == "history_importbatch":
                        cursor.execute(
                            f"DELETE FROM {_q(fk.table)} WHERE {_q(fk.column)} = ANY(%s)",  # noqa: S608
                            [report.synthetic_batches],
                        )
                cursor.execute(
                    "SELECT raw_file_id FROM history_importbatch WHERE id = ANY(%s)",
                    [report.synthetic_batches],
                )
                raw_ids = [r[0] for r in cursor.fetchall() if r[0] is not None]
                cursor.execute(
                    "DELETE FROM history_importbatch WHERE id = ANY(%s)", [report.synthetic_batches]
                )
                cursor.execute(
                    "DELETE FROM history_rawfile r WHERE r.id = ANY(%s) AND NOT EXISTS "
                    "(SELECT 1 FROM history_importbatch b WHERE b.raw_file_id = r.id)",
                    [raw_ids],
                )
            for table, owner, name in E2E_ROWS:
                cursor.execute(
                    f"DELETE FROM {_q(table)} WHERE {_q(owner)} = %s AND {_q(name)} LIKE %s",  # noqa: S608
                    [keep_id, E2E_PREFIX],
                )
            _remove_orphans(cursor, fks, report.nulled)
            # 3. Operational tables.
            for table in OPERATIONAL_TABLES:
                cursor.execute(f"SELECT count(*) FROM {_q(table)}")  # noqa: S608
                report.operational[table] = cursor.fetchone()[0]
            cursor.execute("TRUNCATE " + ", ".join(_q(t) for t in OPERATIONAL_TABLES))
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            report.after = inventory(fks)
            if not execute:
                raise _DryRun
    except _DryRun:
        return report
    report.executed = True
    return report


def format_inventory(report: PruneReport) -> str:
    lines = []
    for title, data in (("before (the copy as restored)", report.before), ("after", report.after)):
        lines.append(f"== {title}")
        for email in sorted(data):
            tables = data[email]
            total = sum(tables.values())
            lines.append(f"  {email}: {total} row(s)")
            lines.extend(f"    {table}: {count}" for table, count in sorted(tables.items()))
    lines.append(f"synthetic batches of the kept account: {report.synthetic_batches or 'none'}")
    lines.append(
        "operational tables emptied: "
        + ", ".join(f"{t}={n}" for t, n in report.operational.items())
    )
    if report.nulled:
        lines.append(
            "references set to NULL: "
            + ", ".join(f"{k}={n}" for k, n in sorted(report.nulled.items()))
        )
    lines.append("EXECUTED" if report.executed else "DRY RUN: nothing changed")
    return "\n".join(lines)
