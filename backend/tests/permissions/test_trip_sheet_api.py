"""Trip spreadsheet imports (item 14c-1, trip-sheet.md §28.10) for every actor of the synthetic
family: a batch's preview, commit and discard are its owner's alone (not even the Admin's), the
upload kind is refused to Viewers like other imports, and the template is open to every
signed-in family member. The SQL/RLS layer is checked as `travel_app` below and case by case in
test_matrix.py."""

import pytest
from django.db import DatabaseError, transaction

from tests.helpers import as_owner
from travel.core.rls import set_context
from travel.history.models import ImportBatch
from travel.trips.models import Trip, TripSheetLink, TripSheetRecord

pytestmark = pytest.mark.django_db

ACTORS = ("admin", "alice", "bob", "carol", "victor", "ivan", "anon")
API = "/api/v1"


def client_for(client, f, actor):
    if actor != "anon":
        with as_owner():
            client.force_login(getattr(f, actor))
    return client


def expected(actor, owner_status):
    if actor in ("ivan", "anon"):
        return 401
    return owner_status if actor == "alice" else 404


@pytest.mark.parametrize("actor", ACTORS)
def test_preview(client, scenario, actor):
    response = client_for(client, scenario, actor).get(
        f"{API}/imports/{scenario.alice_sheet_batch.pk}/trip-sheet"
    )
    assert response.status_code == expected(actor, 200)
    if actor == "alice":
        (tab,) = response.json()["tabs"]
        assert (tab["outcome"], tab["trip_id"]) == ("identical", scenario.trips["family"].pk)


@pytest.mark.parametrize("actor", ACTORS)
def test_commit(client, scenario, actor):
    response = client_for(client, scenario, actor).post(
        f"{API}/imports/{scenario.alice_sheet_batch.pk}/commit", {}, content_type="application/json"
    )
    assert response.status_code == expected(actor, 200)
    with as_owner():
        record = TripSheetRecord.objects.get(pk=scenario.alice_sheet_record.pk)
        batch = ImportBatch.objects.get(pk=scenario.alice_sheet_batch.pk)
    if actor == "alice":
        assert (record.outcome, batch.status) == ("identical", "done")
    else:
        assert (record.outcome, batch.status) == ("", "preview")


@pytest.mark.parametrize("actor", ACTORS)
def test_discard(client, scenario, actor):
    response = client_for(client, scenario, actor).post(
        f"{API}/imports/{scenario.alice_sheet_batch.pk}/discard"
    )
    assert response.status_code == expected(actor, 204)
    with as_owner():
        status = ImportBatch.objects.get(pk=scenario.alice_sheet_batch.pk).status
    assert status == ("discarded" if actor == "alice" else "preview")


@pytest.mark.parametrize("actor", ACTORS)
def test_upload_kind(client, scenario, actor, settings, tmp_path):
    settings.BULK_DIR = tmp_path
    response = client_for(client, scenario, actor).post(
        f"{API}/uploads",
        {"filename": "trips.xlsx", "size": 5000, "kind": "trip_sheet"},
        content_type="application/json",
    )
    statuses = {"victor": 403, "ivan": 401, "anon": 401}
    assert response.status_code == statuses.get(actor, 201)


@pytest.mark.parametrize("actor", ACTORS)
def test_template(client, scenario, actor):
    response = client_for(client, scenario, actor).get(f"{API}/trips/sheet-template.xlsx")
    assert response.status_code == (401 if actor in ("ivan", "anon") else 200)


# --- As travel_app ----------------------------------------------------------------------------


def _refused(fn) -> bool:
    try:
        with transaction.atomic():
            fn()
    except DatabaseError:
        return True
    return False


def test_a_record_needs_the_owners_own_batch(scenario):
    f = scenario
    set_context(f.bob.pk)
    assert _refused(
        lambda: TripSheetRecord.objects.create(
            owner=f.bob,
            import_batch=f.alice_sheet_batch,
            tab_name="x",
            position=9,
            key="x",
            content={},
            content_hash="f" * 64,
        )
    )
    # Nor may a record point at someone else's trip.
    assert _refused(
        lambda: TripSheetRecord.objects.filter(pk=f.bob_sheet_record.pk).update(
            trip=f.trips["family"]
        )
    )


def test_only_the_outcome_of_a_record_changes(scenario):
    f = scenario
    set_context(f.alice.pk)
    assert TripSheetRecord.objects.filter(pk=f.alice_sheet_record.pk).update(
        outcome="updated", trip=f.trips["family"]
    )
    for change in ({"content": {}}, {"key": "other"}, {"issues": [1]}, {"content_hash": "0" * 64}):
        assert _refused(
            lambda change=change: TripSheetRecord.objects.filter(pk=f.alice_sheet_record.pk).update(
                **change
            )
        )


def test_a_link_outlives_its_trip(scenario):
    f = scenario
    set_context(f.alice.pk)
    trip = Trip.objects.create(
        owner=f.alice, title="Short-lived", start_date="2020-01-01", end_date="2020-01-02"
    )
    link = TripSheetLink.objects.create(owner=f.alice, key="short", trip=trip)
    record = TripSheetRecord.objects.create(
        owner=f.alice,
        import_batch=f.alice_sheet_batch,
        tab_name="Short",
        position=3,
        key="short",
        content={},
        content_hash="f" * 64,
        trip=trip,
    )
    Trip.objects.filter(pk=trip.pk).delete()
    link.refresh_from_db()
    record.refresh_from_db()
    assert link.trip_id is None and record.trip_id is None  # remembered: a re-import skips it


def test_nobody_else_reads_or_changes_a_link(scenario):
    f = scenario
    for actor in (f.admin, f.bob, f.carol, f.victor):
        set_context(actor.pk)
        assert not TripSheetLink.objects.filter(pk=f.alice_sheet_link.pk).exists()
        assert TripSheetLink.objects.filter(pk=f.alice_sheet_link.pk).update(trip=None) == 0
        assert TripSheetLink.objects.filter(pk=f.alice_sheet_link.pk).delete()[0] == 0
    # Alice can't move her link to the Admin's trip either.
    set_context(f.alice.pk)
    assert _refused(
        lambda: TripSheetLink.objects.filter(pk=f.alice_sheet_link.pk).update(
            trip=f.admin_private_trip
        )
    )
