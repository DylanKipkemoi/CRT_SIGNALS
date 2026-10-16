from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "CRT Signals administration"
admin.site.site_title = "CRT Signals admin"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("signals/", include("signals.urls")),
    path("markets/", include("markets.urls")),
    path("access/", include("access.urls")),
    path("payments/", include("payments.urls")),
    path("staff/", include("core.staff_urls")),
    path("", include("core.urls")),
]
