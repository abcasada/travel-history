from django.urls import path

from config.api import api
from travel.accounts import views as auth_views
from travel.core import views as core_views

urlpatterns = [
    path("", auth_views.landing_view, name="landing"),
    path("healthz", core_views.healthz, name="healthz"),
    path("auth/login", auth_views.login_view, name="auth-login"),
    path("auth/callback", auth_views.callback_view, name="auth-callback"),
    path("auth/logout", auth_views.logout_view, name="auth-logout"),
    path("auth/reauth", auth_views.reauth_view, name="auth-reauth"),
    path("api/v1/", api.urls),
]
