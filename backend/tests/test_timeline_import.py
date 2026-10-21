"""Milestone 2.2: Google Timeline import with re-import diffing (PLAN.md §8)."""

import copy
import datetime as dt
import json
import tracemalloc

import pytest
from django.contrib.gis.geos import LineString, Point

from tests.factories import UserFactory
from tests.helpers import as_owner
from tests.synth import timeline as synth
from travel.core.rls import rls_context
from travel.history import importers, rawstore
from travel.history.models import (
    ImportBatch,
    LocationPoint,
    PlaceHint,
    PointSource,
    TimelineSegment,
)
from travel.history.timeline import formats
from travel.trips.models import Leg, ReviewFlag, Trip

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def bulk(settings, tmp_path):
    settings.BULK_DIR = tmp_path / "bulk"
    return settings.BULK_DIR


@pytest.fixture
def user():
    with as_owner():
        return UserFactory()


def run_import(user, document, tmp_path, name="Timeline.json") -> ImportBatch:
    data = document if isinstance(document, bytes) else synth.dumps(document)
    path = tmp_path / f"upload-{len(data)}-{hash(data)}.json"
    path.write_bytes(data)
    with rls_context(user.pk):
        raw = rawstore.find_existing(user.pk, rawstore.sha256_file(path))
        raw = raw or rawstore.store_file(user.pk, path, original_name=name)
        batch = ImportBatch.objects.create(owner=user, kind="google_timeline", raw_file=raw)
    return importers.run(batch.pk, user.pk)


def current(user, **filters):
    with as_owner():
        return list(TimelineSegment.objects.filter(owner=user, is_current=True, **filters))


def place(segments, place_id):
    return next(s for s in segments if s.place_id == place_id)


# --- Parser units ---------------------------------------------------------------------------


def test_coordinate_formats():
    assert formats.parse_latlng("48.8566120°, 2.3522190°") == (48.856612, 2.352219)
    assert formats.parse_latlng("geo:41.570045,-8.468077") == (41.570045, -8.468077)
    assert formats.parse_latlng({"latLng": "-33.8688°, 151.2093°"}) == (-33.8688, 151.2093)
    with pytest.raises(formats.ParseWarning):
        formats.parse_latlng("somewhere")
    with pytest.raises(formats.ParseWarning):
        formats.parse_latlng("95.0°, 10.0°")


def test_times_enums_and_string_numbers():
    utc = dt.datetime(2025, 3, 1, 13, 0, tzinfo=dt.UTC)
    assert formats.parse_time("2025-03-01T08:00:00.000-05:00") == utc
    assert formats.parse_time("2025-03-01T13:00:00.000Z") == utc
    with pytest.raises(formats.ParseWarning):
        formats.parse_time("2025-03-01T13:00:00")
    assert formats.enum("in passenger vehicle") == "IN_PASSENGER_VEHICLE"
    assert formats.enum("Searched Address") == "SEARCHED_ADDRESS"
    assert formats.num("0.598864") == pytest.approx(0.598864)
    assert formats.num(12) == 12.0


# --- First import -----------------------------------------------------------------------------


def test_android_import(user, tmp_path):
    batch = run_import(user, synth.road_trip(), tmp_path)
    assert batch.status == ImportBatch.Status.DONE
    summary = batch.summary
    assert summary["format"] == "android" and summary["format_verified"] is True
    assert summary["segments"]["total"] == 10
    assert summary["segments"]["new"] == 10
    assert summary["points"][PointSource.GOOGLE_PATH] == {"seen": 3, "inserted": 3, "duplicates": 0}
    assert summary["points"][PointSource.GOOGLE_RAW]["inserted"] == 2
    assert summary["place_hints_new"] == 1  # profile HOME + HOME-labelled visits, same place
    segments = current(user)
    assert len(segments) == 10
    hotel = place(segments, "ChIJsyntheticHotel")
    assert isinstance(hotel.geom, Point) and hotel.hierarchy_level == 0
    assert place(segments, "ChIJsyntheticMuseum").hierarchy_level == 1
    drive = next(s for s in segments if s.kind == "activity")
    assert isinstance(drive.geom, LineString)
    assert drive.activity_type == "IN_PASSENGER_VEHICLE"
    with as_owner():
        assert LocationPoint.objects.filter(owner=user).count() == 5
        assert PlaceHint.objects.get(owner=user).label == "HOME"


def test_import_never_touches_other_users_data(user, tmp_path):
    with as_owner():
        other = UserFactory()
    run_import(other, synth.road_trip(), tmp_path)
    batch = run_import(user, synth.road_trip(), tmp_path)
    assert batch.summary["format"] == "android"
    with as_owner():
        assert TimelineSegment.objects.filter(owner=other).count() == 10
        assert TimelineSegment.objects.filter(owner=user).count() == 10


# --- Re-imports ---------------------------------------------------------------------------------


def test_identical_content_in_a_new_file_is_skipped(user, tmp_path):
    run_import(user, synth.road_trip(), tmp_path)
    reformatted = json.dumps(synth.road_trip(), indent=2).encode()  # different bytes, same data
    batch = run_import(user, reformatted, tmp_path)
    segments = batch.summary["segments"]
    assert segments["identical"] == 10
    assert segments["new"] == segments["changed"] == 0
    assert batch.summary["points"][PointSource.GOOGLE_PATH]["duplicates"] == 3
    assert len(current(user)) == 10


def test_edited_visit_becomes_a_new_version_and_the_old_is_kept(user, tmp_path):
    run_import(user, synth.road_trip(), tmp_path)
    edited = synth.road_trip()
    edited["semanticSegments"][4]["visit"]["topCandidate"]["placeId"] = "ChIJsyntheticOtherHotel"
    batch = run_import(user, edited, tmp_path)
    assert batch.summary["segments"]["changed"] == 1
    assert batch.summary["segments"]["identical"] == 9
    with as_owner():
        new = TimelineSegment.objects.get(owner=user, place_id="ChIJsyntheticOtherHotel")
        old = TimelineSegment.objects.get(owner=user, place_id="ChIJsyntheticHotel")
    assert new.is_current and new.version == 2
    assert not old.is_current and old.superseded_by_id == new.pk
    assert new.lineage_id == old.lineage_id


def test_absent_segments_are_not_deleted(user, tmp_path):
    run_import(user, synth.road_trip(), tmp_path)
    shorter = synth.road_trip()
    shorter["semanticSegments"] = shorter["semanticSegments"][:3]  # Google dropped the rest
    batch = run_import(user, shorter, tmp_path)
    assert batch.summary["segments"]["identical"] == 3
    assert batch.summary["segments"]["absent_kept"] >= 1
    assert len(current(user)) == 10


def test_split_visit_supersedes_once_and_adds_a_new_lineage(user, tmp_path):
    run_import(user, synth.road_trip(), tmp_path)
    split = synth.road_trip()
    hotel = split["semanticSegments"][4]
    morning = copy.deepcopy(hotel)
    hotel["endTime"] = synth.t(1, 22).isoformat(timespec="milliseconds")
    morning["startTime"] = synth.t(1, 22).isoformat(timespec="milliseconds")
    morning["visit"]["topCandidate"]["placeId"] = "ChIJsyntheticBreakfast"
    split["semanticSegments"].insert(5, morning)
    batch = run_import(user, split, tmp_path)
    assert batch.summary["segments"]["changed"] == 1
    assert batch.summary["segments"]["new"] == 1
    visits = current(user, kind="visit", hierarchy_level=0)
    assert {v.place_id for v in visits} >= {"ChIJsyntheticHotel", "ChIJsyntheticBreakfast"}


def test_merged_visits_supersede_both_originals(user, tmp_path):
    original = synth.road_trip()
    hotel = original["semanticSegments"][4]
    second_half = copy.deepcopy(hotel)
    hotel["endTime"] = synth.t(1, 22).isoformat(timespec="milliseconds")
    second_half["startTime"] = synth.t(1, 22).isoformat(timespec="milliseconds")
    second_half["visit"]["topCandidate"]["placeId"] = "ChIJsyntheticHotelAgain"
    original["semanticSegments"].insert(5, second_half)
    run_import(user, original, tmp_path)
    merged = synth.road_trip()  # one long hotel visit again
    batch = run_import(user, merged, tmp_path)
    assert batch.summary["segments"]["changed"] == 1
    assert batch.summary["segments"]["merged_superseded"] == 1
    visits = current(user, kind="visit", hierarchy_level=0)
    assert "ChIJsyntheticHotelAgain" not in {v.place_id for v in visits}


def test_in_app_edits_win_over_imported_changes(user, tmp_path):
    run_import(user, synth.road_trip(), tmp_path)
    with as_owner():
        google = TimelineSegment.objects.get(owner=user, place_id="ChIJsyntheticHotel")
        TimelineSegment.objects.filter(pk=google.pk).update(is_current=False)
        mine = TimelineSegment.objects.get(pk=google.pk)
        mine.pk = None
        mine.version, mine.is_current, mine.edited_in_app = 2, True, True
        mine.place_id = "ChIJmyOwnCorrection"
        mine.save()
    changed = synth.road_trip()
    changed["semanticSegments"][4]["visit"]["topCandidate"]["placeId"] = "ChIJgoogleChanged"
    batch = run_import(user, changed, tmp_path)
    assert batch.summary["segments"]["kept_app_edits"] == 1
    with as_owner():
        live = TimelineSegment.objects.get(lineage_id=google.lineage_id, is_current=True)
        stored = TimelineSegment.objects.get(place_id="ChIJgoogleChanged")
    assert live.place_id == "ChIJmyOwnCorrection"
    assert not stored.is_current and stored.version == 3


def test_confirmed_trips_on_changed_data_are_flagged_not_changed(user, tmp_path):
    run_import(user, synth.road_trip(), tmp_path)
    hotel = place(current(user), "ChIJsyntheticHotel")
    with as_owner():
        trip = Trip.objects.create(
            owner=user,
            title="Kansas City",
            status="confirmed",
            start_date=dt.date(2025, 3, 1),
            end_date=dt.date(2025, 3, 2),
        )
        Leg.objects.create(
            trip=trip, sequence=1, mode="drive", author=user, source_segments=[hotel.pk]
        )
    edited = synth.road_trip()
    edited["semanticSegments"][4]["visit"]["topCandidate"]["placeId"] = "ChIJsyntheticOtherHotel"
    batch = run_import(user, edited, tmp_path)
    assert batch.summary["trips_flagged_for_review"] == 1
    with as_owner():
        trip.refresh_from_db()
        flag = ReviewFlag.objects.get(trip=trip)
        leg = trip.legs.get()
    assert trip.needs_review and trip.title == "Kansas City"
    assert flag.reason == "source_changed" and flag.details["segments"][0]["old"] == hotel.pk
    assert leg.source_segments == [hotel.pk]  # untouched until the user reviews


def test_nested_visits_never_match_their_parent(user, tmp_path):
    run_import(user, synth.road_trip(), tmp_path)
    without_parent = synth.road_trip()
    del without_parent["semanticSegments"][4]  # the hotel; the museum inside it remains
    batch = run_import(user, without_parent, tmp_path)
    assert batch.summary["segments"]["changed"] == 0
    assert place(current(user), "ChIJsyntheticHotel").is_current


# --- iOS, malformed input, scale ------------------------------------------------------------------


def test_ios_export(user, tmp_path):
    batch = run_import(user, synth.to_ios(synth.road_trip()), tmp_path)
    summary = batch.summary
    assert summary["format"] == "ios" and summary["format_verified"] is False
    assert summary["segments"]["total"] == 9  # the iOS variant has no timelineMemory
    assert summary["points"][PointSource.GOOGLE_PATH]["inserted"] == 3
    segments = current(user)
    assert place(segments, "ChIJsyntheticHome").semantic_type == "HOME"
    assert {s.activity_type for s in segments if s.kind == "activity"} == {"IN_PASSENGER_VEHICLE"}
    assert place(segments, "ChIJsyntheticMuseum").hierarchy_level == 1


def test_ios_minute_precision_path_points_are_all_kept(user, tmp_path):
    export = synth.android_export(
        [
            synth.path(
                synth.t(1, 8),
                synth.t(1, 10),
                [
                    (37.70, -97.40, synth.t(1, 8, 5)),
                    (37.71, -97.41, synth.t(1, 8, 5)),
                    (37.72, -97.42, synth.t(1, 8, 5)),
                ],
            ),
        ]
    )
    batch = run_import(user, synth.to_ios(export), tmp_path)
    assert batch.summary["points"][PointSource.GOOGLE_PATH] == {
        "seen": 3,
        "inserted": 3,
        "duplicates": 0,
    }


def test_malformed_records_are_skipped_and_reported(user, tmp_path):
    export = synth.road_trip()
    export["semanticSegments"][1]["activity"]["start"]["latLng"] = "nowhere"
    del export["semanticSegments"][2]["endTime"]
    export["rawSignals"][0]["position"]["LatLng"] = "999°, 999°"
    batch = run_import(user, export, tmp_path)
    assert batch.status == ImportBatch.Status.DONE
    assert batch.summary["warning_count"] == 3
    assert batch.summary["segments"]["total"] == 8


def _peak_import(user, tmp_path, n_points: int, offset: int) -> tuple[int, int, ImportBatch]:
    start = synth.t(1, 0) + dt.timedelta(days=offset)
    signals = [
        synth.raw_position(
            start + dt.timedelta(seconds=10 * i), (37.0 + i * 1e-5, -97.0 - i * 1e-5)
        )
        for i in range(n_points)
    ]
    document = synth.dumps(synth.android_export([], raw_signals=signals))
    tracemalloc.start()
    batch = run_import(user, document, tmp_path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak, len(document), batch


def test_parsing_streams_with_bounded_memory(user, tmp_path):
    """Peak memory stays flat as files grow: nothing loads the whole export."""
    small_peak, small_size, _ = _peak_import(user, tmp_path, 20_000, offset=0)
    large_peak, large_size, batch = _peak_import(user, tmp_path, 80_000, offset=30)
    assert large_size > 3.5 * small_size
    assert batch.summary["points"][PointSource.GOOGLE_RAW]["inserted"] == 80_000
    assert large_peak < small_peak * 1.3 + 1_000_000, (small_peak, large_peak)
    assert large_peak < 32 * 1024 * 1024


def test_upload_flow_runs_the_importer(user, tmp_path, client, settings):
    from travel.history import uploads

    settings.TRAVEL_UPLOAD_CHUNK_BYTES = 1 << 20
    data = synth.dumps(synth.road_trip())
    with as_owner():
        client.force_login(user)
    info = client.post(
        "/api/v1/uploads",
        {"filename": "Timeline.json", "size": len(data), "kind": "google_timeline"},
        content_type="application/json",
    ).json()
    import hashlib

    client.put(
        f"/api/v1/uploads/{info['id']}/chunks/0",
        data,
        content_type="application/octet-stream",
        HTTP_X_CHUNK_SHA256=hashlib.sha256(data).hexdigest(),
    )
    batch_id = client.post(f"/api/v1/uploads/{info['id']}/complete").json()["id"]
    uploads.process_upload(info["id"], user.pk)
    detail = client.get(f"/api/v1/imports/{batch_id}").json()
    assert detail["status"] == "done"
    assert detail["summary"]["segments"]["new"] == 10
