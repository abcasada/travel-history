from procrastinate.contrib.django import app


@app.task(name="history.process_upload", queue="imports", retry=2)
def process_upload(upload_id: str, owner_id: int) -> None:
    """Archive an uploaded file and import it (serialized per user via a lock at defer time)."""
    from .uploads import process_upload as run

    run(upload_id, owner_id)
