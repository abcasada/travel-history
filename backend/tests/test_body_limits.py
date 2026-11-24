"""Request body limits per endpoint (F-2, D-107; travel.core.bodylimit).

Before, `DATA_UPLOAD_MAX_MEMORY_SIZE` was 40 MiB for every endpoint, and CsrfViewMiddleware
parsed an anonymous form POST to `/` before any view or rate limit as soon as it carried a
well-formed `csrftoken` cookie. Now the default limit is 2.5 MiB, refused (413) before anything
reads the body, and only the upload-chunk and tracker endpoints accept more."""

import hashlib
import json

import pytest
from django.middleware.csrf import _get_new_csrf_string
from django.test import Client

from tests.factories import UserFactory, device_token
from tests.helpers import as_owner
from travel.core import bodylimit

pytestmark = pytest.mark.django_db(databases=["default", "ratelimit"])

MIB = 1024 * 1024
DEFAULT = 2621440  # Django's own default, settings.DATA_UPLOAD_MAX_MEMORY_SIZE


def test_the_default_limit_is_djangos_own(settings):
    assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE == DEFAULT
    assert settings.TRAVEL_UPLOAD_CHUNK_BYTES == 32 * MIB
    assert settings.TRACKER_MAX_BODY_BYTES == 5 * MIB


def anonymous_form_client() -> Client:
    """What the 41a probe sent: any well-formed csrftoken cookie and a matching Referer."""
    client = Client(enforce_csrf_checks=True)
    client.cookies["csrftoken"] = _get_new_csrf_string()
    return client


def test_an_oversized_anonymous_form_post_is_refused_before_parsing(settings):
    client = anonymous_form_client()
    body = "a=" + "x" * (DEFAULT + 1)
    response = client.generic(
        "POST", "/", body, content_type="application/x-www-form-urlencoded",
        headers={"Referer": "http://testserver/"},
    )  # fmt: skip
    assert response.status_code == 413
    assert "Set-Cookie" not in response
    # The response still carries the security headers (the middleware sits inside them).
    assert response["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]


def test_an_oversized_multipart_file_part_is_refused_too():
    """DATA_UPLOAD_MAX_MEMORY_SIZE excludes file parts: Django would stream them to /tmp."""
    client = anonymous_form_client()
    boundary = "SYNTHETICBOUNDARY"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="f"; filename="a.bin"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + b"x" * (3 * MIB)
        + f"\r\n--{boundary}--\r\n".encode()
    )
    response = client.generic(
        "POST", "/", body, content_type=f"multipart/form-data; boundary={boundary}",
        headers={"Referer": "http://testserver/"},
    )  # fmt: skip
    assert response.status_code == 413


def test_a_declared_length_alone_is_enough_to_refuse():
    """The body is never read: a client announcing 40 MB gets 413 at once."""
    response = Client().generic(
        "POST", "/api/v1/trips", b"{}", content_type="application/json",
        CONTENT_LENGTH=str(40 * MIB),
    )  # fmt: skip
    assert response.status_code == 413
    assert response.json() == {"detail": f"the request body is larger than {DEFAULT} bytes"}


def test_small_bodies_are_unaffected():
    response = Client().post("/api/v1/trips", {}, content_type="application/json")
    assert response.status_code == 401  # reached the login wall


@pytest.mark.parametrize(
    ("method", "path", "limit"),
    [
        ("PUT", "/api/v1/uploads/7c3e6f8a-0000-4000-8000-000000000000/chunks/3", "chunk"),
        ("POST", "/api/v1/uploads/7c3e6f8a-0000-4000-8000-000000000000/chunks/3", "default"),
        ("PUT", "/api/v1/uploads/x/chunks/3/extra", "default"),
        ("POST", "/api/v1/ingest/owntracks", "tracker"),
        ("POST", "/api/v1/ingest/overland/", "tracker"),
        ("POST", "/api/v1/trips", "default"),
        ("POST", "/", "default"),
        ("POST", "/auth/logout", "default"),
    ],
)
def test_each_endpoint_has_its_limit(settings, rf, method, path, limit):
    expected = {
        "chunk": settings.TRAVEL_UPLOAD_CHUNK_BYTES,
        "tracker": settings.TRACKER_MAX_BODY_BYTES,
        "default": settings.DATA_UPLOAD_MAX_MEMORY_SIZE,
    }[limit]
    assert bodylimit.body_limit(rf.generic(method, path)) == expected


def test_the_chunk_route_matches_the_limit_pattern():
    from django.urls import resolve

    path = "/api/v1/uploads/7c3e6f8a-0000-4000-8000-000000000000/chunks/3"
    assert bodylimit.UPLOAD_CHUNK_PATH.fullmatch(path)
    assert resolve(path).url_name == "put_chunk"


# --- The endpoints with their own limits still take their large bodies ------------------------


@pytest.fixture
def member(client, settings, tmp_path):
    settings.BULK_DIR = tmp_path
    with as_owner():
        user = UserFactory()
        client.force_login(user)
    return client


def upload_one_chunk(client, data: bytes):
    response = client.post(
        "/api/v1/uploads",
        {"filename": "Timeline.json", "size": len(data), "kind": "google_timeline"},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    upload = response.json()
    return client.put(
        f"/api/v1/uploads/{upload['id']}/chunks/0",
        data,
        content_type="application/octet-stream",
        HTTP_X_CHUNK_SHA256=hashlib.sha256(data).hexdigest(),
    )


def test_an_upload_chunk_above_the_default_limit_is_accepted(member):
    data = b"SYNTHETIC " * (3 * MIB // 10)  # one short (last) chunk of 3 MiB
    response = upload_one_chunk(member, data)
    assert response.status_code == 200, response.content
    assert response.json()["received_bytes"] == len(data)


@pytest.mark.slow
def test_a_full_32_mib_chunk_still_uploads(member, settings):
    size = settings.TRAVEL_UPLOAD_CHUNK_BYTES
    data = (b"SYNTHETIC " * (size // 10 + 1))[:size]
    assert len(data) == settings.TRAVEL_UPLOAD_CHUNK_BYTES
    response = upload_one_chunk(member, data)
    assert response.status_code == 200, response.content
    oversized = Client()
    oversized.cookies = member.cookies
    response = oversized.generic(
        "PUT", "/api/v1/uploads/7c3e6f8a-0000-4000-8000-000000000000/chunks/1", b"",
        content_type="application/octet-stream",
        CONTENT_LENGTH=str(settings.TRAVEL_UPLOAD_CHUNK_BYTES + 1),
    )  # fmt: skip
    assert response.status_code == 413


def test_a_tracker_body_above_the_default_limit_is_accepted(client):
    with as_owner():
        user = UserFactory()
    _token, secret = device_token(user)
    # Valid JSON: whitespace after the document. Over 2.5 MiB, under the tracker's 5 MiB.
    body = json.dumps({"_type": "lwt", "tst": 1700000000}) + " " * (3 * MIB)
    response = client.generic(
        "POST", "/api/v1/ingest/owntracks", body, content_type="application/json",
        headers={"Authorization": f"Bearer {secret}"},
    )  # fmt: skip
    assert response.status_code == 200, response.content
    assert response.content == b"[]"
