import datetime as dt

from django.utils import timezone
from ninja import Router, Schema

router = Router(tags=["me"])


class MeOut(Schema):
    id: int
    email: str
    display_name: str
    role: str
    person_id: int | None
    privacy_notice_ack_at: dt.datetime | None
    onboarding_done_at: dt.datetime | None


@router.get("/me", response=MeOut)
def me(request):
    return request.user


@router.post("/me/privacy-ack", response=MeOut)
def acknowledge_privacy_notice(request):
    """The honesty notice (PLAN.md §6.7) is acknowledged once."""
    user = request.user
    if user.privacy_notice_ack_at is None:
        user.privacy_notice_ack_at = timezone.now()
        user.save(update_fields=["privacy_notice_ack_at"])
    return user
