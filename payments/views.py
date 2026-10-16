import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from access.services import access_summary
from core.models import SiteConfiguration
from core.ratelimit import ratelimit
from core.utils import get_client_ip

from .daraja import DarajaNotConfigured
from .forms import PaymentForm
from .models import PaymentTransaction
from .services import PaymentError, initiate_payment, process_callback, reconcile_payment

logger = logging.getLogger(__name__)


@login_required
@ratelimit("payment_initiate")
def pay(request):
    form = PaymentForm(request.POST or None, initial={"phone": request.user.phone and f"0{request.user.phone[3:]}"})
    if request.method == "POST" and form.is_valid():
        try:
            payment = initiate_payment(request.user, form.cleaned_data["phone"], request=request)
        except DarajaNotConfigured:
            messages.error(request, "M-Pesa payments are not configured yet. Please contact support.")
        except PaymentError as exc:
            messages.error(request, str(exc))
        else:
            return redirect("payments:status", reference=payment.reference)
    return render(request, "payments/pay.html", {
        "form": form, "summary": access_summary(request.user), "fee": SiteConfiguration.load().daily_fee_kes,
    })


@login_required
def payment_status(request, reference):
    payment = get_object_or_404(PaymentTransaction, reference=reference, user=request.user)
    return render(request, "payments/status.html", {"payment": payment})


@login_required
@ratelimit("api", methods=("GET",), json=True)
def payment_status_api(request, reference):
    payment = get_object_or_404(PaymentTransaction, reference=reference, user=request.user)
    if not payment.is_final:
        try:
            reconcile_payment(payment)
        except Exception:  # noqa: BLE001
            logger.exception("status reconcile failed")
        payment.refresh_from_db()
    return JsonResponse({"status": payment.status, "label": payment.get_status_display(), "final": payment.is_final,
                         "description": payment.result_desc})


@login_required
def history(request):
    page = Paginator(PaymentTransaction.objects.filter(user=request.user), 20).get_page(request.GET.get("page"))
    return render(request, "payments/history.html", {"page": page})


@csrf_exempt
@require_POST
@ratelimit("callback", json=True)
def mpesa_callback(request, token):
    cfg = settings.DARAJA
    ip = get_client_ip(request)
    if not cfg["CALLBACK_TOKEN"] or not constant_time_compare(token, cfg["CALLBACK_TOKEN"]):
        logger.warning("M-Pesa callback with invalid token from %s", ip)
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Rejected"}, status=403)
    if cfg["ALLOWED_CALLBACK_IPS"] and ip not in cfg["ALLOWED_CALLBACK_IPS"]:
        logger.warning("M-Pesa callback from non-allowlisted IP %s", ip)
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Rejected"}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid JSON"}, status=400)
    log = process_callback(payload, source_ip=ip)
    logger.info("M-Pesa callback %s: %s", log.checkout_request_id, log.outcome)
    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})
