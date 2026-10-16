from django.urls import path

from . import views

app_name = "access"

urlpatterns = [path("", views.status, name="status")]
