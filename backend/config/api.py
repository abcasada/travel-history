from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from ninja import NinjaAPI

from travel.accounts.api import people_router
from travel.accounts.api import router as accounts_router
from travel.core import ratelimit
from travel.core.api_auth import API_AUTH
from travel.flights.api import router as flights_router
from travel.geo.api import router as geo_router
from travel.history.api import router as history_router
from travel.routing.api import router as routing_router
from travel.tracking.api import router as tracking_router
from travel.trips.api import router as trips_router


def signed_in_only(view):
    """The interactive docs and the schema need a signed-in browser session. A Bearer header
    gets past the login wall for the API's own auth classes, which these two views don't use
    (F-7, D-107); `export_openapi` builds the schema without them."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "authentication required"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


# Production serves neither (F-7): the schema is in the repository, and nobody browses the docs
# there.
_SCHEMA_URL = None if settings.TRAVEL_PRODUCTION else "/openapi.json"

api = NinjaAPI(
    title="Travel History API",
    version="1",
    urls_namespace="api",
    auth=API_AUTH,  # every endpoint requires a user unless it explicitly opts out
    openapi_url=_SCHEMA_URL,
    docs_url="/docs",  # registered only with the schema URL
    docs_decorator=signed_in_only,
)
ratelimit.install(api)  # RateLimited raised in an endpoint -> 429 + Retry-After
api.add_router("/", accounts_router)
api.add_router("/", people_router)
api.add_router("/", history_router)
api.add_router("/", trips_router)
api.add_router("/", tracking_router)
api.add_router("/", flights_router)
api.add_router("/", geo_router)
api.add_router("/", routing_router)
