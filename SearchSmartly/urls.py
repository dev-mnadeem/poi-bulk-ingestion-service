"""URL configuration.

This service has no public HTTP surface. The Django admin is the only
interface; data enters through ``manage.py import_poi``.
"""

from django.contrib import admin
from django.urls import path

admin.site.site_header = "PoI importer"
admin.site.site_title = "PoI importer admin"
admin.site.index_title = "Imported data"
# There is no public site behind the admin, so its "View site" link only led
# to a 404 at "/".
admin.site.site_url = None

urlpatterns = [
    path("admin/", admin.site.urls),
]
