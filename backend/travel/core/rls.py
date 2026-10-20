"""Row-level security context (PLAN.md §6.1).

Every database access by the runtime role happens inside a transaction that has set
`app.user_id` (and optionally a narrow system context `app.ctx`) with `set_config(..., true)`,
i.e. transaction-local: nothing leaks to the next request on a pooled connection, and code that
forgets to set a context sees nothing (policies fail closed).
"""

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connections, transaction

SYSTEM_CONTEXTS = frozenset({"", "auth", "ingest", "public_form", "transfer"})


def set_context(user_id: int | None, ctx: str = "", using: str = "default") -> None:
    if ctx not in SYSTEM_CONTEXTS:
        raise ValueError(f"unknown RLS system context {ctx!r}")
    conn = connections[using]
    if not conn.in_atomic_block:
        raise RuntimeError("RLS context must be set inside a transaction (transaction.atomic)")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.user_id', %s, true), set_config('app.ctx', %s, true)",
            ["" if user_id is None else str(int(user_id)), ctx],
        )


def get_context(using: str = "default") -> tuple[int | None, str]:
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT app.user_id(), app.ctx()")
        uid, ctx = cursor.fetchone()
    return uid, ctx


@contextmanager
def rls_context(user_id: int | None, ctx: str = "", using: str = "default") -> Iterator[None]:
    """Run a block as `user_id` (worker jobs, management tasks acting for a user). Restores the
    previous context on exit when nested inside an outer transaction."""
    with transaction.atomic(using=using):
        previous = get_context(using) if connections[using].in_atomic_block else (None, "")
        set_context(user_id, ctx, using)
        try:
            yield
        finally:
            if connections[using].in_atomic_block and not connections[using].needs_rollback:
                set_context(*previous, using=using)
