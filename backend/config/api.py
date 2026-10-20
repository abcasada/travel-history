from ninja import NinjaAPI

from travel.accounts.api import router as accounts_router
from travel.core.api_auth import API_AUTH

api = NinjaAPI(
    title="Travel History API",
    version="1",
    urls_namespace="api",
    auth=API_AUTH,  # every endpoint requires a user unless it explicitly opts out
)
api.add_router("/", accounts_router)
