from django.db import models


class Timeframe(models.TextChoices):
    M5 = "5m", "5 minutes"
    M15 = "15m", "15 minutes"
    H1 = "1h", "1 hour"
    H4 = "4h", "4 hours"


TIMEFRAME_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


class VolumeType(models.TextChoices):
    EXCHANGE = "exchange", "Exchange-traded volume"
    TICK = "tick", "Broker tick volume"
    NONE = "none", "No volume"


class MarketInstrument(models.Model):
    class AssetClass(models.TextChoices):
        CRYPTO = "crypto", "Crypto"
        METAL = "metal", "Precious metal"

    symbol = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=64)
    asset_class = models.CharField(max_length=12, choices=AssetClass.choices)
    provider = models.CharField(
        max_length=32, help_text="Market-data provider key (coinbase, kraken, oanda, twelvedata, sample)."
    )
    provider_symbol = models.CharField(max_length=32, help_text="Symbol as the provider names it, e.g. BTC-USD.")
    price_decimals = models.PositiveSmallIntegerField(default=2)
    is_enabled = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "symbol"]

    def __str__(self):
        return self.symbol


class MarketCandle(models.Model):
    instrument = models.ForeignKey(MarketInstrument, on_delete=models.CASCADE, related_name="candles")
    provider = models.CharField(max_length=32)
    timeframe = models.CharField(max_length=4, choices=Timeframe.choices)
    open_time = models.DateTimeField()
    open = models.DecimalField(max_digits=20, decimal_places=8)
    high = models.DecimalField(max_digits=20, decimal_places=8)
    low = models.DecimalField(max_digits=20, decimal_places=8)
    close = models.DecimalField(max_digits=20, decimal_places=8)
    volume = models.DecimalField(max_digits=28, decimal_places=8, default=0)
    volume_type = models.CharField(max_length=10, choices=VolumeType.choices, default=VolumeType.NONE)
    is_sample = models.BooleanField(default=False)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["instrument", "timeframe", "open_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "provider", "timeframe", "open_time"], name="unique_candle_per_provider"
            ),
            models.CheckConstraint(condition=models.Q(high__gte=models.F("low")), name="candle_high_gte_low"),
        ]
        indexes = [models.Index(fields=["instrument", "timeframe", "-open_time"])]

    def __str__(self):
        return f"{self.instrument} {self.timeframe} {self.open_time:%Y-%m-%d %H:%M}"


class MarketDataStatus(models.Model):
    instrument = models.OneToOneField(MarketInstrument, on_delete=models.CASCADE, related_name="data_status")
    provider = models.CharField(max_length=32, blank=True)
    provider_symbol = models.CharField(max_length=32, blank=True)
    is_live = models.BooleanField(default=True, help_text="False for sample/offline data.")
    last_price = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    bid = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    ask = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    quote_time = models.DateTimeField(null=True, blank=True)
    change_24h_pct = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_candle_close_at = models.DateTimeField(null=True, blank=True)
    is_stale = models.BooleanField(default=True)
    stale_reason = models.CharField(max_length=255, blank=True)
    volume_type = models.CharField(max_length=10, choices=VolumeType.choices, default=VolumeType.NONE)
    order_flow_available = models.BooleanField(default=False)
    last_error = models.TextField(blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Market data status"

    def __str__(self):
        return f"{self.instrument} via {self.provider}"
