"""Periodic jobs that cover every user under row-level security (work-order item 9, T8, D-87).

The worker connects as `travel_app` (NOBYPASSRLS), so a job sees a user's rows only inside a
transaction whose transaction-local `app.user_id` is that user. A cross-user job therefore:

1. lists the users it applies to with `app.job_user_ids(roles)` (core migration 0003), in its
   own transaction under the `jobs` system context: bare ids of active accounts with one of the
   job's roles, nothing else;
2. runs the job body once per user, each in its own transaction with that user's context set by
   `rls_context` (transaction-local, so nothing carries over to the next user or transaction).
   The body sees exactly what that user could see, and RLS checks every write against them.
   A failing user is rolled back and logged (job name, account id and exception class only, never
   the message, which could quote data) and the run goes on with the next user;
3. holds a session advisory lock for the whole run on a dedicated connection, so two runs of the
   same job (an overlapping periodic run, a manual run) never process users at the same time:
   the second one is skipped. The lock connection runs nothing else, and closing it releases the
   lock even if the worker dies mid-run.

Jobs are listed in `REGISTRY`. Entries without a body are placeholders for jobs that later work
items implement; they are not scheduled. `travel/core/tasks.py` schedules the others.
"""

from __future__ import annotations

import logging
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from django.db import connections
from django.utils.module_loading import import_string

from travel.accounts.models import Role

from .rls import rls_context

log = logging.getLogger(__name__)

# First half of the two-key advisory lock, so these locks can't collide with other users of
# advisory locks in the same database.
JOB_LOCK_NAMESPACE = 0x54384A42

RAW_HISTORY_ROLES = (Role.ADMIN.value, Role.MEMBER.value)  # Viewers have no raw history


@dataclass(frozen=True)
class UserJob:
    """A job run once per user. `body` is the dotted path of a function taking the user id; it
    runs inside that user's RLS transaction. `cron` is in UTC (Procrastinate's schedule)."""

    name: str
    roles: tuple[str, ...]
    body: str | None = None
    cron: str | None = None
    planned: str = ""  # for placeholders: which work item fills it in

    @property
    def scheduled(self) -> bool:
        return self.body is not None and self.cron is not None


REGISTRY: dict[str, UserJob] = {
    job.name: job
    for job in (
        # Abandoned resumable uploads: mark them aborted and delete their part files. Upload
        # creation already does this for the uploading user; this covers users who never come
        # back, whose part files would otherwise stay on disk.
        UserJob(
            "stale_uploads",
            RAW_HISTORY_ROLES,
            body="travel.history.uploads.drop_stale_sessions",
            cron="17 2 * * *",
        ),
        # Expired routing proposals (routing.md §13.1): the user's next proposal also drops
        # them; this covers users who stop routing, so drawn waypoints don't linger.
        UserJob(
            "routing_cache",
            (Role.ADMIN.value, Role.MEMBER.value),
            body="travel.routing.services.purge_expired_cache",
            cron="41 * * * *",
        ),
        UserJob("coverage_reports", RAW_HISTORY_ROLES, planned="work-order item 12 (T10)"),
        UserJob("trip_detection", RAW_HISTORY_ROLES, planned="phase 4 trip detection (§11)"),
        UserJob(
            "public_snapshots",
            (Role.ADMIN.value, Role.MEMBER.value),
            planned="phase 8 public pages (§6.5), if a periodic rebuild is needed",
        ),
    )
}


@dataclass
class RunSummary:
    job: str
    skipped: bool = False  # another run of the same job held the lock
    users: int = 0
    succeeded: int = 0
    failed: int = 0


def lock_key(job: str) -> int:
    """Second half of the advisory lock key: a stable signed 32-bit hash of the job name."""
    value = zlib.crc32(job.encode())
    return value - (1 << 32) if value >= 1 << 31 else value


@contextmanager
def run_lock(job: str, using: str = "default") -> Iterator[bool]:
    """Yield whether this process got the job's run lock. Held on a connection of its own, so
    the per-user transactions on the main connection don't affect it and closing it frees it."""
    conn = connections.create_connection(using)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(%s, %s)", [JOB_LOCK_NAMESPACE, lock_key(job)]
            )
            acquired = cursor.fetchone()[0]
        yield acquired
    finally:
        conn.close()


def user_ids(roles: tuple[str, ...] | list[str], using: str = "default") -> list[int]:
    """Active accounts with one of `roles`, from the narrow enumerator (ids only)."""
    with rls_context(None, ctx="jobs", using=using), connections[using].cursor() as cursor:
        cursor.execute("SELECT id FROM app.job_user_ids(%s::text[]) AS id", [list(roles)])
        return [row[0] for row in cursor.fetchall()]


def run_per_user(
    job: str,
    body: Callable[[int], object],
    roles: tuple[str, ...] | list[str],
    using: str = "default",
) -> RunSummary:
    """Run `body(user_id)` once for every active user with one of `roles`, each in its own
    transaction acting as that user. Must be called outside any transaction."""
    if connections[using].in_atomic_block:
        raise RuntimeError("run_per_user must run outside a transaction: each user gets its own")
    summary = RunSummary(job)
    with run_lock(job, using) as acquired:
        if not acquired:
            summary.skipped = True
            log.info("job %s skipped: another run holds its lock", job)
            return summary
        ids = user_ids(roles, using)
        summary.users = len(ids)
        for user_id in ids:
            try:
                with rls_context(user_id, using=using):
                    body(user_id)
            except Exception as exc:  # noqa: BLE001 (one user's failure must not stop the rest)
                summary.failed += 1
                log.warning("job %s failed for user %s: %s", job, user_id, type(exc).__name__)
            else:
                summary.succeeded += 1
    log.info(
        "job %s done: %s users, %s ok, %s failed",
        job,
        summary.users,
        summary.succeeded,
        summary.failed,
    )
    return summary


def run_job(name: str, using: str = "default") -> RunSummary:
    """Run a registered job (the periodic task and manual runs)."""
    job = REGISTRY[name]
    if job.body is None:
        raise ValueError(f"job {name!r} is a placeholder ({job.planned})")
    return run_per_user(name, import_string(job.body), job.roles, using)
