from django.urls import path

from . import staff_views

app_name = "staff"

urlpatterns = [
    path("", staff_views.staff_dashboard, name="dashboard"),
    path("scan/", staff_views.manual_scan, name="manual_scan"),
]
