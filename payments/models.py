import uuid

from django.conf import settings
from django.db import models


class PaymentStatus(models.TextChoices):
    INITIATED = "initiated", "Initiated"
    PENDING = "pending", "Pending (awaiting PIN)"
    SUCCESS = "success", "Successful"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled by user"
    TIMED_OUT = "timed_out", "Timed out"


OPEN_PAYMENT_STATUSES = (PaymentStatus.INITIATED, PaymentStatus.PENDING)
FINAL_PAYMENT_STATUSES = (PaymentStatus.SUCCESS, PaymentStatus.FAILED, PaymentStatus.CANCELLED, PaymentStatus.TIMED_OUT)


class PaymentTransaction(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    purpose = models.CharField(max_length=32, default="daily_access")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="KES")
    phone_masked = models.CharField(max_length=16)
    status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.INITIATED, db_index=True)
    environment = models.CharField(max_length=12, default="sandbox")

    merchant_request_id = models.CharField(max_length=64, blank=True)
    checkout_request_id = models.CharField(max_length=64, null=True, blank=True)
    mpesa_receipt = models.CharField(max_length=32, null=True, blank=True)
    result_code = models.CharField(max_length=16, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    transaction_date = models.DateTimeField(null=True, blank=True, help_text="M-Pesa transaction time from callback.")
    callback_received_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_method = models.CharField(max_length=32, blank=True)
    access_date = models.DateField(null=True, blank=True, help_text="Nairobi date the payment unlocked.")
    needs_review = models.BooleanField(default=False)
    review_note = models.CharField(max_length=255, blank=True)
    last_query_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["checkout_request_id"], condition=models.Q(checkout_request_id__isnull=False),
                name="unique_checkout_request_id",
            ),
            models.UniqueConstraint(
                fields=["mpesa_receipt"], condition=models.Q(mpesa_receipt__isnull=False), name="unique_mpesa_receipt"
            ),
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(status__in=["initiated", "pending"]),
                name="one_open_payment_per_user",
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self):
        return f"{self.reference} {self.user} KES {self.amount} {self.status}"

    @property
    def is_final(self):
        return self.status in FINAL_PAYMENT_STATUSES


class MpesaCallbackLog(models.Model):
    """Sanitized record of every callback hit (phone numbers masked)."""

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    checkout_request_id = models.CharField(max_length=64, blank=True, db_index=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    accepted = models.BooleanField(default=False)
    outcome = models.CharField(max_length=255, blank=True)
    payment = models.ForeignKey(PaymentTransaction, null=True, blank=True, on_delete=models.SET_NULL, related_name="callbacks")

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.received_at:%Y-%m-%d %H:%M:%S} {self.checkout_request_id} {self.outcome}"
