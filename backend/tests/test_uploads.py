"""Milestone 2.1: resumable chunked uploads and the immutable raw-file archive."""

import hashlib
import io
import json
import stat

import pytest
import zstandard
from django.db import connection

from tests.factories import UserFactory
from tests.helpers import as_owner
from travel.accounts.models import Role
from travel.history import importers, rawstore, uploads
from travel.history.models import ImportBatch, RawFile, UploadSession

pytestmark = pytest.mark.django_db

CHUNK = 1024  # small chunks for tests


@pytest.fixture(autouse=True)
def bulk(settings, tmp_path):
    settings.BULK_DIR = tmp_path
    settings.TRAVEL_UPLOAD_CHUNK_BYTES = CHUNK
    settings.TRAVEL_UPLOAD_MAX_BYTES = 50_000
    settings.TRAVEL_USER_QUOTA_BYTES = 100_000
    return tmp_path


@pytest.fixture
def member(client):
    with as_owner():
        user = UserFactory()
        client.force_login(user)
    client.user = user
    return client


def payload(size=2500, seed=b"SYNTHETIC upload "):
    return (seed * (size // len(seed) + 1))[:size]


def start(client, data, kind="google_timeline", name="Timeline.json"):
    response = client.post(
        "/api/v1/uploads",
        {"filename": name, "size": len(data), "kind": kind},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    return response.json()


def send(client, upload_id, index, chunk, sha=None):
    return client.put(
        f"/api/v1/uploads/{upload_id}/chunks/{index}",
        chunk,
        content_type="application/octet-stream",
        HTTP_X_CHUNK_SHA256=sha or hashlib.sha256(chunk).hexdigest(),
    )


def upload_all(client, data, **kwargs):
    info = start(client, data, **kwargs)
    for index, offset in enumerate(range(0, len(data), CHUNK)):
        assert send(client, info["id"], index, data[offset : offset + CHUNK]).status_code == 200
    return info


def test_full_upload_queues_a_worker_job(member):
    data = payload()
    info = upload_all(member, data)
    assert info["chunk_size"] == CHUNK
    response = member.post(f"/api/v1/uploads/{info['id']}/complete")
    assert response.status_code == 202
    batch_id = response.json()["id"]
    with connection.cursor() as cursor:
        cursor.execute("SELECT task_name, args FROM procrastinate_jobs")
        jobs = cursor.fetchall()
    jobs = [(name, json.loads(args) if isinstance(args, str) else args) for name, args in jobs]
    assert [(name, args["upload_id"]) for name, args in jobs] == [
        ("history.process_upload", info["id"])
    ]
    assert member.get(f"/api/v1/imports/{batch_id}").json()["status"] == "queued"


@pytest.fixture
def fake_importer(monkeypatch):
    seen = []

    def importer(batch):
        seen.append(batch.raw_file_id)
        return {"segments_new": 0}

    monkeypatch.setitem(importers._REGISTRY, "google_timeline", importer)
    return seen


def test_worker_archives_the_exact_bytes_read_only(member, bulk, fake_importer):
    data = payload()
    info = upload_all(member, data)
    member.post(f"/api/v1/uploads/{info['id']}/complete")
    batch = uploads.process_upload(info["id"], member.user.pk)
    assert batch.status == ImportBatch.Status.DONE
    assert batch.summary == {"segments_new": 0}
    assert fake_importer == [batch.raw_file_id]
    with as_owner():
        raw = RawFile.objects.get(owner=member.user)
    assert raw.sha256 == hashlib.sha256(data).hexdigest()
    assert raw.size_bytes == len(data)
    stored = bulk / "raw" / raw.storage_path
    assert stat.S_IMODE(stored.stat().st_mode) == 0o440
    with stored.open("rb") as handle:
        assert zstandard.ZstdDecompressor().stream_reader(handle).read() == data
    with as_owner(), rawstore.open_original(raw) as reader:
        assert reader.read() == data
    assert not uploads.part_path(UploadSession(pk=info["id"], owner_id=member.user.pk)).exists()


def test_formats_without_an_importer_are_archived_and_marked(member, monkeypatch):
    monkeypatch.delitem(importers._REGISTRY, "tripit", raising=False)
    info = upload_all(member, payload(), kind="tripit", name="trips.ics")
    member.post(f"/api/v1/uploads/{info['id']}/complete")
    batch = uploads.process_upload(info["id"], member.user.pk)
    assert batch.status == ImportBatch.Status.UNSUPPORTED
    with as_owner():
        assert RawFile.objects.filter(owner=member.user).count() == 1


def test_identical_reupload_is_detected_by_hash(member, fake_importer):
    data = payload()
    first = upload_all(member, data)
    member.post(f"/api/v1/uploads/{first['id']}/complete")
    uploads.process_upload(first["id"], member.user.pk)
    second = upload_all(member, data, name="renamed.json")
    member.post(f"/api/v1/uploads/{second['id']}/complete")
    batch = uploads.process_upload(second["id"], member.user.pk)
    assert batch.status == ImportBatch.Status.DUPLICATE
    with as_owner():
        assert RawFile.objects.count() == 1


def test_retrying_the_last_chunk_is_harmless(member):
    data = payload()
    info = start(member, data)
    first = data[:CHUNK]
    assert send(member, info["id"], 0, first).status_code == 200
    again = send(member, info["id"], 0, first)
    assert again.status_code == 200
    assert again.json()["next_index"] == 1
    assert again.json()["received_bytes"] == CHUNK


def test_chunks_must_arrive_in_order(member):
    data = payload()
    info = start(member, data)
    response = send(member, info["id"], 1, data[CHUNK : 2 * CHUNK])
    assert response.status_code == 409
    assert member.get(f"/api/v1/uploads/{info['id']}").json()["next_index"] == 0


def test_corrupted_chunks_are_rejected(member):
    data = payload()
    info = start(member, data)
    assert send(member, info["id"], 0, data[:CHUNK], sha="0" * 64).status_code == 422
    assert member.get(f"/api/v1/uploads/{info['id']}").json()["received_bytes"] == 0


def test_short_chunks_only_at_the_end(member):
    data = payload()
    info = start(member, data)
    assert send(member, info["id"], 0, data[:100]).status_code == 422


def test_cannot_send_more_than_declared(member):
    data = payload(1500)
    info = start(member, data)
    assert send(member, info["id"], 0, data[:CHUNK]).status_code == 200
    assert send(member, info["id"], 1, payload(CHUNK)).status_code == 413


def test_complete_requires_every_byte(member):
    data = payload()
    info = start(member, data)
    send(member, info["id"], 0, data[:CHUNK])
    assert member.post(f"/api/v1/uploads/{info['id']}/complete").status_code == 409


def test_size_limit_and_quota(member, settings):
    response = member.post(
        "/api/v1/uploads",
        {"filename": "huge.json", "size": 60_000, "kind": "google_timeline"},
        content_type="application/json",
    )
    assert response.status_code == 413
    settings.TRAVEL_USER_QUOTA_BYTES = 3000
    start(member, payload(2000))
    response = member.post(
        "/api/v1/uploads",
        {"filename": "more.json", "size": 2000, "kind": "google_timeline"},
        content_type="application/json",
    )
    assert response.status_code == 413


def test_uploads_are_private_to_their_owner(member, client):
    info = start(member, payload())
    from django.test import Client

    other = Client()
    with as_owner():
        other.force_login(UserFactory())
    assert other.get(f"/api/v1/uploads/{info['id']}").status_code == 404
    assert send(other, info["id"], 0, payload(CHUNK)).status_code == 404


def test_viewers_cannot_upload(client):
    with as_owner():
        client.force_login(UserFactory(role=Role.VIEWER))
    response = client.post(
        "/api/v1/uploads",
        {"filename": "x.json", "size": 10, "kind": "google_timeline"},
        content_type="application/json",
    )
    assert response.status_code == 403


def test_abort_removes_the_partial_file(member):
    data = payload()
    info = start(member, data)
    send(member, info["id"], 0, data[:CHUNK])
    with as_owner():
        session = UploadSession.objects.get(pk=info["id"])
    assert uploads.part_path(session).exists()
    assert member.delete(f"/api/v1/uploads/{info['id']}").status_code == 204
    assert not uploads.part_path(session).exists()


def test_receive_chunk_rewrites_from_the_recorded_offset(member):
    """Bytes left by a crash between writing and recording a chunk are overwritten."""
    data = payload()
    info = start(member, data)
    with as_owner():
        session = UploadSession.objects.get(pk=info["id"])
    uploads.part_path(session).write_bytes(b"garbage from an interrupted attempt")
    with as_owner():
        uploads.receive_chunk(
            session, 0, io.BytesIO(data[:CHUNK]), CHUNK, hashlib.sha256(data[:CHUNK]).hexdigest()
        )
    assert uploads.part_path(session).read_bytes() == data[:CHUNK]
