from django.urls import path

from travel.core import views as core_views

urlpatterns = [
    path("healthz", core_views.healthz, name="healthz"),
]
