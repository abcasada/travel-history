"""Periodic jobs that cover every user under RLS (work-order item 9, T8, D-87).

Everything runs as `travel_app`: the enumerator `app.job_user_ids`, the per-user runner in
`travel.core.jobs`, and the first real job (`stale_uploads`)."""

import datetime as dt
import logging
import threading

import pytest
from django.db import connection, connections, transaction
from django.utils import timezone

from tests.factories import UserFactory
from tests.helpers import as_owner
from travel.accounts.models import Role, User
from travel.core import jobs
from travel.core.rls import get_context, rls_context, set_context
from travel.history import uploads
from travel.history.models import ImportBatch, UploadSession

TX = pytest.mark.django_db(transaction=True)
SENTINEL = "sentinel-person@example.test"


def make_users() -> dict[str, User]:
    with as_owner():
        return {
            "admin": UserFactory(role=Role.ADMIN),
            "alice": UserFactory(),
            "bob": UserFactory(),
            "viewer": UserFactory(role=Role.VIEWER),
            "gone": UserFactory(is_active=False),
        }


def make_session(owner: User, *, stale: bool = False) -> UploadSession:
    with as_owner():
        session = UploadSession.objects.create(
            owner=owner,
            filename="SYNTHETIC.json",
            kind=ImportBatch.Kind.GOOGLE_TIMELINE,
            total_size=10,
            chunk_size=10,
        )
        if stale:
            old = timezone.now() - uploads.STALE_AFTER - dt.timedelta(hours=1)
            UploadSession.objects.filter(pk=session.pk).update(updated_at=old)
    return session


def call_enumerator(roles) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM app.job_user_ids(%s::text[])", [list(roles)])
        return cursor.fetchall()


# --- The enumerator ------------------------------------------------------------------------


@pytest.mark.django_db
def test_enumerator_is_a_narrow_security_definer_function():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.prorettype = 'bigint'::regtype, p.proretset, p.prosecdef, p.proconfig,
                   p.proowner = (SELECT proowner FROM pg_proc WHERE oid = 'app.user_id()'::regprocedure),
                   has_function_privilege('travel_app', p.oid, 'EXECUTE'),
                   has_function_privilege('travel_public', p.oid, 'EXECUTE'),
                   EXISTS (SELECT 1 FROM aclexplode(p.proacl) a
                            WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE')
              FROM pg_proc p WHERE p.oid = 'app.job_user_ids(text[])'::regprocedure
            """  # noqa: E501
        )
        returns_bigint, returns_set, definer, config, same_owner, app, public, anyone = (
            cursor.fetchone()
        )
    assert returns_bigint and returns_set  # bare ids, nothing else
    assert definer and same_owner  # runs as the owner role, like the policy helpers
    assert config == ["search_path=public, pg_temp"]
    assert app and not public and not anyone


@pytest.mark.django_db
def test_enumerator_lists_only_ids_of_active_users_with_the_roles():
    users = make_users()
    with rls_context(None, ctx="jobs"):
        rows = call_enumerator(jobs.RAW_HISTORY_ROLES)
        assert all(len(row) == 1 for row in rows)  # one column: the id
        assert [row[0] for row in rows] == sorted(users[k].pk for k in ("admin", "alice", "bob"))
        assert [row[0] for row in call_enumerator(["viewer"])] == [users["viewer"].pk]
        assert call_enumerator([]) == []
        assert jobs.user_ids(["member"]) == sorted([users["alice"].pk, users["bob"].pk])


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("as_user", "ctx"),
    [(False, ""), (True, ""), (True, "jobs"), (False, "auth"), (False, "ingest")],
)
def test_enumerator_returns_nothing_outside_the_jobs_context(as_user, ctx):
    """An ordinary request, a job body already acting as a user, and the other system
    contexts all get no rows (fail closed)."""
    users = make_users()
    set_context(users["alice"].pk if as_user else None, ctx)
    assert call_enumerator(["admin", "member", "viewer"]) == []


@pytest.mark.django_db
def test_jobs_context_grants_no_rows():
    users = make_users()
    make_session(users["alice"])
    with rls_context(None, ctx="jobs"):
        assert not User.objects.exists()
        assert not UploadSession.objects.exists()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_policies "
            "WHERE coalesce(qual, '') LIKE '%jobs%' OR coalesce(with_check, '') LIKE '%jobs%'"
        )
        assert cursor.fetchone()[0] == 0


# --- The per-user runner -------------------------------------------------------------------


@pytest.mark.django_db
def test_runner_refuses_to_run_inside_a_transaction():
    with pytest.raises(RuntimeError):
        jobs.run_per_user("test-job", lambda _uid: None, jobs.RAW_HISTORY_ROLES)


@TX
def test_each_user_gets_its_own_transaction_and_sees_only_their_rows():
    users = make_users()
    for user in users.values():
        make_session(user)
    seen: dict[int, tuple] = {}

    def body(user_id: int) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT txid_current()")
            txid = cursor.fetchone()[0]
        owners = set(UploadSession.objects.values_list("owner_id", flat=True))
        accounts = set(User.objects.values_list("pk", flat=True))
        seen[user_id] = (get_context(), owners, accounts, txid, connection.in_atomic_block)

    summary = jobs.run_per_user("test-job", body, jobs.RAW_HISTORY_ROLES)

    expected = [users[k].pk for k in ("admin", "alice", "bob")]
    assert sorted(seen) == sorted(expected)  # not the Viewer, not the deactivated account
    assert (summary.users, summary.succeeded, summary.failed) == (3, 3, 0)
    for user_id, (context, owners, accounts, _txid, atomic) in seen.items():
        assert context == (user_id, "")
        assert owners == {user_id}  # only their own uploads
        assert accounts == {user_id} or users["admin"].pk == user_id  # Admin reads accounts
        assert atomic
    assert len({entry[3] for entry in seen.values()}) == 3  # three separate transactions


@TX
def test_context_does_not_leak_between_users_or_after_the_run():
    users = make_users()
    contexts: list[tuple] = []

    def body(user_id: int) -> None:
        with connection.cursor() as cursor:
            # What the previous user's transaction would have left at session level.
            cursor.execute("SELECT current_setting('app.user_id', true)")
            contexts.append((user_id, cursor.fetchone()[0]))

    jobs.run_per_user("test-job", body, jobs.RAW_HISTORY_ROLES)

    assert [uid for uid, _ in contexts] == sorted(users[k].pk for k in ("admin", "alice", "bob"))
    assert all(value == str(uid) for uid, value in contexts)
    with connection.cursor() as cursor:  # autocommit: a new transaction
        cursor.execute("SELECT coalesce(current_setting('app.user_id', true), '')")
        assert cursor.fetchone()[0] == ""
    with transaction.atomic():
        assert get_context() == (None, "")
        assert not UploadSession.objects.exists()
        assert not User.objects.exists()


@TX
def test_one_users_failure_is_rolled_back_logged_and_the_rest_continue(caplog):
    users = make_users()
    for user in users.values():
        make_session(user)
    alice, bob = users["alice"].pk, users["bob"].pk

    def body(user_id: int) -> None:
        UploadSession.objects.update(status=UploadSession.Status.ABORTED)
        if user_id == alice:
            raise ValueError(f"cannot handle {SENTINEL}")
        if user_id == bob:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 / 0")  # a database error aborts the transaction

    with caplog.at_level(logging.INFO, logger="travel.core.jobs"):
        summary = jobs.run_per_user("test-job", body, jobs.RAW_HISTORY_ROLES)

    assert (summary.users, summary.succeeded, summary.failed) == (3, 1, 2)
    with as_owner():
        status = dict(UploadSession.objects.values_list("owner_id", "status"))
    assert status[users["admin"].pk] == UploadSession.Status.ABORTED  # committed
    assert status[alice] == status[bob] == UploadSession.Status.OPEN  # rolled back
    assert status[users["viewer"].pk] == status[users["gone"].pk] == UploadSession.Status.OPEN
    text = caplog.text
    assert "ValueError" in text and "DataError" in text
    assert SENTINEL not in text and "division by zero" not in text
    assert "test-job done: 3 users, 1 ok, 2 failed" in text


@TX
def test_a_second_run_is_skipped_while_one_holds_the_lock():
    """Another worker process holding the run lock (a separate session) blocks a run."""
    make_users()
    calls: list[int] = []
    with jobs.run_lock("test-job") as acquired:
        assert acquired
        summary = jobs.run_per_user("test-job", calls.append, jobs.RAW_HISTORY_ROLES)
        assert summary.skipped and calls == []
        # Other jobs are not blocked.
        assert not jobs.run_per_user("other-job", calls.append, ["viewer"]).skipped
    assert len(calls) == 1
    assert not jobs.run_per_user("test-job", calls.append, jobs.RAW_HISTORY_ROLES).skipped
    assert len(calls) == 4  # the lock is free again once its session ends


@TX
def test_concurrent_runs_never_process_a_user_twice():
    users = make_users()
    processed: list[tuple[str, int]] = []
    started, release = threading.Event(), threading.Event()
    errors: list[BaseException] = []
    results: dict[str, jobs.RunSummary] = {}

    def slow_body(user_id: int) -> None:
        processed.append(("first", user_id))
        started.set()
        assert release.wait(timeout=30)

    def first_run() -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET ROLE travel_app")
            results["first"] = jobs.run_per_user("test-job", slow_body, jobs.RAW_HISTORY_ROLES)
        except BaseException as exc:  # noqa: BLE001 (reported by the main thread)
            errors.append(exc)
        finally:
            started.set()
            connections.close_all()

    thread = threading.Thread(target=first_run)
    thread.start()
    try:
        assert started.wait(timeout=30)
        results["second"] = jobs.run_per_user(
            "test-job", lambda uid: processed.append(("second", uid)), jobs.RAW_HISTORY_ROLES
        )
    finally:
        release.set()
        thread.join(timeout=60)
    assert errors == []
    assert results["second"].skipped
    assert results["first"].succeeded == 3
    expected = sorted(users[k].pk for k in ("admin", "alice", "bob"))
    assert sorted(uid for _, uid in processed) == expected
    assert {run for run, _ in processed} == {"first"}


# --- Registered jobs -----------------------------------------------------------------------


def test_scheduled_jobs_are_periodic_with_locks_and_placeholders_are_not():
    from procrastinate.contrib.django import app

    registered = app.periodic_registry.periodic_tasks
    for job in jobs.REGISTRY.values():
        key = ("core.run_user_job", f"user-job-{job.name}")
        if not job.scheduled:
            assert key not in registered
            assert job.planned
            continue
        kwargs = registered[key].configure_kwargs
        assert kwargs["task_kwargs"]["job"] == job.name
        assert kwargs["lock"] == kwargs["queueing_lock"] == f"user-job-{job.name}"
        assert registered[key].cron == job.cron
    assert jobs.REGISTRY["stale_uploads"].scheduled


@pytest.mark.django_db
def test_placeholder_jobs_cannot_run():
    with pytest.raises(ValueError):
        jobs.run_job("trip_detection")


@TX
def test_stale_uploads_job_aborts_every_users_abandoned_uploads(settings, tmp_path):
    from travel.core.tasks import run_user_job

    settings.BULK_DIR = tmp_path
    users = make_users()
    sessions = {
        "alice_stale": make_session(users["alice"], stale=True),
        "alice_fresh": make_session(users["alice"]),
        "bob_stale": make_session(users["bob"], stale=True),
        "gone_stale": make_session(users["gone"], stale=True),
    }
    for session in sessions.values():
        path = uploads.part_path(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"SYNTHETIC")

    result = run_user_job(job="stale_uploads", timestamp=0)

    assert result == {"job": "stale_uploads", "skipped": False, "users": 3, "succeeded": 3,
                      "failed": 0}  # fmt: skip
    with as_owner():
        status = {k: UploadSession.objects.get(pk=s.pk).status for k, s in sessions.items()}
    assert status == {
        "alice_stale": UploadSession.Status.ABORTED,
        "alice_fresh": UploadSession.Status.OPEN,
        "bob_stale": UploadSession.Status.ABORTED,
        "gone_stale": UploadSession.Status.OPEN,  # deactivated accounts are left alone
    }
    exists = {k: uploads.part_path(s).exists() for k, s in sessions.items()}
    assert exists == {
        "alice_stale": False,
        "alice_fresh": True,
        "bob_stale": False,
        "gone_stale": True,
    }
