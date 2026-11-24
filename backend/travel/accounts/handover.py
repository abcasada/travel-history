"""Server-side account repairs for go-live (work-order item 40c, G-3, D-104), run as the owner
role through `./dev prod manage` (or `./dev manage`). Never reachable from the app.

- `rebind_identity`: Adam's first Authentik sign-in creates a new, empty account, because
  accounts are matched by (issuer, subject) and never by email. This moves that Authentik
  identity (issuer, subject, email, name) onto the existing account that holds his data, so
  every row stays where it is, then deletes the empty account and both accounts' sessions.
- `link_person`: links a family member's new account to the person Adam already put on trips
  (the onboarding step of auth.md §7.3, pulled forward): trips default to `participants`
  visibility (permissions.md §6.2), so an unlinked account can't see the trips it is on.
- `deactivate_account` (F-3, D-108): ends someone's access now, not at the next provider check:
  the account is deactivated (it then reads nothing, D-53, and its tracker tokens stop working)
  and every session it has is deleted. `--reactivate` undoes it; `--sign-out` only deletes the
  sessions (a lost phone of someone who keeps their access).

Both pick accounts and persons by id only, check everything first, refuse anything outside
their one case (`Refused`, nothing changed), run in one transaction, append to the audit log
and log a line. Without `execute` they run the same steps and roll back (a dry run), so the
report shows exactly what an executed run would do.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.db import connection, transaction

from travel.core.devcopy import foreign_keys
from travel.trips.models import Purpose

from . import oidc, provisioning
from .models import AuditLog, DeviceToken, Person, Role, User

log = logging.getLogger(__name__)

# Guard triggers exempt this role, and row-level security doesn't apply to it (tables aren't
# FORCEd, D-23); as travel_app the deletes below would silently match no rows.
OWNER_ROLE = "travel_owner"
USER_TABLE = User._meta.db_table
# What a first sign-in leaves behind on a new account and nothing else does: the default
# purposes (provisioning.seed_defaults) and UI preferences (split-pane width and the like).
SCAFFOLD_PURPOSE_NAMES = frozenset(name for name, _visibility in provisioning.DEFAULT_PURPOSES)
PURPOSE_FK = (Purpose._meta.db_table, "owner_id")
PREFERENCE_FK = ("accounts_userpreference", "user_id")
SCAFFOLD_FKS = frozenset(f"{table}.{column}" for table, column in (PURPOSE_FK, PREFERENCE_FK))
IDENTITY_FIELDS = ("issuer", "subject", "email", "display_name")


class Refused(Exception):
    """The command must not go ahead; the message says why. Nothing was changed."""


def require_owner_role() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        role = cursor.fetchone()[0]
    if role != OWNER_ROLE:
        raise Refused(
            f"runs only as the owner role {OWNER_ROLE} (./dev prod manage …), not as {role}"
        )


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def owned_rows(user_id: int) -> dict[str, int]:
    """Rows that refer to the account, per `table.column`, over every foreign key to
    accounts_user that PostgreSQL knows (not a hand-kept list, so new tables count too)."""
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for fk in foreign_keys():
            if fk.parent != USER_TABLE or fk.table == USER_TABLE:
                continue
            cursor.execute(
                f"SELECT count(*) FROM {_q(fk.table)} WHERE {_q(fk.column)} = %s",  # noqa: S608 - catalog names
                [user_id],
            )
            count = cursor.fetchone()[0]
            if count:
                counts[f"{fk.table}.{fk.column}"] = count
    return counts


def _rows_referring_to(table: str, ids: list[int]) -> dict[str, int]:
    """Rows in other tables that refer to these rows of `table`."""
    counts: dict[str, int] = {}
    if not ids:
        return counts
    with connection.cursor() as cursor:
        for fk in foreign_keys():
            if fk.parent != table:
                continue
            cursor.execute(
                f"SELECT count(*) FROM {_q(fk.table)} WHERE {_q(fk.column)} = ANY(%s)",  # noqa: S608 - catalog names
                [ids],
            )
            count = cursor.fetchone()[0]
            if count:
                counts[f"{fk.table}.{fk.column}"] = count
    return counts


def session_keys(user_ids: set[int]) -> list[str]:
    """Sessions signed in as any of these accounts (the user id lives inside the signed session
    data, so every session is decoded; one that doesn't decode can't sign anyone in)."""
    wanted = {str(user_id) for user_id in user_ids}
    return [
        session.session_key
        for session in Session.objects.iterator()
        if str(session.get_decoded().get(SESSION_KEY, "")) in wanted
    ]


def _audit(action: str, object_id: int, details: dict) -> None:
    AuditLog.objects.create(
        actor=None,
        action=action,
        object_type="accounts.user",
        object_id=str(object_id),
        details=details,
    )


# --- rebind_identity --------------------------------------------------------------------------


@dataclass
class RebindReport:
    source: dict
    target: dict
    discarded: dict[str, int]
    target_rows: dict[str, int]
    sessions_deleted: int = 0
    executed: bool = False


def _identity(user: User) -> dict:
    return {
        "id": user.pk,
        "issuer": user.oidc_issuer,
        "subject": user.oidc_sub,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
    }


def _check_rebind(source: User, target: User) -> dict[str, int]:
    """Raises Refused unless `source` is a brand-new account that owns nothing and carries an
    identity from the configured provider, and `target` may take that identity. Returns the
    scaffolding rows the source's deletion discards."""
    provider = _configured_issuer()
    if not (source.oidc_sub and source.oidc_issuer):
        raise Refused(f"account {source.pk} has no sign-in identity to move")
    if not oidc.same_issuer(source.oidc_issuer, provider):
        raise Refused(
            f"account {source.pk}'s identity comes from {source.oidc_issuer}, not from the "
            f"configured provider {provider}"
        )
    if source.role != Role.MEMBER or not source.is_active:
        raise Refused(
            f"account {source.pk} is not a new account (role {source.role}, "
            f"{'active' if source.is_active else 'deactivated'}); new accounts are active Members"
        )
    if source.person_id is not None:
        raise Refused(f"account {source.pk} is linked to person {source.person_id}")
    if source.created_at <= target.created_at:
        raise Refused(
            f"account {source.pk} is older than account {target.pk}; the identity moves from the "
            "new account onto the existing one"
        )
    rows = owned_rows(source.pk)
    owned = {key: n for key, n in rows.items() if key not in SCAFFOLD_FKS}
    if owned:
        listing = ", ".join(f"{key}: {n}" for key, n in sorted(owned.items()))
        raise Refused(f"account {source.pk} owns data ({listing}); it is not an empty account")
    purposes = list(Purpose.objects.filter(owner_id=source.pk).values_list("pk", "name"))
    extra = sorted(name for _pk, name in purposes if name not in SCAFFOLD_PURPOSE_NAMES)
    if extra:
        raise Refused(f"account {source.pk} has its own purposes ({', '.join(extra)})")
    used = _rows_referring_to(PURPOSE_FK[0], [pk for pk, _name in purposes])
    if used:
        listing = ", ".join(f"{key}: {n}" for key, n in sorted(used.items()))
        raise Refused(f"account {source.pk}'s default purposes are in use ({listing})")

    if not target.is_active:
        raise Refused(f"account {target.pk} is deactivated")
    if target.oidc_issuer.startswith("https://") or oidc.same_issuer(target.oidc_issuer, provider):
        raise Refused(
            f"account {target.pk} already has a real sign-in identity ({target.oidc_issuer}); "
            "moving another onto it would lock that login out"
        )
    return {key: n for key, n in rows.items() if key in SCAFFOLD_FKS}


def _configured_issuer() -> str:
    if not settings.OIDC_ISSUER:
        raise Refused("no sign-in provider is configured (OIDC_ISSUER)")
    return settings.OIDC_ISSUER


def rebind_identity(source_id: int, target_id: int, *, execute: bool) -> RebindReport:
    """Move the sign-in identity of the new, empty account `source_id` onto the existing
    account `target_id`, delete `source_id` and both accounts' sessions."""
    require_owner_role()
    if source_id == target_id:
        raise Refused("the two accounts are the same")
    with transaction.atomic():
        users = {
            u.pk: u for u in User.objects.select_for_update().filter(pk__in=[source_id, target_id])
        }
        for pk in (source_id, target_id):
            if pk not in users:
                raise Refused(f"no account {pk}")
        source, target = users[source_id], users[target_id]
        discarded = _check_rebind(source, target)
        before = owned_rows(target.pk)
        report = RebindReport(
            source=_identity(source),
            target=_identity(target),
            discarded=discarded,
            target_rows=before,
        )

        keys = session_keys({source.pk, target.pk})
        Session.objects.filter(session_key__in=keys).delete()
        report.sessions_deleted = len(keys)
        with connection.cursor() as cursor:
            for table, column in (PREFERENCE_FK, PURPOSE_FK):
                cursor.execute(f"DELETE FROM {_q(table)} WHERE {_q(column)} = %s", [source.pk])  # noqa: S608 - fixed names
            # The source goes first: the identity and the email are unique.
            cursor.execute(f"DELETE FROM {_q(USER_TABLE)} WHERE id = %s", [source.pk])  # noqa: S608 - fixed name
            cursor.execute(
                f"UPDATE {_q(USER_TABLE)} SET oidc_issuer = %s, oidc_sub = %s, email = %s, "  # noqa: S608 - fixed name
                "display_name = %s WHERE id = %s",
                [source.oidc_issuer, source.oidc_sub, source.email, source.display_name, target.pk],
            )
        if owned_rows(target.pk) != before:
            raise Refused("the existing account's rows changed; rolled back")  # can't happen
        moved = {name: report.source[name] for name in IDENTITY_FIELDS}
        _audit(
            "rebind_identity",
            target.pk,
            {
                "deleted_account": source.pk,
                "before": report.target,
                "after": {**report.target, **moved},
                "sessions_deleted": report.sessions_deleted,
                "discarded": discarded,
            },
        )
        report.executed = execute
        if not execute:
            transaction.set_rollback(True)
    log.info(
        "rebind_identity %s: identity of account %s (%s) moved onto account %s; account %s and "
        "%s session(s) deleted",
        "executed" if execute else "dry run",
        source.pk,
        source.oidc_issuer,
        target.pk,
        source.pk,
        report.sessions_deleted,
    )
    return report


# --- link_person ------------------------------------------------------------------------------


@dataclass
class LinkReport:
    account: dict
    person: dict
    trips: dict[str, int] = field(default_factory=dict)
    already_linked: bool = False
    executed: bool = False


def trips_of_person(person_id: int) -> dict[str, int]:
    """Trips the person is an effective participant of (trip-level, or included on a leg; the
    same test as app.is_trip_participant), per visibility."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT t.visibility, count(*) FROM trips_trip t
             WHERE EXISTS (SELECT 1 FROM trips_tripparticipant p
                            WHERE p.trip_id = t.id AND p.person_id = %(person)s)
                OR EXISTS (SELECT 1 FROM trips_legparticipantoverride o
                             JOIN trips_leg l ON l.id = o.leg_id
                            WHERE l.trip_id = t.id AND o.person_id = %(person)s AND o.include)
             GROUP BY 1 ORDER BY 1
            """,
            {"person": person_id},
        )
        return dict(cursor.fetchall())


def link_person(account_id: int, person_id: int, *, execute: bool) -> LinkReport:
    """Link account `account_id` to the existing person `person_id`."""
    require_owner_role()
    with transaction.atomic():
        account = User.objects.select_for_update().filter(pk=account_id).first()
        if account is None:
            raise Refused(f"no account {account_id}")
        person = Person.objects.select_for_update().filter(pk=person_id).first()
        if person is None:
            raise Refused(f"no person {person_id}")
        linked_to = User.objects.filter(person_id=person.pk).exclude(pk=account.pk).first()
        report = LinkReport(
            account={"id": account.pk, "display_name": account.display_name, "role": account.role},
            person={
                "id": person.pk,
                "display_name": person.display_name,
                "created_by": person.created_by_id,
            },
            trips=trips_of_person(person.pk),
        )
        if account.person_id == person.pk:
            report.already_linked = True
            return report
        if not account.is_active:
            raise Refused(f"account {account.pk} is deactivated")
        if linked_to is not None:
            raise Refused(f"person {person.pk} is already linked to account {linked_to.pk}")
        if account.person_id is not None:
            raise Refused(
                f"account {account.pk} is already linked to person {account.person_id}; "
                "an account links to one person"
            )
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {_q(USER_TABLE)} SET person_id = %s WHERE id = %s",  # noqa: S608 - fixed name
                [person.pk, account.pk],
            )
        _audit(
            "link_person",
            account.pk,
            {"person": person.pk, "person_created_by": person.created_by_id, "trips": report.trips},
        )
        report.executed = execute
        if not execute:
            transaction.set_rollback(True)
    log.info(
        "link_person %s: account %s linked to person %s",
        "executed" if execute else "dry run",
        account.pk,
        person.pk,
    )
    return report


# --- deactivate_account -----------------------------------------------------------------------

DEACTIVATE, REACTIVATE, SIGN_OUT = "deactivate", "reactivate", "sign-out"
ACCOUNT_ACTIONS = {
    DEACTIVATE: "deactivate_account",
    REACTIVATE: "reactivate_account",
    SIGN_OUT: "sign_out_account",
}


@dataclass
class DeactivateReport:
    account: dict
    change: str
    sessions: int = 0
    live_tokens: int = 0
    already: bool = False
    executed: bool = False


def deactivate_account(
    account_id: int, *, execute: bool, change: str = DEACTIVATE
) -> DeactivateReport:
    """Deactivate account `account_id` and delete its sessions (`change` = DEACTIVATE),
    activate it again (REACTIVATE) or only delete its sessions (SIGN_OUT)."""
    require_owner_role()
    if change not in ACCOUNT_ACTIONS:
        raise Refused(f"unknown change {change!r}")
    with transaction.atomic():
        account = User.objects.select_for_update().filter(pk=account_id).first()
        if account is None:
            raise Refused(f"no account {account_id}")
        report = DeactivateReport(
            account={
                "id": account.pk,
                "display_name": account.display_name,
                "role": account.role,
                "active": account.is_active,
            },
            change=change,
            live_tokens=DeviceToken.objects.filter(
                user_id=account.pk, revoked_at__isnull=True
            ).count(),
        )
        if (change == DEACTIVATE and not account.is_active) or (
            change == REACTIVATE and account.is_active
        ):
            report.already = True
            return report
        if change == DEACTIVATE and account.role == Role.ADMIN:
            others = User.objects.filter(role=Role.ADMIN, is_active=True).exclude(pk=account.pk)
            if not others.exists():
                raise Refused(
                    f"account {account.pk} is the only active Admin; deactivating it would "
                    "leave nobody to run the app (use --sign-out to end its sessions)"
                )
        if change != REACTIVATE:
            keys = session_keys({account.pk})
            Session.objects.filter(session_key__in=keys).delete()
            report.sessions = len(keys)
        if change != SIGN_OUT:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {_q(USER_TABLE)} SET is_active = %s WHERE id = %s",  # noqa: S608 - fixed name
                    [change == REACTIVATE, account.pk],
                )
        _audit(
            ACCOUNT_ACTIONS[change],
            account.pk,
            {
                "was_active": account.is_active,
                "role": account.role,
                "sessions_deleted": report.sessions,
                "live_tokens": report.live_tokens,
            },
        )
        report.executed = execute
        if not execute:
            transaction.set_rollback(True)
    log.info(
        "deactivate_account %s: %s account %s; %s session(s) deleted",
        "executed" if execute else "dry run",
        change,
        account.pk,
        report.sessions,
    )
    return report


def sessions_per_account() -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for session in Session.objects.iterator():
        user_id = session.get_decoded().get(SESSION_KEY)
        if user_id:
            counts[int(user_id)] += 1
    return dict(counts)


# --- listings (what the operator picks ids from) ---------------------------------------------


def account_rows() -> list[dict]:
    totals: dict[int, int] = defaultdict(int)
    with connection.cursor() as cursor:
        for fk in foreign_keys():
            if fk.parent != USER_TABLE or fk.table == USER_TABLE:
                continue
            cursor.execute(
                f"SELECT {_q(fk.column)}, count(*) FROM {_q(fk.table)} "  # noqa: S608 - catalog names
                f"WHERE {_q(fk.column)} IS NOT NULL GROUP BY 1"
            )
            for user_id, count in cursor.fetchall():
                totals[user_id] += count
    return [
        {
            "id": user.pk,
            "role": user.role,
            "active": user.is_active,
            "created": user.created_at,
            "display_name": user.display_name,
            "issuer": user.oidc_issuer,
            "person": user.person_id,
            "rows": totals.get(user.pk, 0),
        }
        for user in User.objects.order_by("pk")
    ]


def unlinked_persons() -> list[dict]:
    linked = set(User.objects.exclude(person=None).values_list("person_id", flat=True))
    return [
        {
            "id": person.pk,
            "display_name": person.display_name,
            "created_by": person.created_by_id,
            "trips": sum(trips_of_person(person.pk).values()),
        }
        for person in Person.objects.order_by("pk")
        if person.pk not in linked
    ]
