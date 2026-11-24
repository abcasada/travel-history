import datetime as dt
import json
import re
from enum import StrEnum
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from ninja import Field, Router, Schema, Status
from ninja.decorators import decorate_view
from ninja.errors import HttpError

from travel.core import policy
from travel.core.choices import DeviceClass

from .models import Person, UserDirectory, UserPreference

router = Router(tags=["me"])
people_router = Router(tags=["people"])


class MeOut(Schema):
    id: int
    email: str
    display_name: str
    role: str
    person_id: int | None
    privacy_notice_ack_at: dt.datetime | None
    onboarding_done_at: dt.datetime | None


@router.get("/me", response=MeOut, operation_id="getMe")
@decorate_view(ensure_csrf_cookie)  # the SPA reads the CSRF token from this cookie
def me(request):
    return request.user


@router.post("/me/privacy-ack", response=MeOut, operation_id="acknowledgePrivacyNotice")
def acknowledge_privacy_notice(request):
    """The honesty notice (PLAN.md §6.7) is acknowledged once."""
    user = request.user
    if user.privacy_notice_ack_at is None:
        user.privacy_notice_ack_at = timezone.now()
        user.save(update_fields=["privacy_notice_ack_at"])
    return user


# --- Preferences (split-pane width per device class, shell override, …) ----------------------

PREFERENCE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_PREFERENCE_BYTES = 4096


class PreferenceIn(Schema):
    value: Any
    device_class: DeviceClass = DeviceClass.ANY


@router.get("/preferences", response=dict[str, Any], operation_id="listPreferences")
def list_preferences(request, device_class: DeviceClass = DeviceClass.ANY):
    """Values for `any`, overridden by values stored for the given device class."""
    rows = UserPreference.objects.filter(
        user=request.user, device_class__in={DeviceClass.ANY, device_class}
    )
    merged: dict[str, Any] = {}
    for row in sorted(rows, key=lambda r: r.device_class != DeviceClass.ANY):
        merged[row.key] = row.value
    return merged


@router.put("/preferences/{key}", response=dict[str, Any], operation_id="setPreference")
def set_preference(request, key: str, payload: PreferenceIn):
    if not PREFERENCE_KEY.match(key):
        raise HttpError(422, "invalid preference key")
    if len(json.dumps(payload.value)) > MAX_PREFERENCE_BYTES:
        raise HttpError(422, "preference value too large")
    UserPreference.objects.update_or_create(
        user=request.user,
        key=key,
        device_class=payload.device_class,
        defaults={"value": payload.value},
    )
    return {key: payload.value}


# --- People (participant picker; PLAN.md §17 "People") ------------------------------------------


class PersonOut(Schema):
    id: int
    display_name: str
    visibility: str
    is_me: bool = Field(description="the caller's own person")
    has_account: bool = Field(description="linked to a family account")
    can_edit: bool = Field(
        description="the caller may rename this person: their managing user, or the Admin"
    )
    manages: bool = Field(description="the caller is this person's managing user")


# Schema names come from class names; Person.Visibility would clash with the trips' Visibility.
PersonVisibility = StrEnum("PersonVisibility", [(v.upper(), v) for v in Person.Visibility.values])


class PersonIn(Schema):
    display_name: str = Field(min_length=1, max_length=150)
    visibility: PersonVisibility = PersonVisibility.FAMILY


class PersonPatchIn(Schema):
    """Only the fields sent are changed."""

    display_name: str | None = Field(None, min_length=1, max_length=150)
    visibility: PersonVisibility | None = None


def _people_out(user, people: list[Person]) -> list[dict]:
    linked = dict(
        UserDirectory.objects.filter(person_id__in=[p.pk for p in people]).values_list(
            "person_id", "id"
        )
    )
    rows = []
    for p in people:
        manages = linked[p.pk] == user.pk if p.pk in linked else p.created_by_id == user.pk
        rows.append(
            {
                "id": p.pk,
                "display_name": p.display_name,
                "visibility": p.visibility,
                "is_me": p.pk == user.person_id,
                "has_account": p.pk in linked,
                # The same rule as policy.can_edit_person, from rows already loaded: every
                # person listed is visible, so only the role and the managing user matter.
                "can_edit": policy.can_create(user) and (manages or policy.is_admin(user)),
                "manages": manages and policy.is_family(user),
            }
        )
    return rows


@people_router.get("/persons", response=list[PersonOut], operation_id="listPersons")
def list_persons(request):
    """People the caller can see (row-level security; the policy agrees), own person first."""
    user = request.user
    people = [
        p for p in Person.objects.order_by("display_name", "pk") if policy.can_view_person(user, p)
    ]
    people.sort(key=lambda p: p.pk != user.person_id)
    return _people_out(user, people)


@people_router.post("/persons", response={201: PersonOut}, operation_id="createPerson")
def create_person(request, payload: PersonIn):
    """A traveller without an account (a child, a friend); the caller manages them."""
    if not policy.can_create_person(request.user):
        raise HttpError(403, "your role cannot add people")
    person = Person.objects.create(
        display_name=payload.display_name.strip(),
        visibility=payload.visibility,
        created_by=request.user,
    )
    return Status(201, _people_out(request.user, [person])[0])


@people_router.patch("/persons/{person_id}", response=PersonOut, operation_id="updatePerson")
def update_person(request, person_id: int, payload: PersonPatchIn):
    """Rename a person or change who sees them: their managing user or the Admin. A person
    the caller can't see answers 404."""
    user = request.user
    person = Person.objects.filter(pk=person_id).first()
    if person is None or not policy.can_view_person(user, person):
        raise HttpError(404, "person not found")
    if not policy.can_edit_person(user, person):
        raise HttpError(403, "only the person's managing user or the Admin can change them")
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HttpError(422, "fields cannot be null")
    if "display_name" in changes:
        person.display_name = changes["display_name"].strip()
        if not person.display_name:
            raise HttpError(422, "display_name cannot be blank")
    if "visibility" in changes:
        person.visibility = changes["visibility"]
    if changes:
        person.save(update_fields=[*changes, "updated_at"])
    return _people_out(user, [person])[0]


@router.post("/me/person", response={201: MeOut}, operation_id="createMyPerson")
def create_my_person(request):
    """Make the caller a traveller: a new person linked to their account (once). Until then
    they can't be put on a trip, so trips aren't shared with them as a participant."""
    user = request.user
    if not policy.can_create_person(user):
        raise HttpError(403, "your role cannot add people")
    if not policy.can_create_own_person(user):
        raise HttpError(409, "your account already has a person")
    with transaction.atomic():
        user.person = Person.objects.create(display_name=user.display_name or "Me", created_by=user)
        user.save(update_fields=["person"])
    return Status(201, user)
