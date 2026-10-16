from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("unlock/", views.pay, name="pay"),
    path("history/", views.history, name="history"),
    path("status/<uuid:reference>/", views.payment_status, name="status"),
    path("api/status/<uuid:reference>/", views.payment_status_api, name="status_api"),
    path("mpesa/callback/<str:token>/", views.mpesa_callback, name="mpesa_callback"),
]
