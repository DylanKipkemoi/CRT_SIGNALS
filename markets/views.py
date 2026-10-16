from django.shortcuts import render

from signals.scanner import scanner_health
from signals.views import _instrument_cards


def overview(request):
    return render(request, "markets/overview.html", {"cards": _instrument_cards(), "health": scanner_health()})
