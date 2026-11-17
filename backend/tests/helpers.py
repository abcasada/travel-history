from contextlib import contextmanager

from django.db import connections
from django.urls import URLPattern, URLResolver, get_resolver


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


def sample_paths(resolver=None, prefix=""):
    """One concrete path per URL pattern (converters filled with sample values)."""
    resolver = resolver or get_resolver()
    for entry in resolver.url_patterns:
        route = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            yield from sample_paths(entry, route)
        elif isinstance(entry, URLPattern):
            path = "/" + route.lstrip("^").rstrip("$")
            for converter, sample in (
                ("<int:", "1"),
                ("<str:", "x"),
                ("<slug:", "x"),
                ("<uuid:", "00000000-0000-0000-0000-000000000000"),
                ("<path:", "x"),
                ("<", "x"),
            ):
                while converter in path:
                    start = path.index(converter)
                    path = path[:start] + sample + path[path.index(">", start) + 1 :]
            yield path
