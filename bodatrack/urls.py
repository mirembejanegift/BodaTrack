"""Top-level URL configuration: admin plus the /api/ surface."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("tracker.urls")),
]
