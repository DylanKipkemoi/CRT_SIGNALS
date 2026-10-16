from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from markets.models import MarketInstrument


class Direction(models.TextChoices):
    BUY = "BUY", "Buy"
    SELL = "SELL", "Sell"


class SignalStatus(models.TextChoices):
    PROVISIONAL = "provisional", "Provisional"
    ACTIVE = "active", "Active (awaiting entry)"
    TRIGGERED = "triggered", "Triggered (in trade)"
    EXPIRED = "expired", "Expired"
    INVALIDATED = "invalidated", "Invalidated"
    CLOSED = "closed", "Closed"
    SUPERSEDED = "superseded", "Superseded"


OPEN_STATUSES = (SignalStatus.PROVISIONAL, SignalStatus.ACTIVE, SignalStatus.TRIGGERED)


class Outcome(models.TextChoices):
    NONE = "", "Pending"
    TP1 = "tp1", "Take-profit 1"
    TP2 = "tp2", "Take-profit 2"
    TP3 = "tp3", "Take-profit 3"
    STOP = "stop_loss", "Stop loss"
    TIMEOUT = "timeout", "Timed out"
    EXPIRED = "expired", "Expired before entry"
    INVALIDATED = "invalidated", "Invalidated before entry"


class OrderFlowStatus(models.TextChoices):
    CONFIRMED = "confirmed", "Order flow confirms"
    NEUTRAL = "neutral", "Order flow neutral"
    OPPOSING = "opposing", "Order flow opposing"
    UNAVAILABLE = "unavailable", "Order-flow confirmation unavailable"


class TradingSignal(models.Model):
    instrument = models.ForeignKey(MarketInstrument, on_delete=models.PROTECT, related_name="signals")
    direction = models.CharField(max_length=4, choices=Direction.choices)
    status = models.CharField(max_length=12, choices=SignalStatus.choices, default=SignalStatus.ACTIVE, db_index=True)
    outcome = models.CharField(max_length=12, choices=Outcome.choices, default=Outcome.NONE, blank=True)
    is_provisional = models.BooleanField(default=False)
    is_sample = models.BooleanField(default=False, help_text="Generated from sample (non-live) data.")

    score = models.PositiveSmallIntegerField()
    score_breakdown = models.JSONField(default=dict)
    classification = models.CharField(max_length=16)
    setup_type = models.CharField(max_length=120)

    entry_low = models.DecimalField(max_digits=20, decimal_places=8)
    entry_high = models.DecimalField(max_digits=20, decimal_places=8)
    entry_price = models.DecimalField(max_digits=20, decimal_places=8)
    stop_loss = models.DecimalField(max_digits=20, decimal_places=8)
    take_profit_1 = models.DecimalField(max_digits=20, decimal_places=8)
    take_profit_2 = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    take_profit_3 = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    risk_reward = models.DecimalField(max_digits=6, decimal_places=2, help_text="R multiple to the final target.")
    risk_reward_tp1 = models.DecimalField(max_digits=6, decimal_places=2)

    ref_candle_open = models.DateTimeField(help_text="Open time of the 1H CRT reference candle.")
    ref_high = models.DecimalField(max_digits=20, decimal_places=8)
    ref_low = models.DecimalField(max_digits=20, decimal_places=8)
    ref_mid = models.DecimalField(max_digits=20, decimal_places=8)

    sweep_details = models.JSONField(default=dict)
    structure_details = models.JSONField(default=dict)
    poi_details = models.JSONField(default=dict, help_text="FVG / order-block entry details.")
    order_flow_status = models.CharField(max_length=12, choices=OrderFlowStatus.choices)
    order_flow_details = models.JSONField(default=dict)
    market_context = models.JSONField(default=dict)

    timeframes = models.CharField(max_length=32, default="1H / 15M / 5M")
    provider = models.CharField(max_length=32)
    provider_symbol = models.CharField(max_length=32)
    explanation = models.TextField()
    invalidation_conditions = models.TextField()
    setup_key = models.CharField(max_length=120, unique=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField()
    triggered_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    max_tp_hit = models.PositiveSmallIntegerField(default=0)
    exit_price = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    realized_r = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["instrument", "status", "-created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(direction="BUY", stop_loss__lt=models.F("entry_low"), take_profit_1__gt=models.F("entry_high"))
                    | models.Q(direction="SELL", stop_loss__gt=models.F("entry_high"), take_profit_1__lt=models.F("entry_low"))
                ),
                name="signal_levels_match_direction",
            ),
            models.CheckConstraint(condition=models.Q(entry_low__lte=models.F("entry_high")), name="signal_entry_zone_order"),
        ]

    def __str__(self):
        return f"{self.instrument} {self.direction} {self.score}/100 @ {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def targets(self):
        return [tp for tp in (self.take_profit_1, self.take_profit_2, self.take_profit_3) if tp is not None]

    @property
    def risk_per_unit(self):
        return abs(self.entry_price - self.stop_loss)

    def r_multiple(self, price):
        risk = self.risk_per_unit
        if not risk:
            return Decimal("0")
        move = (Decimal(price) - self.entry_price) if self.direction == Direction.BUY else (self.entry_price - Decimal(price))
        return (move / risk).quantize(Decimal("0.01"))


class SignalEvent(models.Model):
    signal = models.ForeignKey(TradingSignal, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=32)
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12, blank=True)
    price = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at", "id"]

    def __str__(self):
        return f"{self.signal_id} {self.event_type}"


class MarketScanRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        PARTIAL = "partial", "Partial (some instruments failed)"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    class Trigger(models.TextChoices):
        SCHEDULER = "scheduler", "Scheduler"
        MANUAL = "manual", "Manual (admin)"
        COMMAND = "command", "Management command"

    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    trigger = models.CharField(max_length=10, choices=Trigger.choices, default=Trigger.SCHEDULER)
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    instruments_scanned = models.PositiveSmallIntegerField(default=0)
    signals_created = models.PositiveSmallIntegerField(default=0)
    signals_updated = models.PositiveSmallIntegerField(default=0)
    results = models.JSONField(default=dict, blank=True)
    errors = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Scan {self.started_at:%Y-%m-%d %H:%M} {self.status}"

    @property
    def duration_seconds(self):
        if self.finished_at:
            return round((self.finished_at - self.started_at).total_seconds(), 1)
        return None


class InstrumentAnalysis(models.Model):
    """Latest analysis state per instrument (BUY / SELL / WAIT / NO TRADE)."""

    class State(models.TextChoices):
        BUY = "BUY", "Buy"
        SELL = "SELL", "Sell"
        WAIT = "WAIT", "Wait"
        NO_TRADE = "NO_TRADE", "No trade"
        UNAVAILABLE = "UNAVAILABLE", "Data unavailable"

    instrument = models.OneToOneField(MarketInstrument, on_delete=models.CASCADE, related_name="analysis")
    state = models.CharField(max_length=12, choices=State.choices, default=State.UNAVAILABLE)
    bias = models.CharField(max_length=16, blank=True, help_text="Higher-timeframe structure bias.")
    best_score = models.PositiveSmallIntegerField(null=True, blank=True)
    summary = models.CharField(max_length=255, blank=True)
    details = models.JSONField(default=dict, blank=True)
    scan_run = models.ForeignKey(MarketScanRun, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Instrument analyses"

    def __str__(self):
        return f"{self.instrument}: {self.state}"
