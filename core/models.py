import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

DEFAULT_SCORE_WEIGHTS = {
    "crt_alignment": 15,
    "liquidity_sweep": 15,
    "structure_shift": 15,
    "displacement": 10,
    "entry_confluence": 10,
    "price_action": 10,
    "order_flow": 10,
    "risk_reward": 10,
    "market_conditions": 5,
}


def default_score_weights():
    return dict(DEFAULT_SCORE_WEIGHTS)


class SiteConfiguration(models.Model):
    """Singleton holding admin-editable business rules."""

    daily_fee_kes = models.PositiveIntegerField(default=500, validators=[MinValueValidator(1)])
    free_signals_per_user = models.PositiveSmallIntegerField(
        default=1, help_text="Number of complete qualifying signals a verified user may view for free (once per account)."
    )
    daily_access_end_time = models.TimeField(
        default=datetime.time(23, 59, 59),
        help_text="Africa/Nairobi local time at which a paid day's access ends.",
    )
    a_plus_threshold = models.PositiveSmallIntegerField(
        default=80, validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Minimum confluence score (out of 100) for a setup to be published as A+.",
    )
    score_weights = models.JSONField(
        default=default_score_weights, help_text="Factor weights; must be non-negative integers summing to 100."
    )
    min_risk_reward = models.DecimalField(
        max_digits=4, decimal_places=2, default=2.0, help_text="Minimum risk:reward to the final target."
    )
    require_order_flow = models.BooleanField(
        default=False, help_text="Decline setups when genuine order-flow data is unavailable."
    )
    order_flow_unavailable_credit = models.PositiveSmallIntegerField(
        default=0, help_text="Points (out of the order_flow weight) awarded when order flow is unavailable."
    )
    signal_expiry_hours = models.PositiveSmallIntegerField(
        default=4, help_text="Hours a signal waits for entry before it expires."
    )
    trade_timeout_hours = models.PositiveSmallIntegerField(
        default=48, help_text="Hours after entry before an open signal is closed as timed out."
    )
    allow_provisional_signals = models.BooleanField(
        default=True, help_text="Publish early-warning (provisional) setups from the incomplete 1H candle."
    )
    scanner_enabled = models.BooleanField(default=True)
    engine_overrides = models.JSONField(
        default=dict, blank=True, help_text="Optional overrides for signal engine parameters (see docs/SCORING.md)."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Site configuration"
        verbose_name_plural = "Site configuration"

    def __str__(self):
        return "Site configuration"

    def clean(self):
        weights = self.score_weights or {}
        unknown = set(weights) - set(DEFAULT_SCORE_WEIGHTS)
        if unknown:
            raise ValidationError({"score_weights": f"Unknown factors: {', '.join(sorted(unknown))}"})
        missing = set(DEFAULT_SCORE_WEIGHTS) - set(weights)
        if missing:
            raise ValidationError({"score_weights": f"Missing factors: {', '.join(sorted(missing))}"})
        if any(not isinstance(v, int) or v < 0 for v in weights.values()):
            raise ValidationError({"score_weights": "Weights must be non-negative integers."})
        if sum(weights.values()) != 100:
            raise ValidationError({"score_weights": "Weights must sum to 100."})
        if self.order_flow_unavailable_credit > weights.get("order_flow", 0):
            raise ValidationError({"order_flow_unavailable_credit": "Cannot exceed the order_flow weight."})

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("The site configuration cannot be deleted.")

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs"
    )
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    message = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"


class ContactMessage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=150)
    message = models.TextField(max_length=4000)
    handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} ({self.email})"
