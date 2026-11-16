"""Device-token management (work-order item 7, matrix §6.3 "Device tokens"): every endpoint
for every actor of the synthetic family, through real requests; then the SQL rules behind
them as `travel_app` (the narrow `ingest` context, the token guard trigger). The per-action
SQL/policy agreement is in test_matrix.py (create_own_token, revoke_alice_token, …).
"""

import base64
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from tests.factories import device_token
from tests.helpers import as_owner
from travel.accounts.models import DeviceToken, User
from travel.core.rls import set_context
from travel.history.models import LocationPoint
from travel.tracking import tokens
from travel.trips.models import Trip

pytestmark = pytest.mark.django_db

ACTORS = ("admin", "alice", "bob", "carol", "victor", "ivan", "anon")
TOKENS = "/api/v1/tracking/tokens"


def as_actor(client, f, actor: str):
    if actor != "anon":
        with as_owner():
            client.force_login(getattr(f, actor))
    return client


def post(client, path, body=None):
    return client.post(path, json.dumps(body or {}), content_type="application/json")


@pytest.mark.parametrize(
    ("actor", "status"), zip(ACTORS, (200, 200, 200, 200, 200, 401, 401), strict=True)
)
def test_list_shows_only_own_tokens_and_never_the_secret(client, scenario, actor, status):
    f = scenario
    response = as_actor(client, f, actor).get(TOKENS)
    assert response.status_code == status
    if status != 200:
        return
    ids = {row["id"] for row in response.json()}
    mine = actor == "alice"
    assert (f.alice_token.pk in ids) is mine
    assert (f.alice_revoked_token.pk in ids) is mine
    for row in response.json():
        assert set(row) == {
            "id", "name", "kind", "token_prefix", "created_at", "last_used_at", "revoked_at",
            "points_received",
        }  # fmt: skip
    assert f.alice_token.token_hash not in response.content.decode()


@pytest.mark.parametrize(
    ("actor", "status"), zip(ACTORS, (201, 201, 201, 201, 403, 401, 401), strict=True)
)
def test_create_needs_a_role_that_has_raw_history(client, scenario, actor, status):
    f = scenario
    response = post(as_actor(client, f, actor), TOKENS, {"name": "Phone", "kind": "owntracks"})
    assert response.status_code == status
    if status != 201:
        return
    body = response.json()
    secret = body["token"]
    assert tokens.is_well_formed(secret)
    assert body["device"]["token_prefix"] == secret[:8]
    with as_owner():
        row = DeviceToken.objects.get(pk=body["device"]["id"])
    assert row.user_id == getattr(f, actor).pk
    assert row.token_hash == tokens.hash_token(secret)
    # Shown once: the list never includes it.
    assert secret not in client.get(TOKENS).content.decode()


@pytest.mark.parametrize(
    ("actor", "status"), zip(ACTORS, (404, 200, 404, 404, 404, 401, 401), strict=True)
)
def test_only_the_owner_revokes_a_token(client, scenario, actor, status):
    f = scenario
    response = post(as_actor(client, f, actor), f"{TOKENS}/{f.alice_token.pk}/revoke")
    assert response.status_code == status
    with as_owner():
        f.alice_token.refresh_from_db()
    assert (f.alice_token.revoked_at is not None) is (status == 200)


def test_revoking_is_final_and_idempotent(client, scenario):
    f = scenario
    as_actor(client, f, "alice")
    first = post(client, f"{TOKENS}/{f.alice_token.pk}/revoke").json()["revoked_at"]
    again = post(client, f"{TOKENS}/{f.alice_token.pk}/revoke").json()["revoked_at"]
    assert first == again is not None


def test_a_viewer_lists_but_cannot_revoke_a_leftover_token(client, scenario):
    f = scenario
    token, _secret = device_token(f.victor)
    as_actor(client, f, "victor")
    assert [row["id"] for row in client.get(TOKENS).json()] == [token.pk]
    assert post(client, f"{TOKENS}/{token.pk}/revoke").status_code == 403


def test_active_tokens_are_capped(client, scenario, settings):
    f = scenario
    settings.TRACKER_MAX_TOKENS_PER_USER = 1  # alice already has one live token
    as_actor(client, f, "alice")
    assert post(client, TOKENS, {"name": "x", "kind": "overland"}).status_code == 409


@pytest.mark.parametrize("body", [{"name": "", "kind": "owntracks"}, {"name": "x", "kind": "x"},
                                  {"name": "x" * 101, "kind": "owntracks"}])  # fmt: skip
def test_create_validates_its_input(client, scenario, body):
    as_actor(client, scenario, "alice")
    assert post(client, TOKENS, body).status_code == 422


# --- Setup links ---------------------------------------------------------------------------


def _create(client, f, kind: str, settings) -> dict:
    settings.TRACKER_BASE_URL = "https://tracker.example.test"
    as_actor(client, f, "alice")
    response = post(client, TOKENS, {"name": "Synthetic Phone", "kind": kind})
    assert response.status_code == 201
    return response.json()


def _inline_json(value: str) -> dict:
    return json.loads(base64.b64decode(value))


def test_owntracks_setup_link_configures_http_mode(client, scenario, settings):
    body = _create(client, scenario, "owntracks", settings)
    setup = body["setup"]
    assert setup["endpoint"] == "https://tracker.example.test/api/v1/ingest/owntracks"
    link = urlsplit(setup["link"])
    assert (link.scheme, link.path) == ("owntracks", "/config")
    config = _inline_json(parse_qs(link.query)["inline"][0])
    assert config["_type"] == "configuration" and config["mode"] == 3 and config["auth"] is True
    assert config["url"] == setup["endpoint"] and config["password"] == body["token"]
    assert config["deviceId"] == "synthetic-phone" and config["tid"] == "SY"
    assert setup["link_qr"].startswith("data:image/svg+xml;base64,")
    assert setup["token_qr"].startswith("data:image/svg+xml;base64,")


def test_overland_and_colota_setup_links(client, scenario, settings):
    overland = _create(client, scenario, "overland", settings)
    query = parse_qs(urlsplit(overland["setup"]["link"]).query)
    assert overland["setup"]["link"].startswith("overland://setup?")
    assert query["url"] == ["https://tracker.example.test/api/v1/ingest/overland"]
    assert query["token"] == [overland["token"]]

    colota = _create(client, scenario, "colota", settings)
    link = urlsplit(colota["setup"]["link"])
    assert (link.scheme, link.netloc) == ("colota", "setup")
    config = _inline_json(parse_qs(link.query)["config"][0])
    assert config["endpoint"] == "https://tracker.example.test/api/v1/ingest/owntracks"
    assert config["apiTemplate"] == "owntracks"
    assert config["auth"] == {"type": "bearer", "bearerToken": colota["token"]}


def test_gpslogger_gets_fields_to_copy_not_a_hosted_profile(client, scenario, settings):
    body = _create(client, scenario, "gpslogger", settings)
    setup = body["setup"]
    assert setup["link"] is None and setup["link_qr"] is None
    assert setup["auth"] == "basic" and setup["username"] == "travel"
    assert "%TIMESTAMP" in setup["body_template"]


def test_without_a_configured_base_url_links_use_the_request_address(client, scenario, settings):
    settings.TRACKER_BASE_URL = ""
    as_actor(client, scenario, "alice")
    body = post(client, TOKENS, {"name": "p", "kind": "overland"}).json()
    assert body["setup"]["endpoint"] == "http://testserver/api/v1/ingest/overland"


# --- SQL rules (as travel_app) ----------------------------------------------------------------


def _denied(fn) -> bool:
    try:
        with transaction.atomic():
            fn()
    except DatabaseError:
        return True
    return False


def test_ingest_context_reads_tokens_and_nothing_else(scenario):
    f = scenario
    set_context(None, "ingest")
    assert DeviceToken.objects.filter(token_hash=f.alice_token.token_hash).exists()
    assert not LocationPoint.objects.exists()
    assert not User.objects.exists()
    assert not Trip.objects.exists()
    assert DeviceToken.objects.filter(pk=f.alice_token.pk).update(name="x") == 0
    assert _denied(
        lambda: DeviceToken.objects.create(
            user=f.alice, name="n", kind="owntracks", token_prefix="trk_x", token_hash="d" * 64
        )
    )
    assert _denied(
        lambda: LocationPoint.objects.create(
            owner=f.alice, ts=f.now, geom=f.alice_point.geom, source="owntracks",
            device=f.alice_token,
        )
    )  # fmt: skip


def test_token_identity_is_fixed_and_revocation_final(scenario):
    f = scenario
    set_context(f.alice.pk)
    alice_tokens = DeviceToken.objects.filter(pk=f.alice_token.pk)
    assert alice_tokens.update(name="renamed") == 1
    assert _denied(lambda: alice_tokens.update(token_hash="e" * 64))
    assert _denied(lambda: alice_tokens.update(kind="overland"))
    assert _denied(lambda: alice_tokens.update(token_prefix="trk_zzz"))
    assert _denied(lambda: alice_tokens.update(user_id=f.bob.pk))
    revoked = DeviceToken.objects.filter(pk=f.alice_revoked_token.pk)
    assert _denied(lambda: revoked.update(revoked_at=None))
    assert _denied(lambda: revoked.update(revoked_at=timezone.now()))


def test_only_a_hash_can_be_stored(scenario):
    f = scenario
    set_context(f.alice.pk)
    secret = tokens.generate().secret
    assert _denied(
        lambda: DeviceToken.objects.create(
            user=f.alice, name="n", kind="owntracks", token_prefix="trk_x", token_hash=secret
        )
    )


def test_a_token_cannot_write_into_another_users_history(scenario):
    """Even code that got the owner wrong: as bob, neither bob's own history with alice's
    token, nor alice's history, accepts the point."""
    f = scenario
    set_context(f.bob.pk)

    def point(owner, device):
        return lambda: LocationPoint.objects.create(
            owner=owner, ts=f.now, geom=f.alice_point.geom, source="owntracks", device=device
        )

    assert _denied(point(f.bob, f.alice_token))
    assert _denied(point(f.alice, f.alice_token))
    assert not _denied(point(f.bob, None))
    set_context(f.alice.pk)
    assert not _denied(point(f.alice, f.alice_token))
    assert _denied(point(f.alice, f.alice_revoked_token))
