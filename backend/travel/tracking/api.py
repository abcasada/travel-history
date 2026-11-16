"""Device-token management (PLAN.md §9.1, matrix §6.3 "Device tokens").

    GET  /api/v1/tracking/tokens               own tokens (never the token itself)
    POST /api/v1/tracking/tokens               new token: shown once, with setup links/QR
    POST /api/v1/tracking/tokens/{id}/revoke   final; the tracker gets 401 from then on

Members and the Admin manage their own tokens; Viewers can list theirs (left from when they
were Members; they write nothing) but not create or revoke; nobody sees anyone else's,
including the Admin. Row-level security enforces the same (core migration 0002, accounts
migration 0004).
"""

import datetime as dt
from enum import StrEnum
from typing import Annotated

from django.conf import settings
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from ninja import Router, Schema, Status
from ninja.errors import HttpError
from pydantic import StringConstraints

from travel.accounts.models import DeviceToken
from travel.core import policy

from . import setup, tokens

router = Router(tags=["tracking"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# The tracker app a token is for (`DeviceToken.Kind`), under a name of its own in the schema.
TrackerKind = StrEnum("TrackerKind", {kind.name: kind.value for kind in DeviceToken.Kind})


class DeviceTokenOut(Schema):
    id: int
    name: str
    kind: TrackerKind
    token_prefix: str
    created_at: dt.datetime
    last_used_at: dt.datetime | None
    revoked_at: dt.datetime | None
    points_received: int


class DeviceTokenIn(Schema):
    name: Name
    kind: TrackerKind


class DeviceTokenCreatedOut(Schema):
    device: DeviceTokenOut
    token: str  # the only time it is ever shown
    setup: setup.Setup


@router.get("/tracking/tokens", response=list[DeviceTokenOut], operation_id="listDeviceTokens")
def list_tokens(request):
    if not policy.can_list_device_tokens(request.user):
        raise HttpError(403, "no access")
    return DeviceToken.objects.filter(user_id=request.user.pk).order_by("-created_at", "-id")


@router.post(
    "/tracking/tokens", response={201: DeviceTokenCreatedOut}, operation_id="createDeviceToken"
)
@sensitive_variables()
def create_token(request, payload: DeviceTokenIn):
    user = request.user
    if not policy.can_create_device_token(user):
        raise HttpError(403, "your role cannot record location history")
    live = DeviceToken.objects.filter(user_id=user.pk, revoked_at__isnull=True).count()
    if live >= settings.TRACKER_MAX_TOKENS_PER_USER:
        raise HttpError(409, "too many active tokens; revoke one you no longer use")
    new = tokens.generate()
    device = DeviceToken.objects.create(
        user=user,
        name=payload.name,
        kind=payload.kind,
        token_prefix=new.display_prefix,
        token_hash=new.token_hash,
    )
    built = setup.build(device, new.secret, setup.base_url(request))
    return Status(201, {"device": device, "token": new.secret, "setup": built})


@router.post(
    "/tracking/tokens/{token_id}/revoke",
    response=DeviceTokenOut,
    operation_id="revokeDeviceToken",
)
def revoke_token(request, token_id: int):
    device = DeviceToken.objects.filter(pk=token_id, user_id=request.user.pk).first()
    if device is None:
        raise HttpError(404, "not found")
    if not policy.can_revoke_device_token(request.user, device):
        raise HttpError(403, "your role cannot revoke tokens")
    if device.revoked_at is None:
        device.revoked_at = timezone.now()
        device.save(update_fields=["revoked_at"])
    return device
