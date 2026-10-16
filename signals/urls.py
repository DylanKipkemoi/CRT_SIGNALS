from django.urls import path

from . import views

app_name = "signals"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("<int:pk>/", views.signal_detail, name="detail"),
    path("<int:pk>/unlock-free/", views.unlock_free, name="unlock_free"),
    path("api/chart/<str:symbol>/", views.chart_data, name="chart_data"),
    path("<str:symbol>/", views.instrument_signals, name="instrument"),
]
