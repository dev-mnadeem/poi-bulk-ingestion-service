"""URL configuration.

This service has no public HTTP surface. The Django admin is the only
interface; data enters through ``manage.py import_poi``.
"""

from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
