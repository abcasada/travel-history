"""Move a new account's Authentik sign-in onto the existing account (G-3, item 40c, D-104;
travel.accounts.handover). Owner role only:

  ./dev prod manage rebind_identity                     list the accounts
  ./dev prod manage rebind_identity NEW OLD             dry run: what would change
  ./dev prod manage rebind_identity NEW OLD --execute   do it (one transaction)

NEW is the empty account Authentik's first sign-in created, OLD the account holding the data.
Accounts are chosen by id; nothing is ever matched by email."""

from django.core.management.base import BaseCommand, CommandError

from travel.accounts import handover


class Command(BaseCommand):
    help = "Move the sign-in identity of a new, empty account onto an existing account."

    def add_arguments(self, parser):
        parser.add_argument("new", nargs="?", type=int, help="id of the new, empty account")
        parser.add_argument("old", nargs="?", type=int, help="id of the account with the data")
        parser.add_argument("--execute", action="store_true", help="commit (default: dry run)")

    def handle(self, *_args, new, old, execute, **_options):
        try:
            handover.require_owner_role()
            if new is None and old is None:
                self._list()
                return
            if new is None or old is None:
                raise CommandError("give both account ids: NEW OLD (no ids lists the accounts)")
            report = handover.rebind_identity(new, old, execute=execute)
        except handover.Refused as exc:
            raise CommandError(f"refused: {exc}") from exc
        source, target = report.source, report.target
        out = self.stdout.write
        out(f"{'Executed' if report.executed else 'Dry run (nothing changed; add --execute)'}:")
        out(f"  account {target['id']} ({target['display_name']}, {target['role']}) keeps all")
        out(f"    its rows: {_rows(report.target_rows)}")
        out(f"  its sign-in identity {target['issuer'] or '(none)'} {_short(target['subject'])}")
        out(f"    becomes {source['issuer']} {_short(source['subject'])} (name and email too)")
        out(f"  account {source['id']} is deleted, with {_rows(report.discarded) or 'no rows'}")
        out(f"  sessions deleted: {report.sessions_deleted} (both accounts sign in again)")

    def _list(self):
        self.stdout.write("Accounts (NEW = the empty Authentik account, OLD = the one with data):")
        self.stdout.write(
            f"  {'id':>4}  {'role':<7} {'active':<6} {'created':<16} {'rows':>9}  name / identity"
        )
        for row in handover.account_rows():
            self.stdout.write(
                f"  {row['id']:>4}  {row['role']:<7} {'yes' if row['active'] else 'no':<6} "
                f"{row['created']:%Y-%m-%d %H:%M} {row['rows']:>9}  {row['display_name']} / "
                f"{row['issuer'] or '(no identity)'}"
            )


def _short(subject: str) -> str:
    return f"(subject {subject[:8]}…)" if subject else ""


def _rows(counts: dict[str, int]) -> str:
    return ", ".join(f"{key} {n}" for key, n in sorted(counts.items()))
