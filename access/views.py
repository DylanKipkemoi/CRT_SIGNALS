from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import DailySignalAccess
from .services import access_summary


@login_required
def status(request):
    return render(request, "access/status.html", {
        "summary": access_summary(request.user),
        "accesses": DailySignalAccess.objects.filter(user=request.user)[:30],
    })
