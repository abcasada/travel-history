"""Device tokens never reach logs, error reports, error pages or the database in clear
(work-order item 7; threat model §20, "Tracker tokens").

Layer 1: the code never logs a token, and query-string tokens are cut out of the request
before anything else runs; checked on every log record each request path produces (success,
each refusal, rate limits, a server error) and on the report Django would mail for a 500.
Layer 2: every configured log line passes through a redacting formatter; checked directly.
"""

import base64
import hashlib
import json
import logging
import time

import pytest
from django.db import connection
from django.test import Client
from django.views.debug import ExceptionReporter

from tests.factories import UserFactory, device_token
from tests.helpers import as_owner
from travel.core.logredact import RedactingFormatter, RedactingServerFormatter, redact
from travel.tracking import ingest

pytestmark = pytest.mark.django_db(databases=["default", "ratelimit"])

OWNTRACKS = "/api/v1/ingest/owntracks"
OVERLAND = "/api/v1/ingest/overland"


def location(minutes_ago: float = 5, **extra) -> str:
    tst = int(time.time() - minutes_ago * 60)
    return json.dumps({"_type": "location", "lat": 37.69, "lon": -97.34, "tst": tst, **extra})


def basic(secret: str) -> str:
    return "Basic " + base64.b64encode(f"travel:{secret}".encode()).decode()


def everything_logged(records: list[logging.LogRecord]) -> str:
    """Each record's message, raw arguments, exception text and attached request."""
    formatter = logging.Formatter()
    parts = []
    for record in records:
        parts += [record.getMessage(), repr(record.args), str(record.msg)]
        if record.exc_info:
            parts.append(formatter.formatException(record.exc_info))
        request = getattr(record, "request", None)
        if request is not None:
            parts += [request.get_full_path(), repr(request.META), repr(dict(request.GET))]
    return "\n".join(parts)


@pytest.fixture
def owner(db):
    with as_owner():
        return UserFactory()


def test_no_request_path_logs_the_token(owner, settings, caplog, monkeypatch):
    token, secret = device_token(owner)
    revoked, revoked_secret = device_token(owner, name="old phone")
    with as_owner():
        type(revoked).objects.filter(pk=revoked.pk).update(revoked_at="2026-01-01T00:00:00Z")
    _overland, overland_secret = device_token(owner, kind="overland", name="iphone")
    client = Client(raise_request_exception=False)
    settings.TRACKER_RATE_PER_TOKEN = 6
    caplog.set_level(logging.DEBUG)

    auth = {"Authorization": f"Bearer {secret}"}
    requests = [
        (OWNTRACKS, location(9), auth, 200),
        (OWNTRACKS, location(8), {"Authorization": basic(secret)}, 200),
        (f"{OWNTRACKS}?token={secret}", location(7), {}, 200),
        (f"{OVERLAND}?token={overland_secret}&x=1", '{"locations":[]}', {}, 200),
        (OWNTRACKS, location(6, vel=5000), auth, 200),  # flagged: logged at INFO
        (OWNTRACKS, '{"_type":"location","lat":99}', auth, 400),
        (OWNTRACKS, location(5), {"Authorization": f"Bearer {revoked_secret}"}, 401),
        (f"{OWNTRACKS}?token={revoked_secret}", location(5), {}, 401),
        (f"{OWNTRACKS}?token={secret}&token={secret}", location(5), {}, 401),
        (OWNTRACKS, location(4), auth, 200),
        (OWNTRACKS, location(3), auth, 429),  # seventh use of this token in the window
    ]
    for path, body, headers, expected in requests:
        response = client.post(path, body, content_type="application/json", headers=headers)
        assert response.status_code == expected, (path, response.content)
        assert secret not in response.content.decode()

    # A server error while storing: Django logs it with the request attached.
    def explode(*_args, **_kwargs):
        raise RuntimeError("storage failed")

    monkeypatch.setattr(ingest, "store", explode)
    settings.TRACKER_RATE_PER_TOKEN = 100
    response = client.post(
        f"{OWNTRACKS}?token={secret}", location(2), content_type="application/json"
    )
    assert response.status_code == 500
    assert secret not in response.content.decode()

    logged = everything_logged(caplog.records)
    assert "storage failed" in logged  # the error was logged...
    for value in (secret, revoked_secret, overland_secret, base64.b64encode(secret.encode())):
        assert str(value) not in logged  # ...without any token
    assert token.token_hash not in logged

    # The report Django mails or shows for a 500 (when ADMINS or DEBUG is set) has none either.
    (error,) = [r for r in caplog.records if r.levelno >= logging.ERROR and r.exc_info]
    report = ExceptionReporter(error.request, *error.exc_info).get_traceback_text()
    assert "storage failed" in report
    assert secret not in report


def test_query_tokens_are_removed_from_the_request_and_server_environment(owner):
    _token, secret = device_token(owner, kind="overland")
    raw_uri = f"{OVERLAND}?token={secret}&device=1"
    response = Client().post(
        f"{OVERLAND}?token={secret}&device=1",
        '{"locations":[]}',
        content_type="application/json",
        RAW_URI=raw_uri,  # what gunicorn's access log prints
        REQUEST_URI=raw_uri,
    )
    assert response.status_code == 200
    meta = response.wsgi_request.META
    assert meta["QUERY_STRING"] == "device=1"
    assert meta["RAW_URI"] == meta["REQUEST_URI"] == f"{OVERLAND}?device=1"
    assert secret not in response.wsgi_request.get_full_path()
    assert "token" not in response.wsgi_request.GET


def test_the_token_is_stored_nowhere_in_the_database(owner):
    """Create a token through the API, use it, then search every table for it."""
    client = Client()
    with as_owner():
        client.force_login(owner)
    created = client.post(
        "/api/v1/tracking/tokens",
        {"name": "Synthetic phone", "kind": "owntracks"},
        content_type="application/json",
    )
    assert created.status_code == 201
    secret = created.json()["token"]
    tracker = Client()
    assert tracker.post(OWNTRACKS, location(), content_type="application/json",
                        headers={"Authorization": f"Bearer {secret}"}).status_code == 200  # fmt: skip

    with as_owner(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename <> 'spatial_ref_sys'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        found = []
        for table in tables:
            quoted = connection.ops.quote_name(table)
            cursor.execute(
                f"SELECT count(*) FROM {quoted} t WHERE t::text LIKE %s", [f"%{secret[4:]}%"]
            )
            if cursor.fetchone()[0]:
                found.append(table)
        cursor.execute("SELECT token_hash, token_prefix FROM accounts_devicetoken")
        ((stored_hash, prefix),) = cursor.fetchall()
    assert found == []
    assert stored_hash == hashlib.sha256(secret.encode()).hexdigest()
    assert secret.startswith(prefix) and len(prefix) == 8


# --- Layer 2: redaction of whatever reaches a handler -------------------------------------------

SAMPLE = "trk_" + "Ab3_-" * 8 + "xyz"


@pytest.mark.parametrize(
    "line",
    [
        f'"POST /api/v1/ingest/overland?token={SAMPLE} HTTP/1.1" 200 15',
        '"POST /api/v1/ingest/overland?device=1&token=whatever HTTP/1.1" 200 15',
        f"token was {SAMPLE}",
        f"{{'HTTP_AUTHORIZATION': 'Bearer {SAMPLE}'}}",
        "Authorization: Basic dHJhdmVsOnRya19zZWNyZXQ=",
        f"password={SAMPLE}",
    ],
)
def test_redact_removes_tokens_and_credentials(line):
    cleaned = redact(line)
    assert SAMPLE not in cleaned
    assert "whatever" not in cleaned
    assert "dHJhdmVsOnRya19zZWNyZXQ=" not in cleaned
    assert "[redacted]" in cleaned


def test_configured_handlers_redact_and_django_mails_nothing():
    root_formatters = [type(h.formatter) for h in logging.getLogger().handlers if h.formatter]
    assert RedactingFormatter in root_formatters
    server = logging.getLogger("django.server")
    assert server.handlers and all(
        isinstance(h.formatter, RedactingServerFormatter) for h in server.handlers
    )
    # Django's default `mail_admins` handler would send request details by email.
    assert logging.getLogger("django").handlers == []


def test_formatter_redacts_arguments_and_tracebacks():
    formatter = RedactingFormatter("%(message)s")
    try:
        raise ValueError(f"bad {SAMPLE}")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "x", logging.ERROR, __file__, 1, "got %s", (SAMPLE,), sys.exc_info()
        )
    assert SAMPLE not in formatter.format(record)
