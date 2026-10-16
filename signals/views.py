from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from access.services import AccessDenied, access_summary, can_view_signal, free_signal_eligible, use_free_signal
from access.models import SignalUnlock
from core.ratelimit import ratelimit
from markets.models import MarketInstrument
from markets.services import load_candles

from .models import OPEN_STATUSES, InstrumentAnalysis, SignalStatus, TradingSignal
from .scanner import scanner_health
from .services import performance_stats


def _instrument_cards():
    cards = []
    for inst in MarketInstrument.objects.filter(is_enabled=True).select_related("data_status"):
        analysis = InstrumentAnalysis.objects.filter(instrument=inst).first()
        cards.append({"instrument": inst, "status": getattr(inst, "data_status", None), "analysis": analysis})
    return cards


@login_required
def dashboard(request):
    summary = access_summary(request.user)
    active = TradingSignal.objects.filter(status__in=OPEN_STATUSES).exclude(
        status=SignalStatus.SUPERSEDED).select_related("instrument")[:20]
    rows = [{"signal": s, "unlocked": can_view_signal(request.user, s)} for s in active]
    history = SignalUnlock.objects.filter(user=request.user).select_related("signal__instrument")[:20]
    return render(request, "signals/dashboard.html", {
        "summary": summary, "cards": _instrument_cards(), "rows": rows, "history": history,
        "health": scanner_health(), "stats": performance_stats(),
    })


@login_required
def instrument_signals(request, symbol):
    inst = get_object_or_404(MarketInstrument, symbol=symbol.upper())
    qs = TradingSignal.objects.filter(instrument=inst).exclude(status=SignalStatus.SUPERSEDED)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    rows = [{"signal": s, "unlocked": can_view_signal(request.user, s, record=False)} for s in page]
    return render(request, "signals/instrument.html", {
        "instrument": inst, "status": getattr(inst, "data_status", None),
        "analysis": InstrumentAnalysis.objects.filter(instrument=inst).first(),
        "rows": rows, "page": page, "stats": performance_stats(inst), "summary": access_summary(request.user),
    })


@login_required
def signal_detail(request, pk):
    signal = get_object_or_404(TradingSignal.objects.select_related("instrument"), pk=pk)
    unlocked = can_view_signal(request.user, signal)
    ctx = {"signal": signal, "unlocked": unlocked, "summary": access_summary(request.user),
           "free_eligible": free_signal_eligible(signal)}
    if unlocked:
        ctx["events"] = signal.events.all()
        ctx["breakdown"] = signal.score_breakdown
    return render(request, "signals/detail.html", ctx)


@login_required
@require_POST
def unlock_free(request, pk):
    signal = get_object_or_404(TradingSignal, pk=pk)
    try:
        if use_free_signal(request.user, signal, request=request):
            messages.success(request, "Free signal unlocked. This signal stays available in your history.")
    except AccessDenied as exc:
        messages.error(request, str(exc))
    return redirect("signals:detail", pk=pk)


@login_required
@ratelimit("api", methods=("GET",), json=True)
def chart_data(request, symbol):
    inst = get_object_or_404(MarketInstrument, symbol=symbol.upper())
    tf = request.GET.get("tf", "1h")
    if tf not in ("5m", "15m", "1h"):
        raise Http404
    status = getattr(inst, "data_status", None)
    candles = load_candles(inst, tf, limit=300, provider=status.provider if status else None)
    data = {
        "symbol": inst.symbol, "timeframe": tf,
        "provider": status.provider if status else None, "is_live": status.is_live if status else None,
        "candles": [{"time": int(c.open_time.timestamp()), "open": c.open, "high": c.high, "low": c.low,
                     "close": c.close} for c in candles],
        "levels": [], "markers": [], "zones": [],
    }
    sid = request.GET.get("signal")
    if sid:
        signal = get_object_or_404(TradingSignal, pk=sid, instrument=inst)
        if can_view_signal(request.user, signal, record=False):
            data["levels"] = [
                {"price": float(signal.entry_price), "label": "Entry", "color": "#4dabf7"},
                {"price": float(signal.stop_loss), "label": "SL", "color": "#ff5c5c"},
            ] + [{"price": float(t), "label": f"TP{i + 1}", "color": "#2ecc71"} for i, t in enumerate(signal.targets)]
            data["levels"] += [{"price": float(signal.ref_high), "label": "CRT high", "color": "#adb5bd"},
                               {"price": float(signal.ref_low), "label": "CRT low", "color": "#adb5bd"}]
            sweep = signal.sweep_details or {}
            if sweep.get("manipulation_candle_open"):
                from datetime import datetime
                t = int(datetime.fromisoformat(sweep["manipulation_candle_open"]).timestamp())
                data["markers"].append({"time": t - t % {"5m": 300, "15m": 900, "1h": 3600}[tf],
                                        "position": "belowBar" if signal.direction == "BUY" else "aboveBar",
                                        "color": "#f59f00", "shape": "arrowUp" if signal.direction == "BUY" else "arrowDown",
                                        "text": "Sweep"})
            brk = (signal.structure_details or {}).get("ltf_break") or {}
            if brk.get("time"):
                from datetime import datetime
                t = int(datetime.fromisoformat(brk["time"]).timestamp())
                data["markers"].append({"time": t - t % {"5m": 300, "15m": 900, "1h": 3600}[tf], "position": "inBar",
                                        "color": "#e599f7", "shape": "circle", "text": brk.get("kind", "MSS")})
            for key in ("fvg", "order_block"):
                z = (signal.poi_details or {}).get(key)
                if z:
                    data["zones"].append({"label": z["type"], "top": z["top"], "bottom": z["bottom"]})
    return JsonResponse(data)
