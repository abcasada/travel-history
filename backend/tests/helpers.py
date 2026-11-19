import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

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


def rollup_mismatches(owner_ids=None, using: str = "default") -> list[tuple]:
    """Rows where `history_pointrollup` differs from counting the raw points again (history
    migration 0010), as (owner, level, grain, period, source, cell, rollup n, raw n). Run as the
    owner role, so every user's rows are compared. Empty when the roll-up is consistent."""
    from travel.history import tiles

    levels = "{" + ",".join(str(level) for level in tiles.ROLLUP_LEVELS) + "}"
    with as_owner(using), connections[using].cursor() as cursor:
        cursor.execute(
            """
            WITH raw AS (
              SELECT p.owner_id, l.level, g.grain,
                     CASE g.grain WHEN %(day)s THEN (p.ts AT TIME ZONE 'UTC')::date
                          ELSE date_trunc('year', p.ts AT TIME ZONE 'UTC')::date END AS period,
                     p.source, p.tile_key >> (2 * (20 - l.level)) AS cell, count(*) AS n
                FROM history_locationpoint p
               CROSS JOIN unnest(%(levels)s::smallint[]) l(level)
               CROSS JOIN unnest(%(grains)s::smallint[]) g(grain)
               WHERE %(owners)s::bigint[] IS NULL OR p.owner_id = ANY(%(owners)s::bigint[])
               GROUP BY 1, 2, 3, 4, 5, 6
              UNION ALL  -- hourly counts for the coverage strip (migration 0013)
              SELECT p.owner_id, 0, 3, (p.ts AT TIME ZONE 'UTC')::date, p.source,
                     extract(hour FROM p.ts AT TIME ZONE 'UTC')::bigint, count(*)
                FROM history_locationpoint p
               WHERE %(owners)s::bigint[] IS NULL OR p.owner_id = ANY(%(owners)s::bigint[])
               GROUP BY 1, 2, 3, 4, 5, 6
            ), rolled AS (
              SELECT owner_id, level, grain, period, source, cell, n FROM history_pointrollup
               WHERE %(owners)s::bigint[] IS NULL OR owner_id = ANY(%(owners)s::bigint[])
            )
            SELECT owner_id, level, grain, period, source, cell, r.n, raw.n
              FROM rolled r FULL JOIN raw USING (owner_id, level, grain, period, source, cell)
             WHERE r.n IS DISTINCT FROM raw.n
            """,
            {
                "day": tiles.GRAIN_DAY,
                "levels": levels,
                "grains": [tiles.GRAIN_DAY, tiles.GRAIN_YEAR],
                "owners": list(owner_ids) if owner_ids is not None else None,
            },
        )
        return cursor.fetchall()


BACKEND_DIR = Path(__file__).resolve().parent.parent
# A generated-looking key for settings loaded in a fresh process (production servers refuse
# short or placeholder keys).
TEST_SECRET_KEY = "test-only-0123456789abcdefghijklmnopqrstuvwxyz-ABCDEF"
_DUMP_SETTINGS = """
import json, sys
from django.conf import settings
print(json.dumps({name: getattr(settings, name) for name in sys.argv[1:]}))
"""


def load_settings(env: dict[str, str], names: list[str]) -> subprocess.CompletedProcess:
    """Settings as a fresh process would load them from this environment (none of this
    container's DJANGO_/TRAVEL_/OIDC_/RATELIMIT_ variables leak in). stdout holds `names` as
    JSON when the process succeeds; stderr holds ImproperlyConfigured when it refuses."""
    prefixes = ("DJANGO_", "TRAVEL_", "OIDC_", "RATELIMIT_")
    full_env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(prefixes)},
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_SECRET_KEY": TEST_SECRET_KEY,
        **env,
    }
    return subprocess.run(  # noqa: S603 - fixed interpreter and script
        [sys.executable, "-c", _DUMP_SETTINGS, *names],
        cwd=BACKEND_DIR,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def loaded(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)
