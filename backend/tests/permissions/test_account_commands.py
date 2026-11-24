"""The owner-role account commands for go-live (work-order item 40c-1, D-101):
`rebind_identity` (G-3) and `link_person` (auth.md §7.3's linking step, pulled forward).

The commands run as the owner role, as `./dev prod manage` runs them. Everything checked
afterwards is read as `travel_app` under row-level security, the way the app sees it: the
existing account keeps every row, sessions are gone, a linked account sees the trips its person
is on. Each refusal leaves the database exactly as it was, and as `travel_app` neither command,
nor the statements it runs, gets anywhere."""

import datetime as dt
import io

import pytest
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import CommandError, call_command
from django.db import connection, transaction
from django.utils import timezone

from tests.factories import (
    LegFactory,
    LocationPointFactory,
    ParticipantFactory,
    PersonFactory,
    TripFactory,
    UserFactory,
)
from tests.helpers import as_owner, current_role
from travel.accounts import handover
from travel.accounts.models import AuditLog, Person, Role, User
from travel.accounts.provisioning import seed_defaults, user_for_claims
from travel.core.rls import rls_context
from travel.history.models import LocationPoint
from travel.trips.models import Purpose, Trip

pytestmark = pytest.mark.django_db

AUTHENTIK = "https://auth.example.org/application/o/travel-history/"
MOCK = "http://192.0.2.10:8781/default"  # the dev mock provider, as the copied account has it
BACKEND = "django.contrib.auth.backends.ModelBackend"


def authentik_claims(sub: str, email: str, name: str) -> dict:
    return {
        "iss": AUTHENTIK,
        "sub": sub,
        "email": email,
        "email_verified": False,
        "name": name,
        "groups": ["travel-users"],
        "amr": ["pwd", "mfa"],
        "auth_time": int(timezone.now().timestamp()),
    }


def first_sign_in(claims: dict) -> User:
    """What the callback does at a first Authentik sign-in, as travel_app."""
    with rls_context(None):
        return user_for_claims(claims)


def sign_in_session(user: User) -> str:
    session = SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = BACKEND
    session.create()
    return session.session_key


@pytest.fixture
def provider(settings):
    settings.OIDC_ISSUER = AUTHENTIK
    settings.OIDC_REQUIRED_GROUP = "travel-users"
    settings.OIDC_SECOND_FACTOR_AMR = ["mfa", "user"]
    return settings


@pytest.fixture
def world(provider):
    """Production right after Adam's first Authentik sign-in (40c-3's starting point): the
    account copied from dev (`dev-admin`, Admin, the mock's identity, all the data), the empty
    account Authentik's sign-in just created, and a family member with a session."""
    with as_owner():
        old = UserFactory(
            email="dev-admin@example.test",
            display_name="Dev Admin",
            role=Role.ADMIN,
            oidc_issuer=MOCK,
            oidc_sub="dev-admin",
        )
        User.objects.filter(pk=old.pk).update(created_at=timezone.now() - dt.timedelta(days=30))
        old.refresh_from_db()
        seed_defaults(old)
        old.person = PersonFactory(created_by=old, display_name="Dev Admin")
        old.save(update_fields=["person"])
        trip = TripFactory(owner=old, visibility="private")
        LegFactory(trip=trip)
        for _ in range(3):
            LocationPointFactory(owner=old)
        family = UserFactory(display_name="Synthetic Relative")
    new = first_sign_in(authentik_claims("hashed-subject-1", "adam@example.org", "Synthetic Adam"))
    sessions = {
        "old": sign_in_session(old),
        "new": sign_in_session(new),
        "family": sign_in_session(family),
    }
    return {"old": old, "new": new, "family": family, "sessions": sessions}


def run(command: str, *args, owner: bool = True) -> str:
    out = io.StringIO()
    if owner:
        with as_owner():
            call_command(command, *[str(arg) for arg in args], stdout=out)
    else:
        call_command(command, *[str(arg) for arg in args], stdout=out)
    return out.getvalue()


def accounts() -> list[tuple]:
    with as_owner():
        return list(
            User.objects.order_by("pk").values_list(
                "pk",
                "email",
                "display_name",
                "role",
                "oidc_issuer",
                "oidc_sub",
                "person_id",
                "is_active",
                "created_at",
            )
        )


def database_state() -> tuple:
    """Everything a command might touch, read as the owner role."""
    with as_owner():
        rows = {pk: handover.owned_rows(pk) for pk, *_rest in accounts()}
        return (
            accounts(),
            rows,
            sorted(Session.objects.values_list("session_key", flat=True)),
            AuditLog.objects.count(),
        )


def seen_by(user_id: int) -> dict:
    """What the app shows this account, as travel_app under its RLS context."""
    assert current_role() == "travel_app"
    with rls_context(user_id):
        me = User.objects.filter(pk=user_id).values("email", "role", "oidc_issuer").first()
        return {
            "me": me,
            "trips": sorted(Trip.objects.values_list("pk", flat=True)),
            "points": LocationPoint.objects.count(),
            "purposes": Purpose.objects.filter(owner_id=user_id).count(),
            "persons": sorted(Person.objects.values_list("pk", flat=True)),
        }


# --- rebind_identity ---------------------------------------------------------------------------


def test_the_listing_shows_both_accounts(world):
    output = run("rebind_identity")
    assert f"{world['old'].pk:>4}  admin" in output
    assert f"{world['new'].pk:>4}  member" in output
    assert MOCK in output
    assert AUTHENTIK in output


def test_the_dry_run_reports_and_changes_nothing(world):
    before, seen = database_state(), seen_by(world["old"].pk)
    output = run("rebind_identity", world["new"].pk, world["old"].pk)
    assert "Dry run" in output
    assert "becomes " + AUTHENTIK in output
    assert "sessions deleted: 2" in output
    assert "trips_purpose.owner_id 7" in output  # the new account's default purposes
    assert database_state() == before
    assert seen_by(world["old"].pk) == seen


def test_rebind_moves_the_identity_and_every_row_stays(world):
    old, new = world["old"], world["new"]
    seen = seen_by(old.pk)
    assert seen["points"] == 3 and len(seen["trips"]) == 1 and seen["purposes"] == 7
    with as_owner():
        rows = handover.owned_rows(old.pk)

    output = run("rebind_identity", new.pk, old.pk, "--execute")
    assert output.startswith("Executed")

    with as_owner():
        assert not User.objects.filter(pk=new.pk).exists()
        moved = User.objects.get(pk=old.pk)
        assert handover.owned_rows(old.pk) == rows
        assert not Purpose.objects.filter(owner_id=new.pk).exists()
        (entry,) = AuditLog.objects.filter(action="rebind_identity")
    assert (moved.oidc_issuer, moved.oidc_sub) == (AUTHENTIK, "hashed-subject-1")
    assert (moved.email, moved.display_name) == ("adam@example.org", "Synthetic Adam")
    assert (moved.role, moved.person_id, moved.created_at) == (
        Role.ADMIN,
        old.person_id,
        old.created_at,
    )
    assert entry.actor_id is None
    assert entry.object_id == str(old.pk)
    assert entry.details["deleted_account"] == new.pk
    assert entry.details["before"]["issuer"] == MOCK
    assert entry.details["after"]["subject"] == "hashed-subject-1"

    # As the app sees it: the same rows, the new identity, both accounts signed out.
    after = seen_by(old.pk)
    assert after == {
        **seen,
        "me": {**seen["me"], "email": "adam@example.org", "oidc_issuer": AUTHENTIK},
    }
    sessions = set(Session.objects.values_list("session_key", flat=True))
    assert sessions == {world["sessions"]["family"]}

    # Adam's next Authentik sign-in lands on the account with the data; nothing new is made.
    signed_in = first_sign_in(
        authentik_claims("hashed-subject-1", "adam@example.org", "Synthetic Adam")
    )
    assert signed_in.pk == old.pk
    assert signed_in.role == Role.ADMIN
    assert len(accounts()) == 2


def refuse(command: str, *args, match: str, owner: bool = True) -> None:
    before = database_state()
    with pytest.raises(CommandError, match=match):
        run(command, *args, owner=owner)
    assert database_state() == before


def _owner_update(model, pk, **values):
    with as_owner():
        model.objects.filter(pk=pk).update(**values)


@pytest.mark.parametrize(
    ("change", "args", "match"),
    [
        (None, ("new", "new"), "the same"),
        (None, (999_999, "old"), "no account 999999"),
        (None, ("new", 999_999), "no account 999999"),
        (None, ("old", "new"), "not from the configured provider"),  # the wrong way round
        (lambda w: TripFactory(owner=w["new"]), ("new", "old"), "owns data .*trips_trip"),
        (lambda w: LocationPointFactory(owner=w["new"]), ("new", "old"), "owns data"),
        (
            lambda w: Purpose.objects.filter(owner=w["new"], name="Work").update(name="Consulting"),
            ("new", "old"),
            "its own purposes \\(Consulting\\)",
        ),
        (lambda w: _owner_update(User, w["new"].pk, role=Role.ADMIN), ("new", "old"), "not a new"),
        (lambda w: _owner_update(User, w["new"].pk, is_active=False), ("new", "old"), "not a new"),
        (
            lambda w: _owner_update(User, w["new"].pk, person=PersonFactory(created_by=w["old"])),
            ("new", "old"),
            "linked to person",
        ),
        (lambda w: _owner_update(User, w["new"].pk, oidc_sub=""), ("new", "old"), "no sign-in"),
        (
            lambda w: _owner_update(User, w["new"].pk, oidc_issuer="https://other.example.org/o/"),
            ("new", "old"),
            "not from the configured provider",
        ),
        (
            lambda w: _owner_update(User, w["new"].pk, created_at=w["old"].created_at),
            ("new", "old"),
            "older than",
        ),
        (
            lambda w: _owner_update(User, w["old"].pk, is_active=False),
            ("new", "old"),
            "deactivated",
        ),
        (
            lambda w: _owner_update(User, w["old"].pk, oidc_issuer=AUTHENTIK, oidc_sub="real"),
            ("new", "old"),
            "already has a real sign-in identity",
        ),
        (
            lambda w: _owner_update(User, w["old"].pk, oidc_issuer="https://elsewhere.example/"),
            ("new", "old"),
            "already has a real sign-in identity",
        ),
        (
            lambda w: _owner_update(User, w["family"].pk, created_at=timezone.now()),
            ("family", "old"),
            "not from the configured provider",  # a family member's account is never moved
        ),
    ],
    ids=[
        "same",
        "no-new",
        "no-old",
        "swapped",
        "new-owns-trip",
        "new-owns-points",
        "new-renamed-purpose",
        "new-admin",
        "new-deactivated",
        "new-has-person",
        "new-no-identity",
        "new-other-provider",
        "new-not-newer",
        "old-deactivated",
        "old-real-identity",
        "old-https-identity",
        "family-member",
    ],
)
def test_rebind_refuses_everything_else(world, change, args, match):
    if change is not None:
        with as_owner():
            change(world)
    ids = [world[arg].pk if isinstance(arg, str) else arg for arg in args]
    refuse("rebind_identity", *ids, "--execute", match=match)


def test_rebind_refuses_without_a_configured_provider(world, settings):
    settings.OIDC_ISSUER = ""
    refuse("rebind_identity", world["new"].pk, world["old"].pk, "--execute", match="OIDC_ISSUER")


def test_rebind_never_matches_by_email(world):
    """Even an empty account whose email equals the existing account's isn't picked: the ids
    are the only input (and a first sign-in with that email is refused outright)."""
    with pytest.raises(CommandError, match="both account ids"):
        run("rebind_identity", world["new"].pk)
    with pytest.raises(CommandError):
        run("rebind_identity", "dev-admin@example.test", world["old"].pk)


def test_as_travel_app_rebind_is_refused(world):
    with rls_context(world["old"].pk):  # even with the Admin's context
        refuse(
            "rebind_identity",
            world["new"].pk,
            world["old"].pk,
            "--execute",
            match="owner role",
            owner=False,
        )
        refuse("rebind_identity", match="owner role", owner=False)


def test_as_travel_app_the_rebind_statements_themselves_fail(world):
    """Row-level security and the guard triggers stop each step for the runtime role, even as
    the Admin: identities change only at sign-in, and accounts are never deleted by the app."""
    old, new = world["old"], world["new"]
    with rls_context(old.pk):
        with (
            pytest.raises(Exception, match="identity fields change only at login"),
            transaction.atomic(),
        ):
            User.objects.filter(pk=old.pk).update(oidc_sub="hashed-subject-1")
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM accounts_user WHERE id = %s", [new.pk])
            assert cursor.rowcount == 0  # no DELETE policy
    assert len(accounts()) == 3


# --- link_person -------------------------------------------------------------------------------


@pytest.fixture
def family(provider):
    """Adam put Kim on a trip before Kim had an account; Kim has now signed in once."""
    with as_owner():
        adam = UserFactory(display_name="Synthetic Adam", role=Role.ADMIN, oidc_issuer=AUTHENTIK)
        adam.person = PersonFactory(created_by=adam, display_name="Synthetic Adam")
        adam.save(update_fields=["person"])
        kim_person = PersonFactory(created_by=adam, display_name="Synthetic Kim")
        trip = TripFactory(owner=adam, visibility="participants")
        ParticipantFactory(trip=trip, person=kim_person, added_by=adam)
        TripFactory(owner=adam, visibility="private")
    kim = first_sign_in(authentik_claims("hashed-subject-kim", "kim@example.org", "Synthetic Kim"))
    return {"adam": adam, "kim_person": kim_person, "trip": trip, "kim": kim}


def test_link_person_lists_accounts_and_unlinked_persons(family):
    output = run("link_person")
    assert "Synthetic Kim (no person)" in output
    assert f"{family['kim_person'].pk:>4}  Synthetic Kim (created by account" in output
    assert "on 1 trips" in output


def test_linking_lets_the_account_see_the_trips_its_person_is_on(family):
    kim, person, trip = family["kim"], family["kim_person"], family["trip"]
    assert seen_by(kim.pk)["trips"] == []

    before = database_state()
    output = run("link_person", kim.pk, person.pk)
    assert "Dry run" in output and "1 participants" in output
    assert database_state() == before
    assert seen_by(kim.pk)["trips"] == []

    output = run("link_person", kim.pk, person.pk, "--execute")
    assert output.startswith("Executed")
    with as_owner():
        assert User.objects.get(pk=kim.pk).person_id == person.pk
        (entry,) = AuditLog.objects.filter(action="link_person")
    assert entry.details["person"] == person.pk
    assert seen_by(kim.pk)["trips"] == [trip.pk]  # under RLS, as travel_app

    before = database_state()
    assert "already linked" in run("link_person", kim.pk, person.pk, "--execute")
    assert database_state() == before


@pytest.mark.parametrize(
    ("args", "match"),
    [
        ((999_999, "kim_person"), "no account 999999"),
        (("kim", 999_999), "no person 999999"),
        (("kim", "adam_person"), "already linked to account"),
        (("adam", "kim_person"), "already linked to person"),
    ],
    ids=["no-account", "no-person", "person-taken", "account-has-person"],
)
def test_link_person_refuses_everything_else(family, args, match):
    family["adam_person"] = family["adam"].person
    ids = [family[arg].pk if isinstance(arg, str) else arg for arg in args]
    refuse("link_person", *ids, "--execute", match=match)


def test_link_person_refuses_a_deactivated_account(family):
    _owner_update(User, family["kim"].pk, is_active=False)
    refuse(
        "link_person", family["kim"].pk, family["kim_person"].pk, "--execute", match="deactivated"
    )


def test_as_travel_app_linking_is_refused(family):
    kim, person = family["kim"], family["kim_person"]
    with rls_context(family["adam"].pk):
        refuse("link_person", kim.pk, person.pk, "--execute", match="owner role", owner=False)
    # Kim can't claim the person either: the guard allows only a person the account manages.
    with rls_context(kim.pk):
        with pytest.raises(Exception, match="cannot link this account"), transaction.atomic():
            User.objects.filter(pk=kim.pk).update(person=person)
    assert seen_by(kim.pk)["trips"] == []
