from ninja import NinjaAPI

from travel.accounts.api import router as accounts_router
from travel.core import ratelimit
from travel.core.api_auth import API_AUTH
from travel.history.api import router as history_router
from travel.trips.api import router as trips_router

api = NinjaAPI(
    title="Travel History API",
    version="1",
    urls_namespace="api",
    auth=API_AUTH,  # every endpoint requires a user unless it explicitly opts out
)
ratelimit.install(api)  # RateLimited raised in an endpoint -> 429 + Retry-After
api.add_router("/", accounts_router)
api.add_router("/", history_router)
api.add_router("/", trips_router)
