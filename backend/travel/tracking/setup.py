"""Setup links and QR codes for each tracker app (PLAN.md §9.2, guides in docs/tracking/).

They carry the token, so they exist only in the response that creates it: nothing here is
stored, and the frontend shows them once. QR codes are SVG data URIs (rendered with `<img>`,
so the page's content security policy needs nothing new).

GPSLogger has no link: its setup link (`gpslogger://properties/<https URL>`) makes the phone
download a settings file from a URL, which would mean serving the token from a public address.
Its fields are listed for copying instead, with a QR code of the token alone (PLAN.md Q-17).
"""

from __future__ import annotations

import base64
import io
import json
import re
from urllib.parse import quote, urlencode

import qrcode
import qrcode.image.svg
from django.conf import settings
from django.http import HttpRequest
from django.views.decorators.debug import sensitive_variables
from pydantic import BaseModel

from travel.accounts.models import DeviceToken

OWNTRACKS_PATH = "/api/v1/ingest/owntracks"
OVERLAND_PATH = "/api/v1/ingest/overland"
BASIC_USERNAME = "travel"  # any name works; the token is the password
GPSLOGGER_BODY = (
    '{"_type":"location","lat":%LAT,"lon":%LON,"tst":%TIMESTAMP,"acc":%ACC,"alt":%ALT,'
    '"vel":%SPD_KPH,"batt":%BATT,"tid":"gl"}'
)


class Setup(BaseModel):
    """How to point one tracker app at this server. `link` and both QR codes contain the
    token; none of this can be shown again."""

    tracker: str
    endpoint: str
    auth: str  # "basic" (any user name, the token as password) or "bearer"
    username: str | None = None
    link: str | None = None
    link_qr: str | None = None
    token_qr: str
    body_template: str | None = None
    content_type: str = "application/json"


def base_url(request: HttpRequest) -> str:
    """Where trackers send points: `TRACKER_BASE_URL` once the endpoints are reachable from
    outside (work-order item 8), otherwise the address this page was opened at."""
    configured = settings.TRACKER_BASE_URL.rstrip("/")
    return configured or request.build_absolute_uri("/").rstrip("/")


def device_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:32] or "phone"


def tracker_id(name: str) -> str:
    letters = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    return (letters[:2] or "TR").ljust(2, "X")


def qr_data_uri(text: str) -> str:
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


@sensitive_variables()
def build(token: DeviceToken, secret: str, base: str) -> Setup:
    owntracks_url = base + OWNTRACKS_PATH
    overland_url = base + OVERLAND_PATH
    kind = token.kind
    link = None
    if kind == DeviceToken.Kind.OWNTRACKS:
        config = {
            "_type": "configuration",
            "mode": 3,  # HTTP
            "url": owntracks_url,
            "auth": True,
            "username": BASIC_USERNAME,
            "password": secret,
            "deviceId": device_id(token.name),
            "tid": tracker_id(token.name),
            "monitoring": 1,  # significant changes: light on the battery
        }
        link = "owntracks:///config?inline=" + quote(_b64_json(config), safe="")
        setup = Setup(
            tracker=kind, endpoint=owntracks_url, auth="basic", username=BASIC_USERNAME, token_qr=""
        )
    elif kind == DeviceToken.Kind.OVERLAND:
        query = {"url": overland_url, "token": secret, "device_id": device_id(token.name)}
        link = "overland://setup?" + urlencode(query)
        setup = Setup(tracker=kind, endpoint=overland_url, auth="bearer", token_qr="")
    elif kind == DeviceToken.Kind.COLOTA:
        # Colota's OwnTracks template: its fields are documented, so they pass strict checks.
        config = {
            "endpoint": owntracks_url,
            "apiTemplate": "owntracks",
            "httpMethod": "POST",
            "auth": {"type": "bearer", "bearerToken": secret},
        }
        link = "colota://setup?config=" + quote(_b64_json(config), safe="")
        setup = Setup(tracker=kind, endpoint=owntracks_url, auth="bearer", token_qr="")
    elif kind == DeviceToken.Kind.GPSLOGGER:
        setup = Setup(
            tracker=kind,
            endpoint=owntracks_url,
            auth="basic",
            username=BASIC_USERNAME,
            body_template=GPSLOGGER_BODY,
            token_qr="",
        )
    else:
        setup = Setup(tracker=kind, endpoint=owntracks_url, auth="bearer", token_qr="")
    return setup.model_copy(
        update={
            "link": link,
            "link_qr": qr_data_uri(link) if link else None,
            "token_qr": qr_data_uri(secret),
        }
    )


def _b64_json(config: dict) -> str:
    raw = json.dumps(config, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")
