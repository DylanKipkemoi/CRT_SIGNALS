from decimal import Decimal

from django.db.models import Avg, Count, Q

from .models import Outcome, SignalStatus, TradingSignal

WIN_OUTCOMES = [Outcome.TP1, Outcome.TP2, Outcome.TP3]


def performance_stats(instrument=None, include_sample=False):
    """Outcome statistics over ALL published (non-provisional) signals — no cherry-picking."""
    qs = TradingSignal.objects.filter(is_provisional=False)
    if not include_sample:
        qs = qs.filter(is_sample=False)
    if instrument is not None:
        qs = qs.filter(instrument=instrument)
    agg = qs.aggregate(
        total=Count("id"),
        open=Count("id", filter=Q(status__in=[SignalStatus.ACTIVE, SignalStatus.TRIGGERED])),
        wins=Count("id", filter=Q(status=SignalStatus.CLOSED, outcome__in=WIN_OUTCOMES)),
        losses=Count("id", filter=Q(status=SignalStatus.CLOSED, outcome=Outcome.STOP)),
        timeouts=Count("id", filter=Q(status=SignalStatus.CLOSED, outcome=Outcome.TIMEOUT)),
        expired=Count("id", filter=Q(status=SignalStatus.EXPIRED)),
        invalidated=Count("id", filter=Q(status=SignalStatus.INVALIDATED)),
        avg_r=Avg("realized_r", filter=Q(status=SignalStatus.CLOSED)),
    )
    decided = agg["wins"] + agg["losses"] + agg["timeouts"]
    agg["closed"] = decided
    agg["win_rate"] = round(agg["wins"] / decided * 100, 1) if decided else None
    agg["avg_r"] = Decimal(agg["avg_r"]).quantize(Decimal("0.01")) if agg["avg_r"] is not None else None
    return agg
