"""Turning verified OIDC claims into a local user (PLAN.md §7.1). Runs in the narrow `auth`
RLS context: users are matched by (issuer, subject) only - never linked by email."""

from __future__ import annotations

from django.conf import settings

from travel.core.rls import set_context
from travel.trips.models import Purpose

from .models import Role, User

DEFAULT_PURPOSES = (
    ("Work", "private"),
    ("Vacation", "participants"),
    ("Family visit", "participants"),
    ("Outdoors/Camping", "participants"),
    ("Event", "participants"),
    ("Moving", "participants"),
    ("Other", "participants"),
)


class AccessDenied(Exception):
    """The identity is valid but may not use this app (wrong group, deactivated, conflict)."""


def has_required_group(claims: dict) -> bool:
    required = settings.OIDC_REQUIRED_GROUP
    if not required:
        return True
    groups = claims.get("groups") or []
    return required in groups


def user_for_claims(claims: dict) -> User:
    """Find or create the user for verified ID-token claims. Must run inside the request
    transaction; leaves the RLS context set to the returned user."""
    if not has_required_group(claims):
        raise AccessDenied("not in the group for this app")
    issuer, subject = claims["iss"], claims["sub"]
    email = (claims.get("email") or "").strip().lower()
    name = claims.get("name") or claims.get("preferred_username") or email

    set_context(None, ctx="auth")
    user = User.objects.filter(oidc_issuer=issuer, oidc_sub=subject).first()
    if user is None:
        if not email:
            raise AccessDenied("the identity provider sent no email address")
        if User.objects.filter(email__iexact=email).exists():
            raise AccessDenied("an account with this email already exists; ask the Admin")
        user = User(
            email=email,
            display_name=name,
            role=Role.MEMBER,
            oidc_issuer=issuer,
            oidc_sub=subject,
        )
        user.set_unusable_password()  # OIDC only
        user.save()
        created = True
    else:
        if not user.is_active:
            raise AccessDenied("this account is deactivated")
        changed = []
        if (
            email
            and user.email != email
            and not User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists()
        ):
            user.email, changed = email, [*changed, "email"]
        if name and user.display_name != name:
            user.display_name, changed = name, [*changed, "display_name"]
        if changed:
            user.save(update_fields=changed)
        created = False

    set_context(user.pk)
    if created:
        seed_defaults(user)
    return user


def seed_defaults(user: User) -> None:
    if user.role == Role.VIEWER:
        return
    for sort, (name, visibility) in enumerate(DEFAULT_PURPOSES):
        Purpose.objects.get_or_create(
            owner=user, name=name, defaults={"default_visibility": visibility, "sort": sort}
        )
