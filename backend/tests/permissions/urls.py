"""Test-only URLs for exercising the request middleware."""

from django.http import JsonResponse
from django.urls import path

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


# Under a public prefix so anonymous requests reach the view (the login wall would redirect).
urlpatterns = [path("t/probe", visible_trips)]
