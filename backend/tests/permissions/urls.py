"""Test-only URLs for exercising the request middleware."""

from django.http import JsonResponse
from django.urls import path

from travel.accounts.models import User, UserDirectory
from travel.core.rls import get_context
from travel.trips.models import Trip


def visible_trips(request):
    uid, ctx = get_context()
    return JsonResponse(
        {
            "user": request.user.pk,
            "rls_user": uid,
            "ctx": ctx,
            "trips": sorted(Trip.objects.values_list("pk", flat=True)),
        }
    )


def visible_accounts(request):
    """What a request can read about accounts: full rows vs the family directory."""
    return JsonResponse(
        {
            "accounts": list(User.objects.order_by("pk").values("pk", "email", "oidc_sub")),
            "directory": list(
                UserDirectory.objects.order_by("pk").values("pk", "display_name", "is_active")
            ),
        }
    )


# Under a public prefix so anonymous requests reach the view (the login wall would redirect).
urlpatterns = [path("t/probe", visible_trips), path("t/accounts", visible_accounts)]
