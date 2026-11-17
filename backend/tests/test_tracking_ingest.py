"""Tracker ingestion endpoints (work-order item 7, PLAN.md §9.1), through real requests:
middleware, rate limiter, token lookup, row-level security as `travel_app`.

Covers what must hold before the endpoints are exposed (item 8): write-only hashed tokens,
revocation, the rate limiter on every path, the size cap, strict validation, plausibility
flags, responses without data, writes only into the token owner's history.
"""

import base64
import datetime as dt
import json
import time

import pytest
from django.db import connections
from django.test import Client

from tests.factories import DENVER, TOPEKA, WICHITA, UserFactory, device_token
from tests.helpers import as_owner, rollup_mismatches
from travel.accounts.models import DeviceToken, Role
from travel.history.models import LocationPoint
from travel.tracking import tokens

pytestmark = pytest.mark.django_db(databases=["default", "ratelimit"])

OWNTRACKS = "/api/v1/ingest/owntracks"
OVERLAND = "/api/v1/ingest/overland"


@pytest.fixture
def alice(db):
    with as_owner():
        return UserFactory(display_name="Alice")


@pytest.fixture
def bob(db):
    with as_owner():
        return UserFactory(display_name="Bob")


def ago(minutes: float) -> int:
    return int(time.time() - minutes * 60)


def iso(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, tz=dt.UTC).isoformat().replace("+00:00", "Z")


def ot_location(point=WICHITA, minutes_ago: float = 5, **extra) -> dict:
    return {"_type": "location", "lat": point.y, "lon": point.x, "tst": ago(minutes_ago), **extra}


def ol_feature(point=WICHITA, minutes_ago: float = 5, **properties) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [point.x, point.y]},
        "properties": {"timestamp": iso(ago(minutes_ago)), **properties},
    }


def post(client, path, body, *, secret=None, how="bearer", raw=False, **extra):
    headers = {}
    if secret and how == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif secret and how == "basic":
        credentials = base64.b64encode(f"travel:{secret}".encode()).decode()
        headers["Authorization"] = f"Basic {credentials}"
    elif secret and how == "query":
        path = f"{path}?token={secret}"
    data = body if raw else json.dumps(body)
    return client.generic(
        "POST", path, data, content_type=extra.pop("content_type", "application/json"),
        headers=headers, **extra,
    )  # fmt: skip


def points(token=None, owner=None):
    with as_owner():
        rows = LocationPoint.objects.all()
        if token is not None:
            rows = rows.filter(device=token)
        if owner is not None:
            rows = rows.filter(owner=owner)
        return list(rows.order_by("ts"))


# --- Happy paths: exact responses, stored fields ----------------------------------------------


@pytest.mark.parametrize("how", ["bearer", "basic", "query"])
def test_owntracks_stores_one_location_and_answers_an_empty_list(client, alice, how):
    token, secret = device_token(alice)
    body = ot_location(acc=12, alt=300, vel=36, cog=90, batt=80, tid="ph", conn="w", t="u")
    response = post(client, OWNTRACKS, body, secret=secret, how=how)
    assert response.status_code == 200
    assert response.content == b"[]"
    assert response["Content-Type"] == "application/json"
    assert response["Cache-Control"] == "no-store"
    (point,) = points(token)
    assert point.owner_id == alice.pk and point.source == "owntracks"
    assert point.accuracy_m == 12 and point.altitude_m == 300 and point.course_deg == 90
    assert point.speed_mps == pytest.approx(10.0)  # 36 km/h
    assert point.battery_pct == 80
    assert point.extra is None  # no flags; nothing else from the message is kept
    assert (point.geom.x, point.geom.y) == pytest.approx((WICHITA.x, WICHITA.y))


def test_overland_stores_a_batch_and_answers_exactly_result_ok(client, alice):
    token, secret = device_token(alice, kind="overland")
    body = {
        "locations": [
            ol_feature(WICHITA, 10, speed=5, horizontal_accuracy=8, battery_level=0.5,
                       motion=["walking"], wifi="SyntheticNet", device_id="x"),
            ol_feature(WICHITA, 9, speed=-1, course=-1, battery_level=-1),
        ],
        "current": ol_feature(WICHITA, 1),
    }  # fmt: skip
    response = post(client, OVERLAND, body, secret=secret)
    assert response.status_code == 200
    assert response.content == b'{"result":"ok"}'
    first, second = points(token)
    assert first.source == "overland" and first.speed_mps == 5 and first.battery_pct == 50
    assert first.accuracy_m == 8
    assert second.speed_mps is None and second.course_deg is None and second.battery_pct is None
    with as_owner():
        token.refresh_from_db()
    assert token.points_received == 2 and token.last_used_at is not None


def test_overland_query_token_and_trailing_slash(client, alice):
    token, secret = device_token(alice, kind="overland")
    response = post(client, OVERLAND + "/", {"locations": [ol_feature()]}, secret=secret,
                    how="query")  # fmt: skip
    assert response.status_code == 200
    assert len(points(token)) == 1


def test_source_follows_the_token_kind(client, alice):
    for kind, source in [("gpslogger", "gpslogger"), ("colota", "colota"), ("generic", "other")]:
        token, secret = device_token(alice, kind=kind, name=kind)
        assert post(client, OWNTRACKS, ot_location(), secret=secret).status_code == 200
        assert [p.source for p in points(token)] == [source]


def test_gpslogger_body_template_is_accepted(client, alice):
    token, secret = device_token(alice, kind="gpslogger")
    # What GPSLogger sends with the documented template (docs/tracking/gpslogger.md).
    body = (
        '{"_type":"location","lat":37.6922,"lon":-97.3375,"tst":TST,"acc":4.5,"alt":402.0,'
        '"vel":0.0,"batt":77,"tid":"gl"}'
    ).replace("TST", str(ago(3)))
    assert post(client, OWNTRACKS, body, secret=secret, how="basic", raw=True).status_code == 200
    assert len(points(token)) == 1


def test_colota_owntracks_template_is_accepted(client, alice):
    token, secret = device_token(alice, kind="colota")
    body = ot_location(tid="AA", acc=5, alt=100, vel=3, batt=50, bs=1, cog=180)
    assert post(client, OWNTRACKS, body, secret=secret).status_code == 200
    assert len(points(token)) == 1


def test_duplicates_are_dropped_quietly(client, alice):
    token, secret = device_token(alice)
    body = ot_location()
    for _ in range(3):
        assert post(client, OWNTRACKS, body, secret=secret).content == b"[]"
    assert len(points(token)) == 1
    with as_owner():
        token.refresh_from_db()
    assert token.points_received == 1
    assert rollup_mismatches() == []


@pytest.mark.parametrize("kind", ["lwt", "card", "cmd", "transition", "waypoint", "status"])
def test_other_owntracks_messages_are_ignored(client, alice, kind):
    token, secret = device_token(alice)
    body = {"_type": kind, "tst": ago(1), "lat": 1.0, "lon": 1.0, "anything": "goes"}
    response = post(client, OWNTRACKS, body, secret=secret)
    assert response.status_code == 200 and response.content == b"[]"
    assert points(token) == []


def test_empty_owntracks_body_is_ignored_but_needs_a_token(client, alice):
    _token, secret = device_token(alice)
    assert post(client, OWNTRACKS, "", secret=secret, raw=True).content == b"[]"
    assert post(client, OWNTRACKS, "", raw=True).status_code == 401


def test_overland_trip_records_are_ignored(client, alice):
    token, secret = device_token(alice, kind="overland")
    trip = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"type": "trip", "mode": "car", "steps": 0}}  # fmt: skip
    body = {"locations": [trip, ol_feature()], "trip": {"mode": "car", "distance": 10}}
    assert post(client, OVERLAND, body, secret=secret).status_code == 200
    assert len(points(token)) == 1


def test_points_outside_the_time_window_are_counted_not_stored(client, alice, caplog):
    token, secret = device_token(alice, kind="overland")
    old = ol_feature()
    old["properties"]["timestamp"] = "1999-12-31T23:59:59Z"
    future = ol_feature(minutes_ago=-60 * 25)
    body = {"locations": [old, future, ol_feature()]}
    with caplog.at_level("INFO", logger="travel.tracking"):
        assert post(client, OVERLAND, body, secret=secret).status_code == 200
    assert len(points(token)) == 1
    assert "out-of-window 2" in caplog.text


# --- Tokens: refused, revoked, wrong endpoint, wrong owner --------------------------------------


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer trk_short",
        "Bearer " + "trk_" + "A" * 43,  # well formed, unknown
        "Basic not-base64!",
        "Basic " + base64.b64encode(b"no-colon").decode(),
        "Token abc",
    ],
)
def test_requests_without_a_valid_token_get_401(client, alice, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    response = client.post(OWNTRACKS, json.dumps(ot_location()), content_type="application/json",
                           headers=headers)  # fmt: skip
    assert response.status_code == 401
    assert response.json() == {"detail": "a valid device token is required"}
    assert points() == []


def test_a_revoked_token_writes_nothing(client, alice):
    token, secret = device_token(alice)
    assert post(client, OWNTRACKS, ot_location(minutes_ago=6), secret=secret).status_code == 200
    with as_owner():
        DeviceToken.objects.filter(pk=token.pk).update(revoked_at=dt.datetime.now(dt.UTC))
    response = post(client, OWNTRACKS, ot_location(minutes_ago=5), secret=secret)
    assert response.status_code == 401
    assert len(points(token)) == 1


def test_token_is_bound_to_its_endpoint(client, alice):
    _ot, ot_secret = device_token(alice, kind="owntracks")
    _ol, ol_secret = device_token(alice, kind="overland")
    assert (
        post(client, OVERLAND, {"locations": [ol_feature()]}, secret=ot_secret).status_code == 401
    )
    assert post(client, OWNTRACKS, ot_location(), secret=ol_secret).status_code == 401


def test_tokens_of_viewers_and_deactivated_accounts_write_nothing(client, alice):
    with as_owner():
        viewer = UserFactory(role=Role.VIEWER)
        gone = UserFactory(is_active=False)
    for user in (viewer, gone):
        _token, secret = device_token(user)
        assert post(client, OWNTRACKS, ot_location(), secret=secret).status_code == 401
    assert points() == []


def test_a_token_writes_only_into_its_owners_history(client, alice, bob):
    """Nothing in a payload can name another account: OwnTracks topic/tid and Overland's
    device ids are ignored; the owner comes from the token alone."""
    alice_token, alice_secret = device_token(alice)
    bob_token, bob_secret = device_token(bob, kind="overland")
    spoof = ot_location(topic=f"owntracks/{bob.pk}/phone", tid="bo")
    assert post(client, OWNTRACKS, spoof, secret=alice_secret).status_code == 200
    batch = {"locations": [ol_feature(device_id=str(alice.pk), unique_id=str(alice_token.pk))]}
    assert post(client, OVERLAND, batch, secret=bob_secret).status_code == 200
    assert [p.owner_id for p in points(alice_token)] == [alice.pk]
    assert [p.owner_id for p in points(bob_token)] == [bob.pk]
    assert [p.device_id for p in points(owner=alice)] == [alice_token.pk]
    assert [p.device_id for p in points(owner=bob)] == [bob_token.pk]
    assert rollup_mismatches() == []


def test_responses_carry_no_data(client, alice):
    """Even with history stored, the answers are exactly what the apps expect."""
    _token, secret = device_token(alice)
    _ol, ol_secret = device_token(alice, kind="overland")
    for minutes in (30, 20, 10):
        post(client, OWNTRACKS, ot_location(minutes_ago=minutes), secret=secret)
    assert post(client, OWNTRACKS, ot_location(), secret=secret).content == b"[]"
    assert post(client, OVERLAND, {"locations": []}, secret=ol_secret).content == (
        b'{"result":"ok"}'
    )


# --- Size cap and strict validation ----------------------------------------------------------


def test_bodies_over_the_cap_are_refused_before_reading(client, alice, settings):
    token, secret = device_token(alice, kind="overland")
    settings.TRACKER_MAX_BODY_BYTES = 2000
    body = {"locations": [ol_feature(minutes_ago=m) for m in range(1, 30)]}
    response = post(client, OVERLAND, body, secret=secret)
    assert response.status_code == 413
    assert points(token) == []


@pytest.mark.slow
def test_the_default_cap_is_five_megabytes(client, alice):
    _token, secret = device_token(alice)
    padding = "x" * (5 * 1024 * 1024)
    response = post(client, OWNTRACKS, ot_location(image=padding), secret=secret)
    assert response.status_code == 413


def test_oversize_bodies_are_refused_even_without_a_token(client, alice, settings):
    settings.TRACKER_MAX_BODY_BYTES = 100
    response = post(client, OWNTRACKS, ot_location(image="x" * 500))
    assert response.status_code == 413


def test_too_many_points_in_one_request(client, alice, settings):
    token, secret = device_token(alice, kind="overland")
    settings.TRACKER_MAX_POINTS = 3
    body = {"locations": [ol_feature(minutes_ago=m) for m in range(1, 5)]}
    assert post(client, OVERLAND, body, secret=secret).status_code == 413
    assert points(token) == []


def test_chunked_and_compressed_bodies_are_refused(client, alice):
    _token, secret = device_token(alice)
    response = client.generic(
        "POST", OWNTRACKS, json.dumps(ot_location()), content_type="application/json",
        headers={"Authorization": f"Bearer {secret}", "Transfer-Encoding": "chunked"},
    )  # fmt: skip
    assert response.status_code == 411
    response = client.generic(
        "POST", OWNTRACKS, json.dumps(ot_location()), content_type="application/json",
        headers={"Authorization": f"Bearer {secret}", "Content-Encoding": "gzip"},
    )  # fmt: skip
    assert response.status_code == 415


def test_only_json_is_accepted(client, alice):
    _token, secret = device_token(alice)
    response = post(client, OWNTRACKS, "lat=1&lon=2", secret=secret, raw=True,
                    content_type="application/x-www-form-urlencoded")  # fmt: skip
    assert response.status_code == 415


def test_only_post_is_accepted(client, alice):
    _token, secret = device_token(alice)
    response = client.get(OWNTRACKS, headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code == 405 and response["Allow"] == "POST"


MALFORMED_OWNTRACKS = {
    "not json": "{nope",
    "nan": '{"_type":"location","lat":NaN,"lon":1,"tst":%d}',
    "infinity": '{"_type":"location","lat":1,"lon":Infinity,"tst":%d}',
    "huge number": '{"_type":"location","lat":1e999,"lon":1,"tst":%d}',
    "deep nesting": "[" * 100_000 + "]" * 100_000,
    "array": '[{"_type":"location","lat":1,"lon":1,"tst":%d}]',
    "missing type": '{"lat":1,"lon":1,"tst":%d}',
    "unknown type": '{"_type":"selfie","lat":1,"lon":1,"tst":%d}',
    "encrypted": '{"_type":"encrypted","data":"AAAA"}',
    "unknown field": '{"_type":"location","lat":1,"lon":1,"tst":%d,"altitude_feet":3}',
    "lat out of range": '{"_type":"location","lat":91,"lon":1,"tst":%d}',
    "lon out of range": '{"_type":"location","lat":1,"lon":-181,"tst":%d}',
    "battery out of range": '{"_type":"location","lat":1,"lon":1,"tst":%d,"batt":101}',
    "negative accuracy": '{"_type":"location","lat":1,"lon":1,"tst":%d,"acc":-5}',
    "string number": '{"_type":"location","lat":"1.5","lon":1,"tst":%d}',
    "boolean number": '{"_type":"location","lat":true,"lon":1,"tst":%d}',
    "float time": '{"_type":"location","lat":1,"lon":1,"tst":%d.5}',
    "missing time": '{"_type":"location","lat":1,"lon":1}',
    "long text": '{"_type":"location","lat":1,"lon":1,"tst":%d,"tid":"' + "x" * 100 + '"}',
}


@pytest.mark.parametrize("name", MALFORMED_OWNTRACKS)
def test_malformed_owntracks_payloads_are_rejected(client, alice, name):
    token, secret = device_token(alice)
    template = MALFORMED_OWNTRACKS[name]
    body = template % ago(1) if "%d" in template else template
    response = post(client, OWNTRACKS, body, secret=secret, raw=True)
    assert response.status_code == 400, response.content
    assert points(token) == []
    detail = response.json()
    assert set(detail) <= {"detail", "errors"}
    expected = OWNTRACKS_REASONS.get(name)
    if expected:
        assert expected in [detail["detail"], *detail.get("errors", [])], detail


OWNTRACKS_REASONS = {
    "not json": "the body is not valid JSON",
    "nan": "the body is not valid JSON",
    "infinity": "the body is not valid JSON",
    "huge number": "lat: out of range",
    "deep nesting": "the body is not valid JSON",
    "unknown type": "_type: invalid",
    "encrypted": "encrypted OwnTracks payloads are not supported; turn encryption off",
    "unknown field": "altitude_feet: unknown field",
    "lat out of range": "lat: out of range",
    "lon out of range": "lon: out of range",
    "battery out of range": "batt: out of range",
    "negative accuracy": "acc: out of range",
    "string number": "lat: wrong type",
    "boolean number": "lat: wrong type",
    "float time": "tst: wrong type",
    "missing time": "tst: required",
    "long text": "tid: wrong length",
}


def _batch_with(**changes):
    feature = ol_feature()
    for key, value in changes.items():
        target, _, field = key.partition("__")
        if target == "properties":
            feature["properties"][field] = value
        elif target == "geometry":
            feature["geometry"][field] = value
        else:
            feature[key] = value
    return {"locations": [ol_feature(minutes_ago=7), feature]}


MALFORMED_OVERLAND = {
    "no locations": {"points": []},
    "unknown top-level field": {"locations": [], "user": "someone"},
    "unknown property": _batch_with(properties__home="yes"),
    "unknown feature member": _batch_with(id=3),
    "not a point": _batch_with(geometry__type="LineString"),
    "one coordinate": _batch_with(geometry__coordinates=[1.0]),
    "lat out of range": _batch_with(geometry__coordinates=[1.0, 95.0]),
    "lon out of range": _batch_with(geometry__coordinates=[200.0, 1.0]),
    "naive timestamp": _batch_with(properties__timestamp="2026-01-01T10:00:00"),
    "bad timestamp": _batch_with(properties__timestamp="yesterday"),
    "battery level out of range": _batch_with(properties__battery_level=7),
    "speed as text": _batch_with(properties__speed="fast"),
    "locations not a list": {"locations": {"0": 1}},
}


@pytest.mark.parametrize("name", MALFORMED_OVERLAND)
def test_malformed_overland_batches_are_rejected_whole(client, alice, name):
    token, secret = device_token(alice, kind="overland")
    response = post(client, OVERLAND, MALFORMED_OVERLAND[name], secret=secret)
    assert response.status_code == 400, response.content
    assert points(token) == []  # the valid point in the same batch isn't stored either
    detail = response.json()
    expected = OVERLAND_REASONS.get(name)
    if expected:
        assert expected in detail.get("errors", []), detail


OVERLAND_REASONS = {
    "no locations": "locations: required",
    "unknown top-level field": "user: unknown field",
    "unknown property": "locations.1.properties.home: unknown field",
    "unknown feature member": "locations.1.id: unknown field",
    "not a point": "locations.1.geometry.type: invalid",
    "one coordinate": "locations.1.geometry.coordinates: wrong length",
    "lat out of range": "locations.1.geometry.coordinates.1: out of range",
    "lon out of range": "locations.1.geometry.coordinates.0: out of range",
    "naive timestamp": "locations.1.properties.timestamp: needs ISO 8601 with a UTC offset",
    "bad timestamp": "locations.1.properties.timestamp: needs ISO 8601 with a UTC offset",
    "battery level out of range": "locations.1.properties.battery_level: out of range",
    "speed as text": "locations.1.properties.speed: wrong type",
    "locations not a list": "locations: wrong type",
}


def test_validation_errors_name_fields_but_never_echo_values(client, alice):
    _token, secret = device_token(alice, kind="overland")
    body = _batch_with(properties__wifi="SyntheticSecretNet" * 20, properties__extra_key="v@l")
    response = post(client, OVERLAND, body, secret=secret)
    assert response.status_code == 400
    text = response.content.decode()
    assert "SyntheticSecretNet" not in text and "v@l" not in text
    assert any("locations.1.properties.wifi" in e for e in response.json()["errors"])


# --- Rate limits -------------------------------------------------------------------------------


def stored_bucket_keys() -> list[str]:
    with connections["ratelimit"].cursor() as cursor:
        cursor.execute("SELECT key FROM core_ratelimitbucket")
        return [row[0] for row in cursor.fetchall()]


def test_per_token_limit_answers_429_with_retry_after(client, alice, settings):
    settings.TRACKER_RATE_PER_TOKEN = 2
    token, secret = device_token(alice)
    codes = [
        post(client, OWNTRACKS, ot_location(minutes_ago=m), secret=secret).status_code
        for m in (5, 4, 3)
    ]
    assert codes == [200, 200, 429]
    response = post(client, OWNTRACKS, ot_location(minutes_ago=2), secret=secret)
    assert response.status_code == 429 and int(response["Retry-After"]) >= 1
    assert len(points(token)) == 2
    # Other tokens are unaffected.
    _other, other_secret = device_token(alice, name="tablet")
    assert post(client, OWNTRACKS, ot_location(), secret=other_secret).status_code == 200
    # Buckets hold HMACs: neither the token nor its hash is stored.
    keys = " ".join(stored_bucket_keys())
    assert secret not in keys and tokens.hash_token(secret) not in keys


def test_per_address_limit_covers_every_token_and_bad_requests(client, alice, settings):
    settings.TRACKER_RATE_PER_IP = 3
    secrets = [device_token(alice, name=f"phone {i}")[1] for i in range(4)]
    codes = [post(client, OWNTRACKS, ot_location(), secret=s).status_code for s in secrets]
    assert codes == [200, 200, 200, 429]
    # Unauthenticated and malformed requests from the address are limited too.
    assert post(client, OWNTRACKS, "{nope", raw=True).status_code == 429
    other_address = Client(REMOTE_ADDR="198.51.100.20")
    assert (
        post(other_address, OWNTRACKS, ot_location(minutes_ago=2), secret=secrets[3]).status_code
        == 200
    )


def test_both_endpoints_are_rate_limited(client, alice, settings):
    settings.TRACKER_RATE_PER_TOKEN = 1
    _token, secret = device_token(alice, kind="colota")
    assert post(client, OVERLAND, {"locations": [ol_feature()]}, secret=secret).status_code == 200
    assert post(client, OWNTRACKS, ot_location(), secret=secret).status_code == 429


# --- Plausibility flags ------------------------------------------------------------------------


def flags_of(token) -> list[list[str]]:
    return [(p.extra or {}).get("flags", []) for p in points(token)]


def test_an_impossible_jump_is_flagged_and_kept(client, alice):
    """Wichita -> Denver (~700 km) in one minute, then back to Wichita a minute later: only
    the spike is flagged; nothing is dropped."""
    token, secret = device_token(alice, kind="overland")
    body = {"locations": [ol_feature(WICHITA, 12), ol_feature(DENVER, 11), ol_feature(WICHITA, 10)]}
    assert post(client, OVERLAND, body, secret=secret).status_code == 200
    assert flags_of(token) == [[], ["implied_speed"], []]


def test_jumps_are_judged_against_points_stored_by_earlier_requests(client, alice):
    token, secret = device_token(alice)
    assert post(client, OWNTRACKS, ot_location(WICHITA, 10), secret=secret).status_code == 200
    assert post(client, OWNTRACKS, ot_location(DENVER, 9.5), secret=secret).status_code == 200
    assert post(client, OWNTRACKS, ot_location(TOPEKA, 9), secret=secret).status_code == 200
    # Wichita -> Topeka (~200 km) in a minute is still too fast from Wichita and from Denver.
    assert flags_of(token) == [[], ["implied_speed"], ["implied_speed"]]


def test_a_plausible_trip_is_not_flagged(client, alice):
    """Wichita -> Topeka by car: about 220 km in 2.5 hours."""
    token, secret = device_token(alice, kind="overland")
    body = {"locations": [ol_feature(WICHITA, 160, speed=25), ol_feature(TOPEKA, 10, speed=0)]}
    assert post(client, OVERLAND, body, secret=secret).status_code == 200
    assert flags_of(token) == [[], []]


def test_a_reported_impossible_speed_is_flagged(client, alice):
    token, secret = device_token(alice)
    body = ot_location(vel=2000)  # km/h ≈ 556 m/s
    assert post(client, OWNTRACKS, body, secret=secret).status_code == 200
    assert flags_of(token) == [["reported_speed"]]


def test_poor_accuracy_is_allowed_for(client, alice):
    """Two coarse fixes 30 km apart, a minute apart, each ±20 km: not judged impossible."""
    token, secret = device_token(alice, kind="overland")
    shifted = {"type": "Point", "coordinates": [WICHITA.x + 0.34, WICHITA.y]}
    first = ol_feature(WICHITA, 6, horizontal_accuracy=20_000)
    second = ol_feature(WICHITA, 5, horizontal_accuracy=20_000)
    second["geometry"] = shifted
    assert post(client, OVERLAND, {"locations": [first, second]}, secret=secret).status_code == 200
    assert flags_of(token) == [[], []]
