from procrastinate.contrib.django import app


@app.periodic(cron="23 * * * *", periodic_id="purge-rate-limits")
@app.task(name="core.purge_rate_limits", queue="maintenance")
def purge_rate_limits(timestamp: int) -> int:  # noqa: ARG001 (procrastinate passes the schedule time)
    """Hourly: drop rate-limit buckets whose window is over (D-77)."""
    from . import ratelimit

    return ratelimit.purge_expired()


@app.task(name="core.run_user_job", queue="maintenance")
def run_user_job(job: str, timestamp: int | None = None) -> dict:  # noqa: ARG001
    """Run a registered per-user job over every user it applies to (D-87, travel/core/jobs.py)."""
    from dataclasses import asdict

    from . import jobs

    return asdict(jobs.run_job(job))


def _schedule() -> None:
    from .jobs import REGISTRY

    for job in REGISTRY.values():
        if not job.scheduled:
            continue
        # One run of a job at a time: the Procrastinate lock keeps a second worker from starting
        # it while one runs, the queueing lock keeps at most one waiting; the advisory run lock
        # in jobs.run_per_user covers manual runs as well.
        app.periodic(
            cron=job.cron,
            periodic_id=f"user-job-{job.name}",
            task_kwargs={"job": job.name},
            lock=f"user-job-{job.name}",
            queueing_lock=f"user-job-{job.name}",
        )(run_user_job)


_schedule()
