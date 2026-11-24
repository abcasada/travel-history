"""Trip spreadsheet upload, preview and commit (item 14c-1, docs/design/trip-sheet.md §28.8,
§28.9) on SYNTHETIC workbooks: the `trip_sheet` upload kind and worker step, the preview's
outcomes and diff, the commit through the trips services as the caller, and re-imports that
never delete by absence (rule 6) and never change a trip edited in the app (rule 7)."""

import datetime as dt

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.factories import PersonFactory, RouteFactory, UserFactory, user_with_person
from tests.helpers import as_owner
from tests.test_uploads import upload_all
from tests.tripsheet_data import FIELDS, LEGS, STOPS, example, leg, load_places, workbook
from travel.accounts.models import Person, Role
from travel.core.rls import rls_context
from travel.history import uploads
from travel.history.models import ImportBatch
from travel.trips import services
from travel.trips.models import (
    Leg,
    ReviewFlag,
    Stop,
    Trip,
    TripParticipant,
    TripSheetLink,
    TripSheetRecord,
    TripTag,
)

pytestmark = pytest.mark.django_db
API = "/api/v1"


@pytest.fixture(autouse=True)
def setup(settings, tmp_path):
    settings.BULK_DIR = tmp_path / "bulk"
    settings.TRAVEL_UPLOAD_CHUNK_BYTES = 1024  # what upload_all sends
    settings.TRAVEL_UPLOAD_MAX_BYTES = 2_000_000
    settings.TRAVEL_USER_QUOTA_BYTES = 20_000_000
    load_places()


@pytest.fixture
def alice(client):
    with as_owner():
        user = user_with_person(display_name="Alice Synth")
        client.force_login(user)
    client.user = user
    return client


def upload(client, data: bytes, name="trips.xlsx") -> int:
    info = upload_all(client, data, kind="trip_sheet", name=name)
    response = client.post(f"{API}/uploads/{info['id']}/complete")
    assert response.status_code == 202, response.content
    return uploads.process_upload(info["id"], client.user.pk).pk


def preview(client, batch_id: int) -> dict:
    response = client.get(f"{API}/imports/{batch_id}/trip-sheet")
    assert response.status_code == 200, response.content
    return response.json()


def commit(client, batch_id: int, expect=200, **body):
    response = client.post(
        f"{API}/imports/{batch_id}/commit", body, content_type="application/json"
    )
    assert response.status_code == expect, response.content
    return response.json()


def seen(view: dict) -> list[dict]:
    return [
        {"record_id": t["record_id"], "trip_updated_at": t["trip_updated_at"]} for t in view["tabs"]
    ]


def import_once(client, rows=None, name="trips.xlsx") -> Trip:
    batch_id = upload(client, workbook({"Loop": rows or example()}), name=name)
    view = preview(client, batch_id)
    result = commit(client, batch_id, seen=seen(view))
    with rls_context(client.user.pk):
        return Trip.objects.get(pk=result["results"][0]["trip_id"])


def trip_rows(user, trip):
    with rls_context(user.pk):
        trip.refresh_from_db()
        stops = list(Stop.objects.filter(trip=trip).select_related("place").order_by("pk"))
        legs = list(Leg.objects.filter(trip=trip).order_by("sequence"))
    return stops, legs


def test_upload_preview_commit(alice):
    batch_id = upload(alice, workbook({"Loop": example()}))
    with rls_context(alice.user.pk):
        batch = ImportBatch.objects.get(pk=batch_id)
    assert batch.status == "preview" and batch.summary["tabs"] == 1
    assert batch.raw_file.original_name == "trips.xlsx"
    with as_owner():
        assert not Trip.objects.exists()  # parsing never writes trips

    view = preview(alice, batch_id)
    assert view["can_commit"] and view["status"] == "preview"
    (tab,) = view["tabs"]
    assert (tab["outcome"], tab["key"], tab["title"]) == ("new", "synth-loop", "Synthetic loop")
    assert tab["trip_updated_at"] is None and tab["new_tags"] == ["road trip"]
    assert [len(tab["diff"][p]["added"]) for p in ("stops", "legs")] == [4, 3]
    assert tab["legs"][0]["name"] == "Synthport → Denver International Airport"
    assert len(tab["stops"]) == 4

    result = commit(alice, batch_id, seen=seen(view))
    assert result["status"] == "done"
    assert [r["outcome"] for r in result["results"]] == ["created"]
    with rls_context(alice.user.pk):
        trip = Trip.objects.get(pk=result["results"][0]["trip_id"])
        record = TripSheetRecord.objects.get(import_batch_id=batch_id)
        link = TripSheetLink.objects.get(owner=alice.user)
        people = list(TripParticipant.objects.filter(trip=trip).values_list("person_id", flat=True))
        tags = list(TripTag.objects.filter(trip=trip).values_list("tag__name", flat=True))
    assert (trip.source, trip.status, trip.owner_id) == ("sheet_import", "confirmed", alice.user.pk)
    assert trip.edited_in_app_at is None
    assert (trip.title, trip.start_date, trip.end_date) == (
        "Synthetic loop", dt.date(2015, 6, 12), dt.date(2015, 6, 19),
    )  # fmt: skip
    assert people == [alice.user.person_id] and tags == ["road trip"]
    assert (record.outcome, record.trip_id) == ("created", trip.pk)
    assert (link.key, link.trip_id, link.applied_hash) == (
        "synth-loop",
        trip.pk,
        record.content_hash,
    )
    stops, legs = trip_rows(alice.user, trip)
    assert [s.sheet_key for s in stops][0] == "label:home"
    assert {s.import_batch_id for s in stops} == {batch_id}
    assert stops[2].notes == "SYNTHETIC note: cabin by the creek" and stops[2].kind == "lodging"
    assert stops[3].place.name == "Old Town Synth" and stops[3].tz == "America/Denver"
    out, drive, last = legs
    assert (out.mode, out.flight_number, out.seat, out.author_id) == (
        "flight", "WN1234", "14C", alice.user.pk,
    )  # fmt: skip
    assert out.origin_airport.iata_code == "MCI" and out.destination_airport.iata_code == "DEN"
    assert out.start_utc == dt.datetime(2015, 6, 12, 13, 5, tzinfo=dt.UTC)
    assert (out.origin_stop_id, out.destination_stop_id) == (stops[0].pk, stops[1].pk)
    assert drive.notes == "SYNTHETIC leg note" and drive.import_batch_id == batch_id
    assert last.sheet_key.startswith("leg|drive|label:springs|")
    # The batch is finished: no second commit.
    commit(alice, batch_id, expect=409)


def test_identical_reimport_writes_nothing(alice):
    trip = import_once(alice)
    before = trip.updated_at
    batch_id = upload(alice, workbook({"Loop": example()}), name="again.xlsx")
    view = preview(alice, batch_id)
    assert view["tabs"][0]["outcome"] == "identical"
    commit(alice, batch_id, seen=seen(view))
    with rls_context(alice.user.pk):
        trip.refresh_from_db()
        assert TripSheetRecord.objects.get(import_batch_id=batch_id).outcome == "identical"
    assert trip.updated_at == before


def test_identical_bytes_show_the_open_preview_again(alice):
    data = workbook({"Loop": example()})
    first = upload(alice, data)
    second = upload(alice, data, name="renamed.xlsx")
    with rls_context(alice.user.pk):
        batch = ImportBatch.objects.get(pk=second)
    assert batch.status == "duplicate" and batch.summary == {"duplicate_of_batch": first}
    commit(alice, first, seen=seen(preview(alice, first)))
    # Once committed, the same bytes are parsed again into a new preview (D-100).
    third = upload(alice, data)
    assert preview(alice, third)["tabs"][0]["outcome"] == "identical"


def changed_rows():
    """The example with springs' notes changed, Old Town (row 10) and the leg to it gone, a new
    stop and leg, and blank Title and leg notes (blank never clears)."""
    stops = [
        STOPS[0],
        STOPS[1],
        [*STOPS[2][:7], "SYNTHETIC note: changed"],
        ["lake", "Twin Synth, KS", "", "visit", "2015-06-13 12:00", "2015-06-13 18:00", "", ""],
    ]
    legs = [
        LEGS[0],
        leg("", 8, "springs", "drive", "2015-06-12 10:45", "2015-06-12 12:15"),
        leg("", "springs", "lake", "drive", "2015-06-13 08:00", "2015-06-13 12:00"),
    ]
    return example(fields={**FIELDS, "Title": ""}, stops=stops, legs=legs)


def test_reimport_updates_an_untouched_trip_and_keeps_missing_rows(alice):
    trip = import_once(alice)
    stops_before, legs_before = trip_rows(alice.user, trip)
    batch_id = upload(alice, workbook({"Loop": changed_rows()}), name="v2.xlsx")
    view = preview(alice, batch_id)
    (tab,) = view["tabs"]
    assert tab["outcome"] == "update" and tab["trip_id"] == trip.pk
    diff = tab["diff"]
    assert diff["trip"] == []  # blank Title: not given, the title stays
    assert [s["name"] for s in diff["stops"]["added"]] == ["Twin Synth"]
    assert [c["field"] for c in diff["stops"]["changed"][0]["changes"]] == ["notes"]
    assert [s["name"] for s in diff["stops"]["kept"]] == ["Old Town Synth"]
    assert len(diff["legs"]["added"]) == 1 and len(diff["legs"]["kept"]) == 1
    commit(alice, batch_id, seen=seen(view))

    stops, legs = trip_rows(alice.user, trip)
    assert trip.title == "Synthetic loop" and trip.edited_in_app_at is None
    assert len(stops) == 5  # rule 6: Old Town is kept
    assert {s.pk for s in stops_before} <= {s.pk for s in stops}
    assert next(s for s in stops if s.sheet_key == "label:springs").notes.endswith("changed")
    assert len(legs) == 4 and {leg.pk for leg in legs_before} <= {leg.pk for leg in legs}
    assert legs[1].notes == "SYNTHETIC leg note"  # blank cell: kept
    # Sheet legs in sheet order; the kept leg (14 June) after the new one (13 June).
    assert [leg.sequence for leg in legs] == [1, 2, 3, 4]
    assert legs[3].pk == legs_before[2].pk
    assert legs[2].sheet_key.startswith("leg|drive|label:springs|label:lake")
    with rls_context(alice.user.pk):
        link = TripSheetLink.objects.get(owner=alice.user)
        assert link.last_record.import_batch_id == batch_id


def test_remove_missing_rows_only_when_asked(alice):
    trip = import_once(alice)
    batch_id = upload(alice, workbook({"Loop": changed_rows()}), name="v2.xlsx")
    view = preview(alice, batch_id)
    record_id = view["tabs"][0]["record_id"]
    commit(alice, batch_id, seen=seen(view), remove_missing=[record_id])
    stops, legs = trip_rows(alice.user, trip)
    assert len(stops) == 4 and "Old Town Synth" not in [s.place.name for s in stops]
    assert len(legs) == 3


def test_contributed_legs_are_never_touched(alice):
    trip = import_once(alice)
    with as_owner():
        bob = user_with_person(display_name="Bob Synth")
        TripParticipant.objects.create(trip=trip, person=bob.person, added_by=alice.user)
        contributed = Leg.objects.create(
            trip=trip, sequence=99, mode="walk", author=bob, is_contribution=True,
            participant_scope="author", notes="Bob's",
        )  # fmt: skip
    batch_id = upload(alice, workbook({"Loop": changed_rows()}), name="v2.xlsx")
    view = preview(alice, batch_id)
    assert view["tabs"][0]["outcome"] == "update"  # a contribution isn't an edit of the trip
    commit(alice, batch_id, seen=seen(view), remove_missing=[view["tabs"][0]["record_id"]])
    with as_owner():
        contributed.refresh_from_db()
        assert contributed.notes == "Bob's" and contributed.trip_id == trip.pk


def test_trip_edited_in_the_app_goes_to_review(alice):
    trip = import_once(alice)
    with rls_context(alice.user.pk):
        services.update_trip(alice.user, trip, {"title": "Renamed in the app"})
    stops_before, legs_before = trip_rows(alice.user, trip)
    batch_id = upload(alice, workbook({"Loop": changed_rows()}), name="v2.xlsx")
    view = preview(alice, batch_id)
    assert view["tabs"][0]["outcome"] == "review"
    result = commit(alice, batch_id, seen=seen(view))
    assert result["results"][0]["outcome"] == "review"
    stops, legs = trip_rows(alice.user, trip)
    assert trip.title == "Renamed in the app" and trip.needs_review
    assert [(s.pk, s.notes) for s in stops] == [(s.pk, s.notes) for s in stops_before]
    assert [leg.pk for leg in legs] == [leg.pk for leg in legs_before]
    with rls_context(alice.user.pk):
        flag = ReviewFlag.objects.get(trip=trip)
    assert flag.reason == "source_changed" and flag.details["import_batch_id"] == batch_id
    assert flag.details["diff"]["stops"]["added"][0]["name"] == "Twin Synth"
    # One open flag per trip and content hash.
    again = upload(alice, workbook({"Loop": changed_rows()}), name="v3.xlsx")
    commit(alice, again, seen=seen(preview(alice, again)))
    with rls_context(alice.user.pk):
        assert ReviewFlag.objects.filter(trip=trip).count() == 1


def test_saved_route_version_counts_as_an_app_edit(alice):
    trip = import_once(alice)
    _, legs = trip_rows(alice.user, trip)
    with as_owner():
        RouteFactory(leg=legs[1], created_by=alice.user)
    batch_id = upload(alice, workbook({"Loop": changed_rows()}), name="v2.xlsx")
    assert preview(alice, batch_id)["tabs"][0]["outcome"] == "review"


def test_deleted_trip_is_skipped_unless_recreated(alice):
    trip = import_once(alice)
    with rls_context(alice.user.pk):
        services.delete_trip(trip)
    batch_id = upload(alice, workbook({"Loop": changed_rows()}), name="v2.xlsx")
    view = preview(alice, batch_id)
    assert view["tabs"][0]["outcome"] == "deleted" and view["tabs"][0]["trip_id"] is None
    result = commit(alice, batch_id, seen=seen(view))
    assert result["results"][0]["outcome"] == "skipped"
    with rls_context(alice.user.pk):
        assert not Trip.objects.exists()
    again = upload(alice, workbook({"Loop": example()}), name="v3.xlsx")
    view = preview(alice, again)
    result = commit(alice, again, seen=seen(view), recreate=[view["tabs"][0]["record_id"]])
    assert result["results"][0]["outcome"] == "created"
    with rls_context(alice.user.pk):
        link = TripSheetLink.objects.get(owner=alice.user)
        assert link.trip_id == result["results"][0]["trip_id"]


def test_unknown_people_need_the_create_option(alice):
    rows = example(fields={**FIELDS, "People": "me; Pat Synth"})
    batch_id = upload(alice, workbook({"Loop": rows}))
    view = preview(alice, batch_id)
    (tab,) = view["tabs"]
    assert tab["outcome"] == "blocked" and not tab["can_commit"]
    assert tab["unknown_people"] == ["Pat Synth"]
    assert commit(alice, batch_id, records=[tab["record_id"]], expect=422)["records"] == [
        tab["record_id"]
    ]
    result = commit(alice, batch_id, create_people=[tab["record_id"]])
    assert result["results"][0]["outcome"] == "created"
    with rls_context(alice.user.pk):
        pat = Person.objects.get(display_name="Pat Synth")
        trip = Trip.objects.get(pk=result["results"][0]["trip_id"])
        assert TripParticipant.objects.filter(trip=trip, person=pat).exists()
    assert pat.created_by_id == alice.user.pk


def test_leg_people_overrides(alice):
    with as_owner():
        PersonFactory(created_by=alice.user, display_name="Pat Example")
    legs = [*LEGS[:2], leg("", "springs", 10, "drive", "2015-06-14 09:00", people="Pat Example")]
    trip = import_once(alice, example(fields={**FIELDS, "People": "me"}, legs=legs))
    _, imported = trip_rows(alice.user, trip)
    with rls_context(alice.user.pk):
        part = services.participation(trip, imported)
        pat = Person.objects.get(display_name="Pat Example")
    assert part.legs[imported[2].pk] == {pat.pk}  # exactly these people on that leg
    assert part.legs[imported[0].pk] == {alice.user.person_id}


def test_stale_preview_is_refused(alice):
    trip = import_once(alice)
    batch_id = upload(alice, workbook({"Loop": changed_rows()}), name="v2.xlsx")
    view = preview(alice, batch_id)
    with rls_context(alice.user.pk):
        services.touch(trip, in_app=False)  # changed after the preview, not edited in the app
    response = commit(alice, batch_id, expect=409, seen=seen(view))
    assert response["records"] == [view["tabs"][0]["record_id"]]
    stops, _ = trip_rows(alice.user, trip)
    assert len(stops) == 4  # nothing written


def test_discard_ends_the_batch(alice):
    batch_id = upload(alice, workbook({"Loop": example()}))
    assert alice.post(f"{API}/imports/{batch_id}/discard").status_code == 204
    assert preview(alice, batch_id)["status"] == "discarded"
    commit(alice, batch_id, expect=409)
    with rls_context(alice.user.pk):
        assert ImportBatch.objects.get(pk=batch_id).raw_file_id is not None  # the file stays


def test_trip_sheet_upload_limit(alice):
    response = alice.post(
        f"{API}/uploads",
        {"filename": "big.xlsx", "size": 10 * 1024 * 1024 + 1, "kind": "trip_sheet"},
        content_type="application/json",
    )
    assert response.status_code == 413


def test_unreadable_file_fails_cleanly(alice):
    batch_id = upload(alice, b"SYNTHETIC not a spreadsheet\n" * 10, name="trips.xlsx")
    with rls_context(alice.user.pk):
        batch = ImportBatch.objects.get(pk=batch_id)
    assert batch.status == "failed" and "not an .xlsx file" in batch.error
    with as_owner():
        assert not TripSheetRecord.objects.exists()


def test_template_download(alice):
    response = alice.get(f"{API}/trips/sheet-template.xlsx")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    assert b"".join(response.streaming_content)[:2] == b"PK"


def test_command_previews_and_commits_as_the_user(alice, tmp_path, capsys):
    path = tmp_path / "trips.xlsx"
    path.write_bytes(workbook({"Loop": example(), "Broken": example(fields={"Title": "x"})}))
    with as_owner():
        call_command("trips_sheet_import", alice.user.email, str(path))
    out = capsys.readouterr().out
    assert "'Loop' (key 'synth-loop'): new" in out and "'Broken' (key 'broken'): blocked" in out
    report = (tmp_path / "trips.report.csv").read_text(encoding="utf-8")
    assert report.splitlines()[0] == "tab,row,column,severity,reason,message,hint"
    assert "Broken" in report and "bad_reference" in report
    with as_owner():
        assert not Trip.objects.exists()
        call_command("trips_sheet_import", alice.user.email, str(path), "--commit")
    out = capsys.readouterr().out
    assert "identical file: showing the open preview" in out and "'Loop': created" in out
    with as_owner():
        trip = Trip.objects.get()
        assert (trip.owner_id, trip.source) == (alice.user.pk, "sheet_import")
        assert path.read_bytes()[:2] == b"PK"  # the input is only read


def test_command_refuses_viewers(tmp_path):
    with as_owner():
        viewer = UserFactory(role=Role.VIEWER)
    path = tmp_path / "trips.xlsx"
    path.write_bytes(workbook({"Loop": example()}))
    with as_owner(), pytest.raises(CommandError):
        call_command("trips_sheet_import", viewer.email, str(path))
