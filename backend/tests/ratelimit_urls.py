"""Test-only endpoints for the rate limiter, under a public prefix (the login wall lets them
through) on their own Ninja API."""

from django.urls import path
from ninja import NinjaAPI

from travel.core import ratelimit
from travel.core.ratelimit import Rate

api = NinjaAPI(urls_namespace="ratelimit-test", auth=None, docs_url=None)
ratelimit.install(api)


@api.get("/decorated", operation_id="rlDecorated")
@ratelimit.limit("test-decorated", Rate(limit=2, period=60))
def decorated(request, q: int = 0):
    return {"q": q}


@api.post("/enforced/{name}", operation_id="rlEnforced")
def enforced(request, name: str):
    ratelimit.enforce("test-enforced", name, Rate(limit=1, period=60))
    return {"name": name}


urlpatterns = [path("t/rl/", api.urls)]
