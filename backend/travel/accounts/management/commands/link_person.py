"""Link a family member's account to the person already on their trips (item 40c, D-101,
auth.md §7.3; travel.accounts.handover). Owner role only, like set_role:

  ./dev prod manage link_person                              list accounts and unlinked persons
  ./dev prod manage link_person ACCOUNT PERSON               dry run
  ./dev prod manage link_person ACCOUNT PERSON --execute     link them (one transaction)

Both are ids. Until linked, the account can't see trips with `participants` visibility that
the person is on (permissions.md §6.2)."""

from django.core.management.base import BaseCommand, CommandError

from travel.accounts import handover


class Command(BaseCommand):
    help = "Link an account to an existing person (both by id)."

    def add_arguments(self, parser):
        parser.add_argument("account", nargs="?", type=int, help="account id")
        parser.add_argument("person", nargs="?", type=int, help="person id")
        parser.add_argument("--execute", action="store_true", help="commit (default: dry run)")

    def handle(self, *_args, account, person, execute, **_options):
        try:
            handover.require_owner_role()
            if account is None and person is None:
                self._list()
                return
            if account is None or person is None:
                raise CommandError("give both ids: ACCOUNT PERSON (no ids lists them)")
            report = handover.link_person(account, person, execute=execute)
        except handover.Refused as exc:
            raise CommandError(f"refused: {exc}") from exc
        acc, per = report.account, report.person
        trips = ", ".join(f"{n} {visibility}" for visibility, n in report.trips.items()) or "none"
        if report.already_linked:
            self.stdout.write(f"account {acc['id']} is already linked to person {per['id']}")
            return
        self.stdout.write(
            f"{'Executed' if report.executed else 'Dry run (nothing changed; add --execute)'}:\n"
            f"  account {acc['id']} ({acc['display_name']}, {acc['role']}) -> person {per['id']} "
            f"({per['display_name']}, created by account {per['created_by']})\n"
            f"  the person's trips: {trips}; the account now manages this person"
        )

    def _list(self):
        self.stdout.write("Accounts:")
        for row in handover.account_rows():
            person = f"person {row['person']}" if row["person"] else "no person"
            self.stdout.write(
                f"  {row['id']:>4}  {row['role']:<7} {row['display_name']} ({person}"
                f"{'' if row['active'] else ', deactivated'})"
            )
        self.stdout.write("Persons without an account:")
        for row in handover.unlinked_persons():
            self.stdout.write(
                f"  {row['id']:>4}  {row['display_name']} (created by account "
                f"{row['created_by']}, on {row['trips']} trips)"
            )
