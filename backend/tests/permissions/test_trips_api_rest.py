"""The rest of the trips API (work-order item 13): tags, purposes, stops, notes, GPS tracks,
photo metadata, route versions, leg order, bulk edit and list filters - every endpoint for every
actor of the synthetic family (tests/permissions/conftest.py), through real requests.

Same rules as item 6 (test_trips_api.py): 404 for what the caller can't see, 403 for a visible
thing they may not change, 401 signed out or deactivated, 422 for invalid data and for
references they can't use. The SQL/RLS and policy layers are checked in test_matrix.py.
"""

import pytest
from django.contrib.gis.geos import LineString, MultiLineString, Point

from tests.factories import LegFactory, RouteFactory
from tests.helpers import as_owner
from tests.permissions.test_trips_api import (
    ACTORS,
    API,
    as_actor,
    assert_no_identity,
    call,
    login,
    trip_path,
)
from travel.media.models import Media
from travel.trips.models import (
    Leg,
    Place,
    Purpose,
    Route,
    Stop,
    Tag,
    TrackContribution,
    Trip,
    TripNote,
    TripParticipant,
    TripTag,
)

pytestmark = pytest.mark.django_db

R = (401, 401)  # ivan (deactivated) and anonymous
ALL_200 = (200, 200, 200, 200, 200, *R)
TRACK = {"start_utc": "2024-05-02T10:00:00Z", "end_utc": "2024-05-02T12:00:00Z"}
INN = {"name": "Synthetic Motel", "lon": -97.3, "lat": 37.7}

# name -> (method, path(f), body(f) or None, expected status per actor in ACTORS order)
CASES = {
    # --- reads
    "list_tags": ("GET", lambda f: f"{API}/tags", None, ALL_200),
    "list_purposes": ("GET", lambda f: f"{API}/purposes", None, ALL_200),
    "list_trip_tags:family": ("GET", lambda f: trip_path(f, "family", "/tags"), None, ALL_200),
    "list_trip_tags:participants": (
        "GET", lambda f: trip_path(f, "participants", "/tags"), None, (404, 200, 200, 404, 404, *R)
    ),
    "list_stops:family": ("GET", lambda f: trip_path(f, "family", "/stops"), None, ALL_200),
    "list_stops:private": (
        "GET", lambda f: trip_path(f, "private", "/stops"), None, (404, 200, 404, 404, 404, *R)
    ),
    "list_notes:family": ("GET", lambda f: trip_path(f, "family", "/notes"), None, ALL_200),
    "list_notes:participants": (
        "GET", lambda f: trip_path(f, "participants", "/notes"), None, (404, 200, 200, 404, 404, *R)
    ),
    "list_tracks:family": ("GET", lambda f: trip_path(f, "family", "/tracks"), None, ALL_200),
    "list_media:family": ("GET", lambda f: trip_path(f, "family", "/media"), None, ALL_200),
    "list_media:private": (
        "GET", lambda f: trip_path(f, "private", "/media"), None, (404, 200, 404, 404, 404, *R)
    ),
    "list_leg_routes": ("GET", lambda f: f"{API}/legs/{f.core_leg.pk}/routes", None, ALL_200),
    "get_route": ("GET", lambda f: f"{API}/routes/{f.route.pk}", None, ALL_200),
    # --- tag definitions (own only)
    "create_tag": (
        "POST", lambda f: f"{API}/tags", lambda f: {"name": "new-tag"}, (201, 201, 201, 201, 403, *R)
    ),
    "create_tag_named_like_alices": (
        "POST",
        lambda f: f"{API}/tags",
        lambda f: {"name": "ALICE-TAG"},  # names are unique per owner, case-insensitively
        (201, 409, 201, 201, 403, *R),
    ),
    "create_tag_bad_color": (
        "POST",
        lambda f: f"{API}/tags",
        lambda f: {"name": "x", "color": "red"},
        (422, 422, 422, 422, 403, *R),
    ),
    "rename_alices_tag": (
        "PATCH",
        lambda f: f"{API}/tags/{f.alice_tag.pk}",
        lambda f: {"name": "renamed", "color": "#123abc"},
        (404, 200, 404, 404, 404, *R),
    ),
    "delete_bobs_tag_definition": (
        "DELETE", lambda f: f"{API}/tags/{f.bob_tag.pk}", None, (404, 404, 204, 404, 404, *R)
    ),
    # --- tags on trips (contributions)
    "tag_family_by_name": (
        "POST",
        lambda f: trip_path(f, "family", "/tags"),
        lambda f: {"name": "fresh"},
        (403, 201, 201, 403, 403, *R),
    ),
    "tag_participants_by_name": (
        "POST",
        lambda f: trip_path(f, "participants", "/tags"),
        lambda f: {"name": "fresh"},
        (404, 201, 201, 404, 404, *R),
    ),
    "tag_family_with_alices_tag": (
        "POST",
        lambda f: trip_path(f, "family", "/tags"),
        lambda f: {"tag_id": f.alice_tag.pk},
        (403, 201, 422, 403, 403, *R),
    ),
    "tag_family_with_bobs_tag_again": (
        "POST",
        lambda f: trip_path(f, "family", "/tags"),
        lambda f: {"tag_id": f.bob_tag.pk},
        (403, 422, 409, 403, 403, *R),
    ),
    "remove_bobs_tag:family": (
        "DELETE",
        lambda f: trip_path(f, "family", f"/tags/{f.bob_tag.pk}"),
        None,
        (403, 403, 204, 403, 403, *R),
    ),
    "remove_absent_tag:family": (
        "DELETE",
        lambda f: trip_path(f, "family", f"/tags/{f.alice_tag.pk}"),
        None,
        (404, 404, 404, 404, 404, *R),
    ),
    # --- stops (core itinerary)
    "add_stop_new_place:family": (
        "POST",
        lambda f: trip_path(f, "family", "/stops"),
        lambda f: {"kind": "lodging", "place": INN},
        (201, 201, 403, 403, 403, *R),
    ),
    "add_stop_new_place:private": (
        "POST",
        lambda f: trip_path(f, "private", "/stops"),
        lambda f: {"kind": "lodging", "place": INN},
        (404, 201, 404, 404, 404, *R),
    ),
    "add_stop_at_alices_private_place:family": (
        "POST",
        lambda f: trip_path(f, "family", "/stops"),
        lambda f: {"kind": "visit", "place_id": f.alice_private_place.pk},
        (422, 201, 403, 403, 403, *R),
    ),
    "add_stop_at_the_trips_place:family": (
        "POST",
        lambda f: trip_path(f, "family", "/stops"),
        lambda f: {"kind": "visit", "place_id": f.family_stop.place_id},
        (201, 201, 403, 403, 403, *R),
    ),
    "edit_family_stop": (
        "PATCH",
        lambda f: f"{API}/stops/{f.family_stop.pk}",
        lambda f: {"kind": "destination", "leg_id": f.core_leg.pk, "tz": "America/Chicago"},
        (200, 200, 403, 403, 403, *R),
    ),
    "delete_family_stop": (
        "DELETE", lambda f: f"{API}/stops/{f.family_stop.pk}", None, (204, 204, 403, 403, 403, *R)
    ),
    # --- notes
    "add_note:family": (
        "POST",
        lambda f: trip_path(f, "family", "/notes"),
        lambda f: {"body": "A synthetic note"},
        # Victor is a participant, but Viewers are read-only (Q-6).
        (403, 201, 201, 403, 403, *R),
    ),
    "add_note:private": (
        "POST",
        lambda f: trip_path(f, "private", "/notes"),
        lambda f: {"body": "A synthetic note"},
        (404, 201, 404, 404, 404, *R),
    ),
    "edit_bobs_note": (
        "PATCH",
        lambda f: f"{API}/notes/{f.bob_note.pk}",
        lambda f: {"body": "edited", "public_consent": True},
        (403, 403, 200, 403, 403, *R),
    ),
    "delete_bobs_note": (
        "DELETE", lambda f: f"{API}/notes/{f.bob_note.pk}", None, (403, 403, 204, 403, 403, *R)
    ),
    "delete_alices_note": (
        "DELETE", lambda f: f"{API}/notes/{f.alice_note.pk}", None, (403, 204, 403, 403, 403, *R)
    ),
    # --- GPS tracks
    "add_track:family": (
        "POST",
        lambda f: trip_path(f, "family", "/tracks"),
        lambda f: TRACK,
        (403, 201, 201, 403, 403, *R),
    ),
    "edit_bobs_track": (
        "PATCH",
        lambda f: f"{API}/tracks/{f.bob_track.pk}",
        lambda f: {"public_consent": True, "end_utc": "2024-05-01T19:00:00Z"},
        (403, 403, 200, 403, 403, *R),
    ),
    "delete_bobs_track": (
        "DELETE", lambda f: f"{API}/tracks/{f.bob_track.pk}", None, (403, 403, 204, 403, 403, *R)
    ),
    # --- photo metadata
    "edit_bobs_photo": (
        "PATCH",
        lambda f: f"{API}/media/{f.bob_photo.pk}",
        lambda f: {"caption": "Synthetic caption", "leg_id": f.core_leg.pk},
        (403, 403, 200, 403, 403, *R),
    ),
    "delete_bobs_photo": (
        "DELETE", lambda f: f"{API}/media/{f.bob_photo.pk}", None, (403, 403, 204, 403, 403, *R)
    ),
    "edit_alices_private_photo": (
        "PATCH",
        lambda f: f"{API}/media/{f.alice_private_photo.pk}",
        lambda f: {"caption": "x"},
        (404, 200, 404, 404, 404, *R),
    ),
    # --- leg order
    "reorder_legs:family": (
        "POST",
        lambda f: trip_path(f, "family", "/legs/order"),
        lambda f: {"leg_ids": [f.bob_leg.pk, f.core_leg.pk]},
        (200, 200, 403, 403, 403, *R),
    ),
    "reorder_legs_incomplete:family": (
        "POST",
        lambda f: trip_path(f, "family", "/legs/order"),
        lambda f: {"leg_ids": [f.core_leg.pk]},
        (422, 422, 403, 403, 403, *R),
    ),
    # --- bulk edit (all or nothing)
    "bulk_visibility": (
        "POST",
        lambda f: f"{API}/trips/bulk",
        lambda f: {"trip_ids": [f.trips["family"].pk, f.trips["public"].pk], "visibility": "family"},
        (200, 200, 403, 403, 403, *R),
    ),
    "bulk_including_a_private_trip": (
        "POST",
        lambda f: f"{API}/trips/bulk",
        lambda f: {"trip_ids": [f.trips["private"].pk, f.trips["family"].pk], "visibility": "family"},
        (404, 200, 404, 404, 404, *R),
    ),
    "bulk_bobs_tag": (
        "POST",
        lambda f: f"{API}/trips/bulk",
        lambda f: {"trip_ids": [f.trips["public"].pk], "add_tag_ids": [f.bob_tag.pk]},
        (422, 422, 200, 422, 422, *R),
    ),
    "bulk_add_carol": (
        "POST",
        lambda f: f"{API}/trips/bulk",
        lambda f: {
            "trip_ids": [f.trips["family"].pk, f.trips["public"].pk],
            "add_person_ids": [f.carol.person_id],
        },
        (200, 200, 403, 403, 403, *R),
    ),
}  # fmt: skip

PARAMS = [
    pytest.param(name, actor, status, id=f"{name}-{actor}")
    for name, (_, _, _, row) in CASES.items()
    for actor, status in zip(ACTORS, row, strict=True)
]


@pytest.mark.parametrize(("name", "actor", "expected"), PARAMS)
def test_api_matrix(client, scenario, name, actor, expected):
    f = scenario
    method, path, body, _ = CASES[name]
    response = call(as_actor(client, f, actor), method, path(f), body(f) if body else None)
    assert response.status_code == expected, response.content[:300]
    if expected < 300 and response.content:
        assert_no_identity(f, response.content)


def remove_bob(f):
    with as_owner():
        TripParticipant.objects.filter(pk=f.bob_participation_pk).delete()


# --- Q-16 and the contribution rule ------------------------------------------------------------


def test_owner_deletes_what_a_removed_participant_left(client, scenario):
    """Bob contributed a leg, note, track, tag and photo; Alice removed him from the trip. He
    still sees the (family) trip but no longer changes any of it; Alice may delete each (Q-16)."""
    f = scenario
    remove_bob(f)
    login(client, f.bob)
    for method, path, body in (
        ("PATCH", f"{API}/legs/{f.bob_leg.pk}", {"mode": "bus"}),
        ("DELETE", f"{API}/legs/{f.bob_leg.pk}", None),
        ("PATCH", f"{API}/notes/{f.bob_note.pk}", {"body": "x"}),
        ("DELETE", f"{API}/notes/{f.bob_note.pk}", None),
        ("PATCH", f"{API}/tracks/{f.bob_track.pk}", {"public_consent": True}),
        ("DELETE", f"{API}/tracks/{f.bob_track.pk}", None),
        ("DELETE", trip_path(f, "family", f"/tags/{f.bob_tag.pk}"), None),
        ("PATCH", f"{API}/media/{f.bob_photo.pk}", {"caption": "x"}),
        ("DELETE", f"{API}/media/{f.bob_photo.pk}", None),
    ):
        assert call(client, method, path, body).status_code == 403, (method, path)

    login(client, f.alice)
    detail = call(client, "GET", trip_path(f, "family")).json()
    leg = next(g for g in detail["legs"] if g["id"] == f.bob_leg.pk)
    assert (leg["can_edit"], leg["can_delete"]) == (False, True)
    notes = call(client, "GET", trip_path(f, "family", "/notes")).json()
    bobs = next(n for n in notes if n["id"] == f.bob_note.pk)
    assert (bobs["can_edit"], bobs["can_delete"]) == (False, True)
    # Alice still can't edit what Bob wrote, only delete it.
    assert call(client, "PATCH", f"{API}/notes/{f.bob_note.pk}", {"body": "x"}).status_code == 403
    for path in (
        f"{API}/legs/{f.bob_leg.pk}",
        f"{API}/notes/{f.bob_note.pk}",
        f"{API}/tracks/{f.bob_track.pk}",
        trip_path(f, "family", f"/tags/{f.bob_tag.pk}"),
        f"{API}/media/{f.bob_photo.pk}",
    ):
        assert call(client, "DELETE", path).status_code == 204, path
    with as_owner():
        assert not Leg.objects.filter(pk=f.bob_leg.pk).exists()
        assert not TripNote.objects.filter(pk=f.bob_note.pk).exists()
        assert not TrackContribution.objects.filter(pk=f.bob_track.pk).exists()
        assert not TripTag.objects.filter(pk=f.bob_triptag.pk).exists()
        assert not Media.objects.filter(pk=f.bob_photo.pk).exists()
        assert Tag.objects.filter(pk=f.bob_tag.pk).exists()  # his definition stays his


@pytest.mark.parametrize("actor", ["admin", "carol", "victor"])
def test_only_the_owner_deletes_a_removed_participants_contributions(client, scenario, actor):
    f = scenario
    remove_bob(f)
    login(client, getattr(f, actor))
    assert call(client, "DELETE", f"{API}/notes/{f.bob_note.pk}").status_code == 403
    assert call(client, "DELETE", f"{API}/legs/{f.bob_leg.pk}").status_code == 403


def test_owner_cannot_delete_a_current_participants_contributions(client, scenario):
    f = scenario
    login(client, f.alice)
    notes = call(client, "GET", trip_path(f, "family", "/notes")).json()
    bobs = next(n for n in notes if n["id"] == f.bob_note.pk)
    assert (bobs["can_edit"], bobs["can_delete"]) == (False, False)
    assert call(client, "DELETE", f"{API}/tracks/{f.bob_track.pk}").status_code == 403


def test_a_leg_include_keeps_a_contributor_on_the_trip(client, scenario):
    """'On the trip' is the sharing test: a trip-level row, or an include on any leg."""
    f = scenario
    remove_bob(f)
    login(client, f.alice)
    put = call(
        client,
        "PUT",
        f"{API}/legs/{f.core_leg.pk}/participants/{f.bob.person_id}",
        {"on_leg": True},
    )
    assert put.status_code == 200
    assert call(client, "DELETE", f"{API}/notes/{f.bob_note.pk}").status_code == 403
    login(client, f.bob)
    assert call(client, "PATCH", f"{API}/notes/{f.bob_note.pk}", {"body": "ok"}).status_code == 200


# --- Writes do what they say -------------------------------------------------------------------


def test_tags_on_a_trip_show_their_author_and_the_owners_first(client, scenario):
    f = scenario
    login(client, f.alice)
    added = call(client, "POST", trip_path(f, "family", "/tags"), {"name": "Road trip"})
    assert added.status_code == 201
    rows = added.json()
    assert [(t["name"], t["by_owner"]) for t in rows] == [("Road trip", True), ("bob-tag", False)]
    assert rows[1]["author"] == {"id": f.bob.pk, "display_name": "Bob"}
    assert [t["can_remove"] for t in rows] == [True, False]
    # Same name again (any case) reuses the tag, which is then already on the trip.
    again = call(client, "POST", trip_path(f, "family", "/tags"), {"name": "road TRIP"})
    assert again.status_code == 409
    listed = {t["name"]: t for t in call(client, "GET", f"{API}/tags").json()}
    assert listed["Road trip"]["trip_count"] == 1
    assert "bob-tag" not in listed  # other people's tags only show on trips
    trips = call(client, "GET", f"{API}/trips").json()["items"]
    fam = next(t for t in trips if t["id"] == f.trips["family"].pk)
    assert [t["name"] for t in fam["tags"]] == ["Road trip", "bob-tag"]


def test_deleting_a_tag_definition_takes_it_off_every_trip(client, scenario):
    f = scenario
    login(client, f.bob)
    assert call(client, "DELETE", f"{API}/tags/{f.bob_tag.pk}").status_code == 204
    with as_owner():
        assert not TripTag.objects.filter(tag_id=f.bob_tag.pk).exists()


def test_stop_with_a_new_place_belongs_to_its_creator(client, scenario):
    f = scenario
    login(client, f.admin)
    stop = call(
        client,
        "POST",
        trip_path(f, "family", "/stops"),
        {
            "kind": "lodging",
            "place": INN,
            "leg_id": f.core_leg.pk,
            "arrive_utc": "2024-05-01T20:00:00Z",
            "depart_utc": "2024-05-02T14:00:00Z",
            "tz": "America/Chicago",
        },
    )
    assert stop.status_code == 201, stop.content
    body = stop.json()
    assert (body["place"]["name"], body["leg_id"], body["can_edit"]) == (
        "Synthetic Motel",
        f.core_leg.pk,
        True,
    )
    assert body["author"] == {"id": f.admin.pk, "display_name": "Admin"}
    with as_owner():
        assert Place.objects.get(pk=body["place"]["id"]).owner_id == f.admin.pk
        assert Trip.objects.get(pk=f.trips["family"].pk).edited_in_app_at is not None
    detail = call(client, "GET", trip_path(f, "family")).json()
    assert {s["id"] for s in detail["stops"]} == {f.family_stop.pk, body["id"]}
    login(client, f.carol)
    stops = call(client, "GET", trip_path(f, "family", "/stops")).json()
    assert {s["place"]["name"] for s in stops} == {"Synthetic Inn", "Synthetic Motel"}
    assert not any(s["can_edit"] for s in stops)


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "lodging"},  # no place
        {"kind": "lodging", "place": INN, "place_id": 1},
        {"kind": "lodging", "place": INN, "tz": "Mars/Olympus"},
        {"kind": "lodging", "place": {**INN, "lat": 95}},
        {"kind": "palace", "place": INN},
        {
            "kind": "lodging",
            "place": INN,
            "arrive_utc": "2024-05-02T10:00:00Z",
            "depart_utc": "2024-05-01T10:00:00Z",
        },
    ],
)
def test_stop_validation(client, scenario, body):
    login(client, scenario.alice)
    assert call(client, "POST", trip_path(scenario, "family", "/stops"), body).status_code == 422


def test_stop_and_photo_legs_stay_inside_their_trip(client, scenario):
    f = scenario
    with as_owner():
        other = LegFactory(trip=f.trips["public"], author=f.alice, sequence=1)
    login(client, f.alice)
    stop = call(client, "PATCH", f"{API}/stops/{f.family_stop.pk}", {"leg_id": other.pk})
    assert stop.status_code == 422
    login(client, f.bob)
    photo = call(client, "PATCH", f"{API}/media/{f.bob_photo.pk}", {"leg_id": other.pk})
    assert photo.status_code == 422
    stop_ref = call(client, "PATCH", f"{API}/media/{f.bob_photo.pk}", {"stop_id": 999_999})
    assert stop_ref.status_code == 422
    ok = call(client, "PATCH", f"{API}/media/{f.bob_photo.pk}", {"stop_id": f.family_stop.pk})
    assert ok.status_code == 200
    assert ok.json()["stop_id"] == f.family_stop.pk


def test_note_and_track_round_trip(client, scenario):
    f = scenario
    login(client, f.bob)
    note = call(client, "POST", trip_path(f, "family", "/notes"), {"body": "Synthetic **note**"})
    assert note.status_code == 201
    assert (note.json()["author"]["id"], note.json()["can_edit"]) == (f.bob.pk, True)
    track = call(
        client, "POST", trip_path(f, "family", "/tracks"), {**TRACK, "public_consent": True}
    )
    assert track.status_code == 201
    body = track.json()
    assert (body["start_utc"], body["end_utc"], body["route_id"]) == (
        "2024-05-02T10:00:00Z",
        "2024-05-02T12:00:00Z",
        None,
    )
    assert body["public_consent"] is True
    tracks = call(client, "GET", trip_path(f, "family", "/tracks")).json()
    assert {t["id"] for t in tracks} == {f.bob_track.pk, body["id"]}


@pytest.mark.parametrize(
    "body",
    [
        {"start_utc": "2024-05-02T10:00:00Z", "end_utc": "2024-05-02T10:00:00Z"},
        {"start_utc": "2024-05-02T10:00:00Z", "end_utc": "2024-05-01T10:00:00Z"},
        {"start_utc": "2023-01-01T00:00:00Z", "end_utc": "2024-05-01T00:00:00Z"},
        {"start_utc": "2024-05-02T10:00:00", "end_utc": "2024-05-02T12:00:00"},
        {"start_utc": "2024-05-02T10:00:00Z"},
    ],
)
def test_track_validation(client, scenario, body):
    login(client, scenario.bob)
    assert call(client, "POST", trip_path(scenario, "family", "/tracks"), body).status_code == 422


def test_a_tracks_time_range_is_fixed_once_it_has_a_route(client, scenario):
    """Its route was built from that range; saved routes are never recomputed (rule 5)."""
    f = scenario
    with as_owner():
        route = RouteFactory(leg=f.bob_leg, created_by=f.bob, kind=Route.Kind.GPS)
        TrackContribution.objects.filter(pk=f.bob_track.pk).update(route=route)
    login(client, f.bob)
    moved = call(
        client, "PATCH", f"{API}/tracks/{f.bob_track.pk}", {"start_utc": "2024-05-01T13:00:00Z"}
    )
    assert moved.status_code == 409
    consent = call(client, "PATCH", f"{API}/tracks/{f.bob_track.pk}", {"public_consent": True})
    assert consent.status_code == 200


def test_media_metadata_never_shows_file_paths(client, scenario):
    f = scenario
    login(client, f.carol)
    rows = call(client, "GET", trip_path(f, "family", "/media")).json()
    assert [r["id"] for r in rows] == [f.bob_photo.pk]
    assert "display_path" not in rows[0] and "bob.webp" not in str(rows)


# --- Route versions ---------------------------------------------------------------------------


def test_route_versions_newest_first_with_the_current_one_marked(client, scenario):
    f = scenario
    with as_owner():
        v2 = RouteFactory(
            leg=f.core_leg,
            version=2,
            created_by=f.alice,
            kind=Route.Kind.HAND_EDITED,
            waypoints=[{"lon": -97.3, "lat": 37.7, "role": "anchor"}],
        )
        Leg.objects.filter(pk=f.core_leg.pk).update(current_route=v2)
    login(client, f.carol)
    rows = call(client, "GET", f"{API}/legs/{f.core_leg.pk}/routes").json()
    assert [(r["version"], r["is_current"]) for r in rows] == [(2, True), (1, False)]
    assert rows[0]["created_by"] == {"id": f.alice.pk, "display_name": "Alice"}
    detail = call(client, "GET", f"{API}/routes/{v2.pk}").json()
    assert detail["geometry"]["type"] == "MultiLineString"
    assert detail["waypoints"] == [{"lon": -97.3, "lat": 37.7, "role": "anchor"}]


@pytest.mark.parametrize(
    ("actor", "status"), [("admin", 404), ("alice", 200), ("bob", 404), ("carol", 404)]
)
def test_routes_on_a_private_trip_stay_private(client, scenario, actor, status):
    f = scenario
    with as_owner():
        leg = LegFactory(trip=f.trips["private"], author=f.alice, sequence=1)
        route = RouteFactory(leg=leg, created_by=f.alice)
    login(client, getattr(f, actor))
    assert call(client, "GET", f"{API}/routes/{route.pk}").status_code == status
    assert call(client, "GET", f"{API}/legs/{leg.pk}/routes").status_code == status


def test_routes_have_no_write_endpoints(client, scenario):
    """Saved routes are frozen versions (rule 5); new versions come with the editor (T25)."""
    f = scenario
    login(client, f.alice)
    for method in ("PATCH", "PUT", "DELETE"):
        assert call(client, method, f"{API}/routes/{f.route.pk}", {}).status_code == 405


# --- Leg order ----------------------------------------------------------------------------------


def test_owner_reorders_legs_including_contributed_ones(client, scenario):
    f = scenario
    login(client, f.alice)
    rows = call(
        client,
        "POST",
        trip_path(f, "family", "/legs/order"),
        {"leg_ids": [f.bob_leg.pk, f.core_leg.pk]},
    ).json()
    assert [(g["id"], g["sequence"]) for g in rows] == [(f.bob_leg.pk, 1), (f.core_leg.pk, 2)]
    with as_owner():
        bobs = Leg.objects.get(pk=f.bob_leg.pk)
    assert (bobs.author_id, bobs.is_contribution) == (f.bob.pk, True)
    new = call(client, "POST", trip_path(f, "family", "/legs"), {"mode": "walk"}).json()
    assert new["sequence"] == 3


@pytest.mark.parametrize(
    "ids",
    [
        lambda f: [f.core_leg.pk, f.core_leg.pk],
        lambda f: [f.core_leg.pk, f.bob_leg.pk, 999_999],
        lambda f: [],
    ],
)
def test_reorder_lists_every_leg_once(client, scenario, ids):
    f = scenario
    login(client, f.alice)
    response = call(client, "POST", trip_path(f, "family", "/legs/order"), {"leg_ids": ids(f)})
    assert response.status_code == 422


# --- Bulk edit ----------------------------------------------------------------------------------


def test_bulk_is_all_or_nothing_and_lists_every_refusal(client, scenario):
    f = scenario
    with as_owner():
        own = Trip.objects.create(
            owner=f.carol, title="Carol's", start_date="2022-01-01", end_date="2022-01-02"
        )
        tag = Tag.objects.create(owner=f.carol, name="carol-tag")
    login(client, f.carol)
    ids = [own.pk, f.trips["family"].pk, f.trips["public"].pk]
    response = call(client, "POST", f"{API}/trips/bulk", {"trip_ids": ids, "add_tag_ids": [tag.pk]})
    assert response.status_code == 403
    assert [r["trip_id"] for r in response.json()["refused"]] == ids[1:]
    with as_owner():
        assert not TripTag.objects.filter(tag=tag).exists()
    alone = call(
        client, "POST", f"{API}/trips/bulk", {"trip_ids": [own.pk], "add_tag_ids": [tag.pk]}
    )
    assert alone.status_code == 200
    assert [t["name"] for t in alone.json()["items"][0]["tags"]] == ["carol-tag"]


def test_bulk_sets_and_clears_purpose_and_manages_participants(client, scenario):
    f = scenario
    with as_owner():
        TripParticipant.objects.create(
            trip=f.trips["public"], person=f.carol.person, added_by=f.alice
        )
    ids = [f.trips["family"].pk, f.trips["public"].pk]
    login(client, f.alice)
    body = {
        "trip_ids": ids,
        "purpose_id": f.alice_purpose.pk,
        "add_person_ids": [f.carol.person_id],
        "add_tag_ids": [f.alice_tag.pk],
        "remove_tag_ids": [],
    }
    first = call(client, "POST", f"{API}/trips/bulk", body)
    assert first.status_code == 200, first.content
    assert [t["purpose"]["id"] for t in first.json()["items"]] == [f.alice_purpose.pk] * 2
    with as_owner():
        for pk in ids:
            assert TripParticipant.objects.filter(trip_id=pk, person=f.carol.person).exists()
            assert TripTag.objects.filter(trip_id=pk, tag=f.alice_tag).exists()
    cleared = call(
        client,
        "POST",
        f"{API}/trips/bulk",
        {
            "trip_ids": ids,
            "purpose_id": None,
            "remove_person_ids": [f.carol.person_id],
            "remove_tag_ids": [f.alice_tag.pk],
        },
    )
    assert cleared.status_code == 200
    assert [t["purpose"] for t in cleared.json()["items"]] == [None, None]
    with as_owner():
        assert not TripParticipant.objects.filter(trip_id__in=ids, person=f.carol.person).exists()
        assert not TripTag.objects.filter(trip_id__in=ids, tag=f.alice_tag).exists()


def test_bulk_refuses_another_users_purpose_and_hidden_people(client, scenario):
    f = scenario
    login(client, f.admin)
    ids = [f.trips["family"].pk]
    purpose = call(
        client, "POST", f"{API}/trips/bulk", {"trip_ids": ids, "purpose_id": f.alice_purpose.pk}
    )
    assert purpose.status_code == 422  # the Admin can't see Alice's unused purpose
    person = call(
        client,
        "POST",
        f"{API}/trips/bulk",
        {"trip_ids": ids, "add_person_ids": [f.alices_private_person.pk]},
    )
    assert person.status_code == 404


# --- List filters ---------------------------------------------------------------------------


def list_ids(client, query: str) -> set[int]:
    response = call(client, "GET", f"{API}/trips?{query}")
    assert response.status_code == 200, response.content
    return {t["id"] for t in response.json()["items"]}


def test_filters_by_purpose_tag_mode_and_vehicle(client, scenario):
    f = scenario
    fam, pub = f.trips["family"].pk, f.trips["public"].pk
    with as_owner():
        Trip.objects.filter(pk=pub).update(purpose=f.alice_purpose)
        LegFactory(trip=f.trips["public"], author=f.alice, sequence=1, mode="flight")
        Leg.objects.filter(pk=f.core_leg.pk).update(vehicle=f.hidden_vehicle)
        other = Purpose.objects.create(owner=f.alice, name="Synthetic other")
    login(client, f.alice)
    assert list_ids(client, f"purpose={f.alice_purpose.pk}") == {pub}
    assert list_ids(client, f"purpose={f.alice_purpose.pk}&purpose={other.pk}") == {pub}
    assert list_ids(client, f"tag={f.bob_tag.pk}") == {fam}
    assert list_ids(client, "mode=flight") == {pub}
    assert list_ids(client, "mode=flight&mode=drive") == {fam, pub}
    assert list_ids(client, f"vehicle={f.hidden_vehicle.pk}") == {fam}
    assert list_ids(client, f"mode=flight&tag={f.bob_tag.pk}") == set()
    # A hidden vehicle filters like a missing one for everyone else: nothing matches.
    login(client, f.carol)
    assert list_ids(client, f"vehicle={f.hidden_vehicle.pk}") == set()
    assert list_ids(client, f"vehicle={f.hidden_vehicle.pk}&vehicle=999999") == set()
    assert list_ids(client, f"tag={f.bob_tag.pk}") == {fam}
    login(client, f.admin)
    assert list_ids(client, f"purpose={f.alice_purpose.pk}") == {pub}


def test_bbox_matches_routes_airports_and_stops(client, scenario):
    """The family trip's route runs Wichita-Topeka (factories); its stop is in Wichita."""
    f = scenario
    with as_owner():
        Leg.objects.filter(pk=f.core_leg.pk).update(current_route=f.route)
        far = LegFactory(trip=f.trips["public"], author=f.alice, sequence=1)
        RouteFactory(
            leg=far,
            created_by=f.alice,
            geom=MultiLineString(
                LineString(Point(179.5, -17.0), Point(179.9, -17.5), srid=4326), srid=4326
            ),
        )
        Stop.objects.filter(pk=f.family_stop.pk).delete()
    fam = f.trips["family"].pk
    login(client, f.carol)
    assert list_ids(client, "bbox=-96,38,-95,40") == {fam}  # crosses the route near Topeka
    assert list_ids(client, "bbox=10,10,20,20") == set()
    # The public trip's route isn't its leg's current route, so it doesn't count.
    assert list_ids(client, "bbox=179,-18,-179,-16") == set()
    with as_owner():
        Leg.objects.filter(pk=far.pk).update(current_route=far.routes.get())
    assert list_ids(client, "bbox=179,-18,-179,-16") == {f.trips["public"].pk}


def test_bbox_matches_a_stop_place(client, scenario):
    f = scenario
    login(client, f.carol)
    assert list_ids(client, "bbox=-97.4,37.6,-97.3,37.7") == {f.trips["family"].pk}


@pytest.mark.parametrize("bbox", ["1,2,3", "a,b,c,d", "0,10,1,5", "-190,0,0,1", "nan,0,1,1"])
def test_bad_bbox(client, scenario, bbox):
    login(client, scenario.alice)
    assert call(client, "GET", f"{API}/trips?bbox={bbox}").status_code == 422
