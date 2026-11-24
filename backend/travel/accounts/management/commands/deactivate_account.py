"""End someone's access now (F-3, D-108; travel.accounts.handover). Owner role only, like
set_role:

  ./dev prod manage deactivate_account                          list the accounts
  ./dev prod manage deactivate_account ACCOUNT                  dry run: what would change
  ./dev prod manage deactivate_account ACCOUNT --execute        deactivate it, delete its sessions
  ./dev prod manage deactivate_account ACCOUNT --reactivate --execute    let it in again
  ./dev prod manage deactivate_account ACCOUNT --sign-out --execute      only end its sessions

Removing someone from `travel-users` in Authentik ends their access within the hour by itself
(sessions go back through Authentik, OIDC_SESSION_RECHECK_SECONDS); this ends it at once. A
deactivated account reads nothing and its tracker tokens stop working; its data stays."""

from django.core.management.base import BaseCommand, CommandError

from travel.accounts import handover


class Command(BaseCommand):
    help = "Deactivate an account (by id) and delete its sessions, or reactivate it."

    def add_arguments(self, parser):
        parser.add_argument("account", nargs="?", type=int, help="account id")
        change = parser.add_mutually_exclusive_group()
        change.add_argument("--reactivate", action="store_true", help="activate it again")
        change.add_argument("--sign-out", action="store_true", help="only delete its sessions")
        parser.add_argument("--execute", action="store_true", help="commit (default: dry run)")

    def handle(self, *_args, account, reactivate, sign_out, execute, **_options):
        change = (
            handover.REACTIVATE
            if reactivate
            else handover.SIGN_OUT
            if sign_out
            else handover.DEACTIVATE
        )
        try:
            handover.require_owner_role()
            if account is None:
                self._list()
                return
            report = handover.deactivate_account(account, execute=execute, change=change)
        except handover.Refused as exc:
            raise CommandError(f"refused: {exc}") from exc
        acc = report.account
        who = f"account {acc['id']} ({acc['display_name']}, {acc['role']})"
        if report.already:
            state = "deactivated" if change == handover.DEACTIVATE else "active"
            self.stdout.write(f"{who} is already {state}; nothing changed")
            return
        out = self.stdout.write
        out(f"{'Executed' if report.executed else 'Dry run (nothing changed; add --execute)'}:")
        if change == handover.DEACTIVATE:
            out(f"  {who} is deactivated: it reads nothing and can't sign in; its data stays")
        elif change == handover.REACTIVATE:
            out(f"  {who} is active again (it signs in through Authentik as before)")
        if change != handover.REACTIVATE:
            out(f"  sessions deleted: {report.sessions}")
        tokens = report.live_tokens
        if tokens and change == handover.DEACTIVATE:
            out(f"  {tokens} tracker token(s) stop working while it is deactivated")
        elif tokens:
            out(f"  {tokens} live tracker token(s): revoke a lost phone's on Location trackers")

    def _list(self):
        sessions = handover.sessions_per_account()
        self.stdout.write("Accounts:")
        self.stdout.write(f"  {'id':>4}  {'role':<7} {'active':<6} {'sessions':>8}  name")
        for row in handover.account_rows():
            self.stdout.write(
                f"  {row['id']:>4}  {row['role']:<7} {'yes' if row['active'] else 'no':<6} "
                f"{sessions.get(row['id'], 0):>8}  {row['display_name']}"
            )
