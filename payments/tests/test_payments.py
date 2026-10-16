import base64
import datetime
import json
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from access.models import DailySignalAccess
from access.services import can_view_signal
from core.testing import make_signal, make_user
from payments.daraja import DarajaClient, DarajaError
from payments.models import MpesaCallbackLog, PaymentStatus, PaymentTransaction
from payments import services

DARAJA = {**settings.DARAJA, "CONSUMER_KEY": "key", "CONSUMER_SECRET": "secret", "SHORTCODE": "174379",
          "PASSKEY": "passkey", "CALLBACK_BASE_URL": "https://example.com", "CALLBACK_TOKEN": "tok123",
          "VERIFY_WITH_QUERY": False, "ALLOWED_CALLBACK_IPS": [], "ENVIRONMENT": "sandbox"}


class FakeClient:
    def __init__(self, query=None, push_error=None):
        self.query = query or {"ResultCode": "0", "ResultDesc": "ok"}
        self.push_error = push_error
        self.pushes = []

    def check_configured(self):
        pass

    def stk_push(self, phone, amount, ref, desc):
        if self.push_error:
            raise self.push_error
        self.pushes.append((phone, amount))
        n = len(self.pushes)
        return {"MerchantRequestID": f"m{n}", "CheckoutRequestID": f"ws_CO_{n}", "ResponseCode": "0",
                "CustomerMessage": "Success. Request accepted for processing"}

    def stk_query(self, checkout):
        if isinstance(self.query, Exception):
            raise self.query
        return self.query


def callback(checkout, code=0, amount=500, receipt="QKA1B2C3D4", merchant="m1"):
    cb = {"MerchantRequestID": merchant, "CheckoutRequestID": checkout, "ResultCode": code, "ResultDesc": "desc"}
    if code == 0:
        cb["CallbackMetadata"] = {"Item": [
            {"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt},
            {"Name": "TransactionDate", "Value": 20261016120000}, {"Name": "PhoneNumber", "Value": 254712345678}]}
    return {"Body": {"stkCallback": cb}}


@override_settings(DARAJA=DARAJA)
class PaymentFlowTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client_fake = FakeClient()
        patcher = mock.patch.object(services, "get_client", return_value=self.client_fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pay(self):
        return services.initiate_payment(self.user, "254712345678", client=self.client_fake)

    def post_cb(self, payload, token="tok123"):
        return self.client.post(reverse("payments:mpesa_callback", args=[token]), data=json.dumps(payload),
                                content_type="application/json")

    def test_initiate_creates_pending_without_access(self):
        p = self.pay()
        self.assertEqual(p.status, PaymentStatus.PENDING)
        self.assertEqual(p.amount, 500)
        self.assertEqual(p.checkout_request_id, "ws_CO_1")
        self.assertNotIn("345678"[:4], p.phone_masked[3:7])
        self.assertFalse(DailySignalAccess.objects.filter(user=self.user).exists())

    def test_successful_callback_grants_access_once(self):
        p = self.pay()
        r = self.post_cb(callback("ws_CO_1"))
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.SUCCESS)
        self.assertEqual(p.mpesa_receipt, "QKA1B2C3D4")
        self.assertTrue(can_view_signal(self.user, make_signal()))
        self.post_cb(callback("ws_CO_1"))
        self.assertEqual(DailySignalAccess.objects.filter(user=self.user).count(), 1)
        self.assertIn("Duplicate", MpesaCallbackLog.objects.first().outcome)
        logged = json.dumps(MpesaCallbackLog.objects.last().payload)
        self.assertNotIn("254712345678", logged)

    def test_cancelled_and_failed_callbacks_grant_nothing(self):
        p = self.pay()
        self.post_cb(callback("ws_CO_1", code=1032))
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.CANCELLED)
        self.post_cb(callback("ws_CO_1"))  # late success after cancel must not grant
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.CANCELLED)
        self.assertFalse(DailySignalAccess.objects.filter(user=self.user).exists())
        p2 = self.pay()
        self.post_cb(callback(p2.checkout_request_id, code=1, merchant=p2.merchant_request_id))
        p2.refresh_from_db()
        self.assertEqual(p2.status, PaymentStatus.FAILED)

    def test_amount_mismatch_rejected(self):
        p = self.pay()
        self.post_cb(callback("ws_CO_1", amount=1))
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.FAILED)
        self.assertTrue(p.needs_review)
        self.assertFalse(DailySignalAccess.objects.exists())

    def test_unknown_checkout_and_bad_requests(self):
        self.assertEqual(self.post_cb(callback("nope")).status_code, 200)
        self.assertIn("Unknown", MpesaCallbackLog.objects.first().outcome)
        self.assertEqual(self.post_cb(callback("x"), token="wrong").status_code, 403)
        r = self.client.post(reverse("payments:mpesa_callback", args=["tok123"]), data="{bad",
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.post_cb({"Body": {}})
        self.assertIn("Invalid", MpesaCallbackLog.objects.first().outcome)

    def test_merchant_mismatch_ignored(self):
        p = self.pay()
        self.post_cb(callback("ws_CO_1", merchant="other"))
        p.refresh_from_db()
        self.assertEqual(p.status, PaymentStatus.PENDING)

    def test_one_open_payment_and_no_double_pay(self):
        self.pay()
        with self.assertRaises(services.PaymentError):
            self.pay()
        self.post_cb(callback("ws_CO_1"))
        with self.assertRaises(services.PaymentError):
            self.pay()

    def test_unverified_user_cannot_pay(self):
        self.user.email_verified_at = None
        self.user.save()
        with self.assertRaises(services.PaymentError):
            self.pay()

    def test_stk_failure_marks_failed(self):
        self.client_fake.push_error = DarajaError("boom", code="400.002.02")
        with self.assertRaises(services.PaymentError):
            self.pay()
        self.assertEqual(PaymentTransaction.objects.get().status, PaymentStatus.FAILED)

    def test_query_verification_required(self):
        with override_settings(DARAJA={**DARAJA, "VERIFY_WITH_QUERY": True}):
            self.client_fake.query = {"ResultCode": "1032", "ResultDesc": "Cancelled"}
            p = self.pay()
            self.post_cb(callback("ws_CO_1"))
            p.refresh_from_db()
            self.assertNotEqual(p.status, PaymentStatus.SUCCESS)
            self.assertTrue(p.needs_review)
            self.client_fake.query = {"ResultCode": "0", "ResultDesc": "ok"}
            p2 = PaymentTransaction.objects.create(user=make_user(), amount=500, phone_masked="2547****5678",
                                                   checkout_request_id="ws_CO_X", merchant_request_id="m1",
                                                   status=PaymentStatus.PENDING)
            self.post_cb(callback("ws_CO_X", receipt="QZZZ999"))
            p2.refresh_from_db()
            self.assertEqual((p2.status, p2.verification_method), (PaymentStatus.SUCCESS, "callback+query"))

    def test_reconcile_timeout_and_success(self):
        p = self.pay()
        later = p.created_at + datetime.timedelta(seconds=DARAJA["PENDING_TIMEOUT_SECONDS"] + 5)
        self.client_fake.query = {"ResultCode": "1037", "ResultDesc": "No response from user"}
        self.assertEqual(services.reconcile_payment(p, client=self.client_fake, now=later), PaymentStatus.TIMED_OUT)
        p2 = self.pay()
        later = p2.created_at + datetime.timedelta(seconds=DARAJA["PENDING_TIMEOUT_SECONDS"] + 5)
        self.client_fake.query = {"ResultCode": "0", "ResultDesc": "ok"}
        self.assertEqual(services.reconcile_pending_payments(client=self.client_fake, now=later), 1)
        p2.refresh_from_db()
        self.assertEqual(p2.status, PaymentStatus.SUCCESS)
        self.assertTrue(DailySignalAccess.objects.filter(user=self.user, payment=p2).exists())

    def test_reconcile_not_before_timeout(self):
        p = self.pay()
        self.assertIsNone(services.reconcile_payment(p, client=self.client_fake, now=timezone.now()))

    def test_status_api_never_trusts_frontend(self):
        p = self.pay()
        self.client.force_login(self.user)
        r = self.client.get(reverse("payments:status_api", args=[p.reference])).json()
        self.assertEqual(r["status"], "pending")
        other = make_user()
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("payments:status_api", args=[p.reference])).status_code, 404)


class DarajaClientTests(TestCase):
    @override_settings(DARAJA=DARAJA)
    @mock.patch("payments.daraja.requests.post")
    @mock.patch("payments.daraja.requests.get")
    def test_stk_push_request(self, get, post):
        get.return_value = mock.Mock(status_code=200, json=lambda: {"access_token": "T", "expires_in": "3599"})
        post.return_value = mock.Mock(status_code=200, json=lambda: {"ResponseCode": "0", "CheckoutRequestID": "c"})
        DarajaClient().stk_push("254712345678", 500, "CRTSIGNALS", "Daily signals")
        url = post.call_args.args[0]
        body = post.call_args.kwargs["json"]
        self.assertEqual(url, "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest")
        self.assertEqual(body["Amount"], 500)
        self.assertEqual(body["CallBackURL"], "https://example.com/payments/mpesa/callback/tok123/")
        decoded = base64.b64decode(body["Password"]).decode()
        self.assertEqual(decoded, "174379passkey" + body["Timestamp"])
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer T")

    def test_not_configured(self):
        from payments.daraja import DarajaNotConfigured
        with override_settings(DARAJA={**DARAJA, "CONSUMER_KEY": ""}):
            with self.assertRaises(DarajaNotConfigured):
                DarajaClient().check_configured()
        with override_settings(DARAJA={**DARAJA, "CALLBACK_BASE_URL": "http://insecure"}):
            with self.assertRaises(DarajaNotConfigured):
                DarajaClient().check_configured()

    def test_pay_view_when_not_configured(self):
        user = make_user()
        self.client.force_login(user)
        with override_settings(DARAJA={**DARAJA, "CONSUMER_KEY": ""}):
            r = self.client.post(reverse("payments:pay"), {"phone": "0712345678"}, follow=True)
        self.assertContains(r, "not configured")
        self.assertFalse(PaymentTransaction.objects.exists())
