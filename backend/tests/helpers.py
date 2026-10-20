from contextlib import contextmanager

from django.db import connections


@contextmanager
def as_owner(using: str = "default"):
    """Temporarily act as the owner role (bypasses RLS) — for building test fixtures only."""
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT current_user")
        previous = cursor.fetchone()[0]
        cursor.execute("RESET ROLE")
    try:
        yield
    finally:
        with connections[using].cursor() as cursor:
            if previous != "travel_owner":
                cursor.execute(f"SET ROLE {previous}")


def current_role(using: str = "default") -> str:
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT current_user")
        return cursor.fetchone()[0]
