import datetime as dt
import json
import re
from typing import Any

from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.errors import HttpError

from travel.core.choices import DeviceClass

from .models import UserPreference

router = Router(tags=["me"])


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
