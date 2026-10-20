"""Bootstrap/repair roles from the server (runs as the owner role via ./dev manage):
    ./dev manage set_role adam@example.com admin
In-app, only the Admin changes roles (enforced by the database guard)."""

from django.core.management.base import BaseCommand, CommandError

from travel.accounts.models import Role, User


class Command(BaseCommand):
    help = "Set a user's role (admin, member, viewer)."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("role", choices=[r.value for r in Role])

    def handle(self, *_args, email, role, **_options):
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f"no user with email {email!r} (they must sign in once first)")
        user.role = role
        user.save(update_fields=["role"])
        self.stdout.write(self.style.SUCCESS(f"{user.email} is now {role}"))
