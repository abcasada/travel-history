"""Milestone 1.1: the stack's security-relevant plumbing."""

import pytest
from django.conf import settings
from django.db import connection, transaction
from django.db.utils import ProgrammingError

from tests.helpers import current_role


def test_healthz_reports_ok(client, db):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_db_tests_run_as_the_runtime_role():
    assert current_role() == "travel_app"


@pytest.mark.django_db
@pytest.mark.as_owner
def test_runtime_roles_cannot_bypass_rls_or_escalate():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
            "FROM pg_roles WHERE rolname IN ('travel_app', 'travel_public') ORDER BY rolname"
        )
        rows = cursor.fetchall()
    assert rows == [
        ("travel_app", False, False, False, False),
        ("travel_public", False, False, False, False),
    ]


@pytest.mark.django_db
@pytest.mark.as_owner
def test_runtime_role_owns_no_tables():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_tables WHERE tableowner IN ('travel_app', 'travel_public')"
        )
        assert cursor.fetchone()[0] == 0


@pytest.mark.django_db
def test_runtime_role_cannot_create_tables():
    with pytest.raises(ProgrammingError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("CREATE TABLE should_fail (id int)")


@pytest.mark.django_db
def test_public_role_cannot_read_user_table():
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE travel_public")
    with pytest.raises(ProgrammingError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT * FROM accounts_user")


def test_production_security_defaults():
    # Tests run with production-like settings (no DEBUG, secure cookies).
    assert settings.DEBUG is False
    assert settings.SESSION_COOKIE_SECURE is True
    assert settings.CSRF_COOKIE_SECURE is True
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SECURE_CSP["frame-ancestors"] == ["'none'"]


@pytest.mark.django_db
def test_runtime_role_has_dml_on_app_tables():
    from django.utils import timezone

    from travel.core.models import RateLimitBucket

    bucket = RateLimitBucket.objects.create(key="k", window_start=timezone.now(), count=1)
    RateLimitBucket.objects.filter(pk=bucket.pk).update(count=2)
    assert RateLimitBucket.objects.get(pk=bucket.pk).count == 2


@pytest.mark.django_db
def test_runtime_role_can_use_the_job_queue_tables():
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM procrastinate_jobs")
        cursor.execute("SELECT count(*) FROM procrastinate_workers")


@pytest.mark.django_db
def test_runtime_role_cannot_rewrite_migration_history():
    with pytest.raises(ProgrammingError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM django_migrations")
