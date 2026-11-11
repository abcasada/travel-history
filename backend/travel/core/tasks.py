from procrastinate.contrib.django import app


@app.periodic(cron="23 * * * *", periodic_id="purge-rate-limits")
@app.task(name="core.purge_rate_limits", queue="maintenance")
def purge_rate_limits(timestamp: int) -> int:  # noqa: ARG001 (procrastinate passes the schedule time)
    """Hourly: drop rate-limit buckets whose window is over (D-77)."""
    from . import ratelimit

    return ratelimit.purge_expired()
