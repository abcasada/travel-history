"""Moving the real data from the development database into production (work-order item 40b,
docs/production.md "Copying the data from development").

`./dev prod import-from-dev` restores a dump of the dev database into a staging database next to
production's, then runs these functions there through `manage.py dev_copy` (owner role):

- `check_target`: refuses when the two databases' applied migrations differ, and forever once
  any production account has a real identity (an https issuer: production refuses any other
  issuer, and the dev mock provider's is http), because the copy would erase it;
- `prune`: every account but the kept one goes with all its rows, the kept account's synthetic
  rows (batches whose raw file carries the SYNTHETIC fixture marker or, for a trip
  spreadsheet, a title starting with it; such raw files no batch uses; the e2e smoke test's
  leftovers: trips, places, tokens and persons named "E2E …", its tags) too, and the
  operational tables (sessions, the job queue, rate-limit counters, the routing cache) are
  emptied. One transaction; a dry run rolls back.
- `remove_e2e_leftovers` (`e2e_cleanup`, the live dev and lane databases): the same e2e rows and
  SYNTHETIC trip-sheet batches, by name and marker only, never a raw file.

All of it is generic over the foreign keys PostgreSQL knows, not over Django's `on_delete`
(most user foreign keys are DO_NOTHING): a NOT NULL reference to a removed row removes the
referencing row, a nullable one is set to NULL, repeated until nothing changes.
"""

from __future__ import annotations

import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import zstandard
from defusedxml import ElementTree
from django.db import connection, transaction

# The live database's name in both stacks: pruning never runs there (only in the staging copy).
LIVE_DATABASE = "travel"
SYNTHETIC_MARKER = b"SYNTHETIC"
# A trip spreadsheet is a zip, so the marker is never in its first bytes: SYNTHETIC workbooks
# (the e2e fixture, scripts/make_e2e_trip_sheet.py) start their title with it instead. The
# template's title only contains it ("… (SYNTHETIC example)"), so a real sheet made from the
# template never matches.
WORKBOOK_TITLE = "{http://purl.org/dc/elements/1.1/}title"
MAX_WORKBOOK_BYTES = 16 * 1024 * 1024  # trip sheets are refused above 10 MB at upload
MAX_CORE_XML_BYTES = 64 * 1024
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
# The e2e smoke test (e2e/smoke.mjs) names what it creates "E2E …", and the tags it makes
# `e2e` (the trip spreadsheet's) and `e2e-bulk-<time>` (the bulk edit's): (table, owner
# column, name column, ILIKE pattern). F-11 added the persons and the tags.
E2E_ROWS = (
    ("trips_trip", "owner_id", "title", "E2E %"),
    ("trips_place", "owner_id", "name", "E2E %"),
    ("accounts_devicetoken", "user_id", "name", "E2E %"),
    ("accounts_person", "created_by_id", "display_name", "E2E %"),
    ("trips_tag", "owner_id", "name", "e2e"),
    ("trips_tag", "owner_id", "name", "e2e-bulk-%"),
)
TRIP_SHEET = "trip_sheet"

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
    synthetic_raw_files: list[int] = field(default_factory=list)
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


def is_synthetic_workbook(data: bytes) -> bool:
    """An .xlsx whose title (docProps/core.xml) starts with the SYNTHETIC marker."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("docProps/core.xml")
            if info.file_size > MAX_CORE_XML_BYTES:
                return False
            root = ElementTree.fromstring(archive.read(info))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError):
        return False
    title = root.findtext(WORKBOOK_TITLE) or ""
    return title.strip().startswith(SYNTHETIC_MARKER.decode())


def _is_synthetic(raw_dir: Path, storage_path: str, kind: str | None = None) -> bool:
    path = raw_dir / storage_path
    if not path.is_file():
        raise Refused(f"the kept account's raw file {storage_path} is missing from {raw_dir}")
    with path.open("rb") as handle:
        reader = zstandard.ZstdDecompressor().stream_reader(handle)
        if kind == TRIP_SHEET:
            return is_synthetic_workbook(reader.read(MAX_WORKBOOK_BYTES))
        head = reader.read(4096)
    return SYNTHETIC_MARKER in head


def synthetic_batches(keep_id: int, raw_dir: Path) -> list[int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT b.id, b.kind, r.storage_path FROM history_importbatch b "
            "JOIN history_rawfile r ON r.id = b.raw_file_id WHERE b.owner_id = %s ORDER BY b.id",
            [keep_id],
        )
        return [pk for pk, kind, path in cursor.fetchall() if _is_synthetic(raw_dir, path, kind)]


def synthetic_unused_raw_files(keep_id: int, raw_dir: Path) -> list[int]:
    """The kept account's raw files no batch uses any more (`e2e_cleanup` removes the e2e
    trip-sheet batches but never a raw file) that are SYNTHETIC, by either test."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT r.id, r.storage_path FROM history_rawfile r WHERE r.owner_id = %s AND NOT "
            "EXISTS (SELECT 1 FROM history_importbatch b WHERE b.raw_file_id = r.id) ORDER BY 1",
            [keep_id],
        )
        return [
            pk
            for pk, path in cursor.fetchall()
            if _is_synthetic(raw_dir, path) or _is_synthetic(raw_dir, path, TRIP_SHEET)
        ]


def delete_sheet_links(cursor, batch_ids: list[int]) -> int:
    """Key links whose last record came from these trip-sheet batches: their reference to the
    record is nullable, so the generic cleanup would keep them as rows naming an e2e key."""
    cursor.execute(
        "DELETE FROM trips_tripsheetlink WHERE last_record_id IN "
        "(SELECT id FROM trips_tripsheetrecord WHERE import_batch_id = ANY(%s))",
        [batch_ids],
    )
    return cursor.rowcount


def delete_rows(
    cursor,
    fks: list[ForeignKey],
    table: str,
    column: str,
    values: list,
    nulled: dict[str, int],
    _depth: int = 0,
) -> int:
    """Delete the rows of `table` whose `column` is in `values`, with the rows that can't
    outlive them: a NOT NULL reference to them is deleted the same way, a nullable one set to
    NULL. For the live database, where `_remove_orphans`' whole-database scan is too broad."""
    if not values:
        return 0
    if _depth > 10:
        raise Refused(f"references to {table} go deeper than expected")
    for fk in fks:
        if fk.parent != table:
            continue
        cursor.execute(
            f"SELECT DISTINCT {_q(fk.parent_column)} FROM {_q(table)} "  # noqa: S608 - catalog names
            f"WHERE {_q(column)} = ANY(%s)",
            [values],
        )
        referenced = [row[0] for row in cursor.fetchall()]
        if not referenced:
            continue
        if fk.not_null:
            delete_rows(cursor, fks, fk.table, fk.column, referenced, nulled, _depth + 1)
            continue
        # Only touch rows that refer: raw points and raw files refuse any UPDATE.
        cursor.execute(
            f"UPDATE {_q(fk.table)} SET {_q(fk.column)} = NULL "  # noqa: S608 - catalog names
            f"WHERE {_q(fk.column)} = ANY(%s)",
            [referenced],
        )
        if cursor.rowcount:
            key = f"{fk.table}.{fk.column}"
            nulled[key] = nulled.get(key, 0) + cursor.rowcount
    cursor.execute(
        f"DELETE FROM {_q(table)} WHERE {_q(column)} = ANY(%s)",  # noqa: S608 - catalog names
        [values],
    )
    return cursor.rowcount


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
                delete_sheet_links(cursor, report.synthetic_batches)
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
            unused = synthetic_unused_raw_files(keep_id, raw_dir)
            if unused:
                cursor.execute("DELETE FROM history_rawfile WHERE id = ANY(%s)", [unused])
            report.synthetic_raw_files = unused
            for table, owner, name, pattern in E2E_ROWS:
                cursor.execute(
                    f"DELETE FROM {_q(table)} WHERE {_q(owner)} = %s AND {_q(name)} ILIKE %s",  # noqa: S608
                    [keep_id, pattern],
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
    lines.append(f"synthetic raw files no batch used: {report.synthetic_raw_files or 'none'}")
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


# --- e2e_cleanup (the live dev and lane databases) ---------------------------------------------


@dataclass
class E2eCleanupReport:
    removed: dict[str, int] = field(default_factory=dict)
    nulled: dict[str, int] = field(default_factory=dict)


def synthetic_sheet_batches(raw_dir: Path) -> list[int]:
    """Every account's trip-sheet batches whose workbook is SYNTHETIC (the e2e fixture). A raw
    file missing from the archive is skipped here: this is cleanup, not a copy."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT b.id, r.storage_path FROM history_importbatch b "
            "JOIN history_rawfile r ON r.id = b.raw_file_id WHERE b.kind = %s ORDER BY b.id",
            [TRIP_SHEET],
        )
        rows = cursor.fetchall()
    found = []
    for pk, path in rows:
        try:
            if _is_synthetic(raw_dir, path, TRIP_SHEET):
                found.append(pk)
        except Refused:
            continue
    return found


def remove_e2e_leftovers(raw_dir: Path) -> E2eCleanupReport:
    """What `./dev e2e` leaves in a live database (F-11): persons named "E2E …", its tags, and
    the SYNTHETIC trip-sheet batches with their parsed tabs and key links. By name and marker
    only, in every account (the e2e signs in as dev-member). Raw files stay (rule 12): a later
    run reuses the archived one (D-100), and the dev copy prunes it."""
    report = E2eCleanupReport()
    fks = foreign_keys()
    with transaction.atomic(), connection.cursor() as cursor:
        batches = synthetic_sheet_batches(raw_dir)
        if batches:
            report.removed["trips_tripsheetlink"] = delete_sheet_links(cursor, batches)
            report.removed["history_importbatch (trip sheets)"] = delete_rows(
                cursor, fks, "history_importbatch", "id", batches, report.nulled
            )
        for table, _owner, name, pattern in E2E_ROWS:
            if table not in ("accounts_person", "trips_tag"):
                continue  # trips, places and tokens: the e2e deletes or revokes its own
            cursor.execute(
                f"SELECT id FROM {_q(table)} WHERE {_q(name)} ILIKE %s",  # noqa: S608 - fixed names
                [pattern],
            )
            ids = [row[0] for row in cursor.fetchall()]
            if ids:
                count = delete_rows(cursor, fks, table, "id", ids, report.nulled)
                report.removed[table] = report.removed.get(table, 0) + count
    return report
