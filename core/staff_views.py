from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from core.audit import audit
from core.models import AuditLog, SiteConfiguration
from markets.models import MarketDataStatus
from payments.models import MpesaCallbackLog, PaymentStatus, PaymentTransaction
from signals.models import MarketScanRun, TradingSignal
from signals.scanner import run_scan, scanner_health
from signals.services import performance_stats


@staff_member_required
def staff_dashboard(request):
    today = timezone.localdate()
    payments_today = PaymentTransaction.objects.filter(created_at__date=today)
    ctx = {
        "health": scanner_health(),
        "runs": MarketScanRun.objects.all()[:15],
        "feeds": MarketDataStatus.objects.select_related("instrument"),
        "stats": performance_stats(include_sample=True),
        "users_total": User.objects.count(),
        "users_suspended": User.objects.filter(is_active=False).count(),
        "payments_by_status": payments_today.values("status").annotate(n=Count("id")),
        "revenue_today": payments_today.filter(status=PaymentStatus.SUCCESS).aggregate(s=Sum("amount"))["s"] or 0,
        "review_payments": PaymentTransaction.objects.filter(needs_review=True)[:10],
        "callbacks": MpesaCallbackLog.objects.all()[:10],
        "recent_signals": TradingSignal.objects.select_related("instrument")[:10],
        "audit": AuditLog.objects.select_related("actor")[:15],
        "config": SiteConfiguration.load(),
    }
    return render(request, "core/staff_dashboard.html", ctx)


@staff_member_required
@require_POST
def manual_scan(request):
    run = run_scan(trigger=MarketScanRun.Trigger.MANUAL, user=request.user)
    audit("scanner.manual_scan", request=request, target=run, status=run.status)
    level = messages.SUCCESS if run.status == MarketScanRun.Status.SUCCESS else messages.WARNING
    messages.add_message(request, level, f"Scan {run.status}: {run.signals_created} new, {run.signals_updated} updated. "
                         + " ".join(run.errors))
    return redirect("staff:dashboard")
