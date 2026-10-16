from django.conf import settings
from django.db import models
from django.utils import timezone


class FreeSignalEntitlement(models.Model):
    """One-time free complete signal per account, tracked server-side."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="free_entitlement")
    allowance = models.PositiveSmallIntegerField(default=1)
    used = models.PositiveSmallIntegerField(default=0)
    granted_at = models.DateTimeField(default=timezone.now)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(used__lte=models.F("allowance")), name="free_used_lte_allowance")]

    def __str__(self):
        return f"{self.user} free {self.used}/{self.allowance}"

    @property
    def remaining(self):
        return max(self.allowance - self.used, 0)


class SignalUnlock(models.Model):
    """A signal a user can view permanently (free unlock or viewed under paid access)."""

    class Source(models.TextChoices):
        FREE = "free", "Free first signal"
        PAID = "paid", "Paid daily access"
        STAFF = "staff", "Staff"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="signal_unlocks")
    signal = models.ForeignKey("signals.TradingSignal", on_delete=models.CASCADE, related_name="unlocks")
    source = models.CharField(max_length=8, choices=Source.choices)
    daily_access = models.ForeignKey("access.DailySignalAccess", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "signal"], name="unique_unlock_per_user_signal")]

    def __str__(self):
        return f"{self.user} -> {self.signal_id} ({self.source})"


class DailySignalAccess(models.Model):
    """Paid access for one Africa/Nairobi calendar day."""

    class Source(models.TextChoices):
        PAYMENT = "payment", "M-Pesa payment"
        ADMIN = "admin", "Granted by admin"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="daily_accesses")
    access_date = models.DateField(help_text="Africa/Nairobi calendar date.")
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.PAYMENT)
    payment = models.OneToOneField(
        "payments.PaymentTransaction", null=True, blank=True, on_delete=models.PROTECT, related_name="daily_access"
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-access_date"]
        verbose_name_plural = "Daily signal access"
        constraints = [
            models.UniqueConstraint(fields=["user", "access_date"], name="unique_daily_access_per_user_day"),
            models.CheckConstraint(condition=models.Q(expires_at__gt=models.F("starts_at")), name="daily_access_window_valid"),
        ]

    def __str__(self):
        return f"{self.user} {self.access_date}"

    @property
    def is_active(self):
        now = timezone.now()
        return self.starts_at <= now < self.expires_at
