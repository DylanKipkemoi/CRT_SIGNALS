"""Payment workflow: initiate STK push, process callbacks idempotently, reconcile."""

import datetime
import logging
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from access.services import active_daily_access, grant_daily_access
from core.audit import audit
from core.models import SiteConfiguration
from core.utils import NAIROBI, mask_phone

from .daraja import DarajaClient, DarajaError, DarajaNotConfigured
from .models import MpesaCallbackLog, PaymentStatus, PaymentTransaction

logger = logging.getLogger(__name__)

PROCESSING_ERROR_CODE = "500.001.1001"  # "The transaction is being processed"


class PaymentError(Exception):
    pass


def status_for_result_code(code):
    code = int(code)
    if code == 0:
        return PaymentStatus.SUCCESS
    if code == 1032:
        return PaymentStatus.CANCELLED
    if code in (1037, 1019):
        return PaymentStatus.TIMED_OUT
    return PaymentStatus.FAILED


def get_client():
    return DarajaClient()


def initiate_payment(user, phone, request=None, client=None, now=None):
    now = now or timezone.now()
    if not user.is_verified:
        raise PaymentError("Verify your email address before paying.")
    if active_daily_access(user, now):
        raise PaymentError("You already have access to today's signals.")
    open_payment = PaymentTransaction.objects.filter(
        user=user, status__in=[PaymentStatus.INITIATED, PaymentStatus.PENDING]).first()
    if open_payment:
        reconcile_payment(open_payment, client=client, now=now)
        open_payment.refresh_from_db()
        if not open_payment.is_final:
            raise PaymentError("A payment request is already in progress. Check your phone or wait a few minutes.")
    client = client or get_client()
    client.check_configured()
    site = SiteConfiguration.load()
    try:
        payment = PaymentTransaction.objects.create(
            user=user, amount=Decimal(site.daily_fee_kes), phone_masked=mask_phone(phone),
            environment=settings.DARAJA["ENVIRONMENT"],
        )
    except IntegrityError as exc:
        raise PaymentError("A payment request is already in progress.") from exc
    audit("payment.initiated", actor=user, target=payment, request=request, amount=str(payment.amount))
    try:
        resp = client.stk_push(phone, payment.amount, settings.DARAJA["ACCOUNT_REFERENCE"], "Daily signals")
    except DarajaError as exc:
        payment.status = PaymentStatus.FAILED
        payment.result_desc = str(exc)[:255]
        payment.result_code = str(exc.code)[:16]
        payment.completed_at = timezone.now()
        payment.save()
        audit("payment.stk_failed", actor=user, target=payment, request=request, error=str(exc)[:200])
        raise PaymentError("Could not send the M-Pesa prompt. Please try again shortly.") from exc
    payment.merchant_request_id = resp.get("MerchantRequestID", "")
    payment.checkout_request_id = resp.get("CheckoutRequestID")
    payment.status = PaymentStatus.PENDING
    payment.result_desc = (resp.get("CustomerMessage") or resp.get("ResponseDescription") or "")[:255]
    payment.save()
    return payment


def parse_callback(payload):
    """Validate the Daraja STK callback structure. Raises ValueError."""
    try:
        cb = payload["Body"]["stkCallback"]
        checkout = str(cb["CheckoutRequestID"])
        result_code = int(cb["ResultCode"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid STK callback structure") from exc
    items = {}
    meta = cb.get("CallbackMetadata") or {}
    for item in meta.get("Item", []) or []:
        if isinstance(item, dict) and "Name" in item:
            items[item["Name"]] = item.get("Value")
    return {
        "merchant_request_id": str(cb.get("MerchantRequestID", "")),
        "checkout_request_id": checkout,
        "result_code": result_code,
        "result_desc": str(cb.get("ResultDesc", ""))[:255],
        "items": items,
    }


def sanitize_payload(payload):
    try:
        import copy

        clean = copy.deepcopy(payload)
        for item in clean["Body"]["stkCallback"].get("CallbackMetadata", {}).get("Item", []):
            if item.get("Name") == "PhoneNumber":
                item["Value"] = mask_phone(item.get("Value"))
        return clean
    except (KeyError, TypeError, AttributeError):
        return {"unparseable": True}


def _parse_mpesa_date(value):
    try:
        dt = datetime.datetime.strptime(str(value), "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=NAIROBI)
    except (TypeError, ValueError):
        return None


def mark_success(payment_id, method, now=None, request=None):
    """Mark success and grant access exactly once (idempotent)."""
    now = now or timezone.now()
    with transaction.atomic():
        payment = PaymentTransaction.objects.select_for_update().get(pk=payment_id)
        if payment.status == PaymentStatus.SUCCESS:
            return payment, False
        if payment.is_final:
            payment.needs_review = True
            payment.review_note = f"Success reported after final status {payment.status}"[:255]
            payment.save(update_fields=["needs_review", "review_note", "updated_at"])
            return payment, False
        payment.status = PaymentStatus.SUCCESS
        payment.verified_at = now
        payment.verification_method = method
        payment.completed_at = now
        payment.save()
        access, created = grant_daily_access(payment.user, payment=payment, now=now, request=request)
        if not created:
            payment.needs_review = True
            payment.review_note = "Duplicate payment for an already-unlocked day — review for refund."
        payment.access_date = access.access_date
        payment.save(update_fields=["needs_review", "review_note", "access_date", "updated_at"])
    audit("payment.success", actor=payment.user, target=payment, request=request, method=method,
          receipt=payment.mpesa_receipt or "")
    return payment, created


def mark_final(payment_id, status, code="", desc="", now=None):
    now = now or timezone.now()
    with transaction.atomic():
        payment = PaymentTransaction.objects.select_for_update().get(pk=payment_id)
        if payment.is_final:
            return payment, False
        payment.status = status
        payment.result_code = str(code)[:16]
        payment.result_desc = str(desc)[:255]
        payment.completed_at = now
        payment.save()
    audit(f"payment.{status}", actor=payment.user, target=payment, code=str(code))
    return payment, True


def process_callback(payload, source_ip=None, client=None):
    """Handle a Daraja STK callback. Never trusts it blindly; always idempotent."""
    log = MpesaCallbackLog.objects.create(source_ip=source_ip, payload=sanitize_payload(payload))
    try:
        data = parse_callback(payload)
    except ValueError as exc:
        log.outcome = str(exc)
        log.save(update_fields=["outcome"])
        return log
    log.checkout_request_id = data["checkout_request_id"]
    payment = PaymentTransaction.objects.filter(checkout_request_id=data["checkout_request_id"]).first()
    if payment is None:
        log.outcome = "Unknown CheckoutRequestID — ignored"
        log.save(update_fields=["checkout_request_id", "outcome"])
        return log
    log.payment = payment
    log.accepted = True
    if payment.merchant_request_id and data["merchant_request_id"] and payment.merchant_request_id != data["merchant_request_id"]:
        log.accepted = False
        log.outcome = "MerchantRequestID mismatch — ignored"
        log.save()
        return log
    if payment.is_final:
        log.outcome = f"Duplicate callback ignored (already {payment.status})"
        log.save()
        return log

    with transaction.atomic():
        p = PaymentTransaction.objects.select_for_update().get(pk=payment.pk)
        p.callback_received_at = timezone.now()
        p.result_code = str(data["result_code"])
        p.result_desc = data["result_desc"]
        if data["result_code"] == 0:
            items = data["items"]
            receipt = items.get("MpesaReceiptNumber")
            if receipt and not PaymentTransaction.objects.filter(mpesa_receipt=receipt).exclude(pk=p.pk).exists():
                p.mpesa_receipt = str(receipt)[:32]
            if items.get("Amount") is not None:
                p.paid_amount = Decimal(str(items["Amount"]))
            p.transaction_date = _parse_mpesa_date(items.get("TransactionDate"))
        p.save()

    if data["result_code"] != 0:
        status = status_for_result_code(data["result_code"])
        mark_final(payment.pk, status, data["result_code"], data["result_desc"])
        log.outcome = f"Marked {status}"
        log.save()
        return log

    payment.refresh_from_db()
    if payment.paid_amount is None or payment.paid_amount != payment.amount:
        payment.needs_review = True
        payment.review_note = f"Amount mismatch: expected {payment.amount}, callback {payment.paid_amount}"
        payment.save(update_fields=["needs_review", "review_note", "updated_at"])
        mark_final(payment.pk, PaymentStatus.FAILED, "AMOUNT", "Paid amount does not match the expected fee")
        log.outcome = "Amount mismatch — not granted, flagged for review"
        log.save()
        return log
    if not payment.mpesa_receipt:
        log.outcome = "Success callback without a unique receipt — left pending for reconciliation"
        log.save()
        return log

    if settings.DARAJA["VERIFY_WITH_QUERY"]:
        verified = _query_confirms_success(payment, client)
        if verified is None:
            log.outcome = "Success callback received; verification query pending — will reconcile"
            log.save()
            return log
        if not verified:
            payment.needs_review = True
            payment.review_note = "Callback reported success but STK query did not confirm."
            payment.save(update_fields=["needs_review", "review_note", "updated_at"])
            log.outcome = "Verification query did not confirm success — flagged"
            log.save()
            return log
        method = "callback+query"
    else:
        method = "callback"
    _, created = mark_success(payment.pk, method)
    log.outcome = "Success — access granted" if created else "Success — no new access (duplicate day)"
    log.save()
    return log


def _query_confirms_success(payment, client=None):
    """True/False when Safaricom answers definitively; None when not yet known."""
    client = client or get_client()
    try:
        resp = client.stk_query(payment.checkout_request_id)
    except DarajaNotConfigured:
        return None
    except DarajaError as exc:
        logger.info("STK query for %s not conclusive: %s", payment.reference, exc)
        return None
    finally:
        PaymentTransaction.objects.filter(pk=payment.pk).update(last_query_at=timezone.now())
    if "ResultCode" not in resp:
        return None
    return str(resp.get("ResultCode")) == "0"


def reconcile_payment(payment, client=None, now=None):
    """Resolve a stale open payment via STK query. Returns new status or None."""
    now = now or timezone.now()
    timeout = settings.DARAJA["PENDING_TIMEOUT_SECONDS"]
    if payment.is_final or (now - payment.created_at).total_seconds() < timeout:
        return None
    if not payment.checkout_request_id:
        mark_final(payment.pk, PaymentStatus.FAILED, "", "STK push was never accepted", now)
        return PaymentStatus.FAILED
    client = client or get_client()
    try:
        resp = client.stk_query(payment.checkout_request_id)
    except DarajaNotConfigured:
        return None
    except DarajaError as exc:
        PaymentTransaction.objects.filter(pk=payment.pk).update(last_query_at=now)
        if exc.code == PROCESSING_ERROR_CODE and (now - payment.created_at).total_seconds() < timeout * 3:
            return None
        if (now - payment.created_at).total_seconds() >= timeout * 3:
            mark_final(payment.pk, PaymentStatus.TIMED_OUT, exc.code, "No final result from M-Pesa", now)
            return PaymentStatus.TIMED_OUT
        return None
    PaymentTransaction.objects.filter(pk=payment.pk).update(last_query_at=now)
    if "ResultCode" not in resp:
        return None
    status = status_for_result_code(resp["ResultCode"])
    if status == PaymentStatus.SUCCESS:
        mark_success(payment.pk, "query", now)
    else:
        mark_final(payment.pk, status, resp.get("ResultCode"), resp.get("ResultDesc", ""), now)
    return status


def reconcile_pending_payments(client=None, now=None):
    count = 0
    for payment in PaymentTransaction.objects.filter(status__in=[PaymentStatus.INITIATED, PaymentStatus.PENDING]):
        try:
            if reconcile_payment(payment, client=client, now=now):
                count += 1
        except Exception:  # noqa: BLE001
            logger.exception("Reconciliation failed for %s", payment.reference)
    return count
