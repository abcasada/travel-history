from django.urls import path, re_path

from config.api import api
from travel.accounts import views as auth_views
from travel.core import spa
from travel.core import views as core_views
from travel.tracking import views as tracking_views

urlpatterns = [
    path("", auth_views.landing_view, name="landing"),
    path("healthz", core_views.healthz, name="healthz"),
    path("auth/login", auth_views.login_view, name="auth-login"),
    path("auth/callback", auth_views.callback_view, name="auth-callback"),
    path("auth/logout", auth_views.logout_view, name="auth-logout"),
    path("auth/reauth", auth_views.reauth_view, name="auth-reauth"),
    # Tracker ingestion: device tokens, not sessions (PLAN.md §9.1). Before the JSON API, whose
    # prefix they share. A trailing slash is accepted: some apps add one.
    re_path(r"^api/v1/ingest/owntracks/?$", tracking_views.owntracks, name="ingest-owntracks"),
    re_path(r"^api/v1/ingest/overland/?$", tracking_views.overland, name="ingest-overland"),
    path("api/v1/", api.urls),
    re_path(r"^app/(?P<path>.*)$", spa.spa_index, name="spa"),
]
