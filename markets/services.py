"""Market-data service: fetch, validate, cache, persist and report freshness.

Kept separate from the signal engine, which only ever receives validated,
completed candles.
"""

import datetime
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import MarketCandle, MarketDataStatus, MarketInstrument
from .providers import ProviderError, ProviderNotConfigured, get_provider
from .types import TF_SECONDS, Candle

logger = logging.getLogger(__name__)

DEFAULT_LIMITS = {"1h": 200, "15m": 200, "5m": 288, "4h": 120}


@dataclass
class ValidationReport:
    dropped_invalid: int = 0
    duplicates: int = 0
    gaps: list = field(default_factory=list)  # [(after_open_time, missing_count)]

    @property
    def missing_candles(self):
        return sum(n for _, n in self.gaps)


@dataclass
class MarketSnapshot:
    symbol: str
    provider: str
    provider_name: str
    provider_symbol: str
    is_live: bool
    volume_type: str
    candles: dict  # timeframe -> list[Candle] (completed only)
    forming: dict  # timeframe -> Candle | None
    quote: object = None
    order_flow: object = None
    fetched_at: datetime.datetime = None
    stale: bool = False
    stale_reason: str = ""
    issues: list = field(default_factory=list)
    reports: dict = field(default_factory=dict)

    @property
    def price(self):
        if self.quote and self.quote.last:
            return self.quote.last
        ltf = self.candles.get("5m") or self.candles.get("15m") or self.candles.get("1h")
        if self.forming.get("5m"):
            return self.forming["5m"].close
        return ltf[-1].close if ltf else None


def validate_candles(candles, timeframe):
    """Drop malformed candles, de-duplicate, sort and detect gaps."""
    report = ValidationReport()
    seen = {}
    for c in candles:
        ok = (
            c.high >= c.low and c.high >= max(c.open, c.close) and c.low <= min(c.open, c.close)
            and min(c.open, c.high, c.low, c.close) > 0 and c.volume >= 0
            and c.open_time.tzinfo is not None
        )
        if not ok:
            report.dropped_invalid += 1
            continue
        if c.open_time in seen:
            report.duplicates += 1
        seen[c.open_time] = c
    clean = [seen[k] for k in sorted(seen)]
    step = datetime.timedelta(seconds=TF_SECONDS[timeframe])
    for prev, cur in zip(clean, clean[1:], strict=False):
        diff = cur.open_time - prev.open_time
        if diff > step:
            report.gaps.append((prev.open_time, int(diff / step) - 1))
    return clean, report


def split_completed(candles, now):
    """Return (completed candles, forming candle or None)."""
    completed = [c for c in candles if c.close_time <= now]
    forming = next((c for c in reversed(candles) if c.open_time <= now < c.close_time), None)
    return completed, forming


def is_stale(completed, timeframe, now, grace=None):
    grace = settings.MARKET_DATA["STALE_GRACE_SECONDS"] if grace is None else grace
    if not completed:
        return True, f"No completed {timeframe} candles."
    age = (now - completed[-1].close_time).total_seconds()
    limit = TF_SECONDS[timeframe] + grace
    if age > limit:
        return True, f"Latest {timeframe} candle closed {int(age // 60)} min ago (limit {limit // 60} min)."
    return False, ""


def recent_gaps(report, completed, window):
    """Gaps that fall within the last ``window`` candles."""
    if not completed:
        return []
    cutoff = completed[max(0, len(completed) - window)].open_time
    return [(t, n) for t, n in report.gaps if t >= cutoff]


def _with_retries(fn, *args):
    retries = settings.MARKET_DATA["RETRIES"]
    last = None
    for attempt in range(retries):
        try:
            return fn(*args)
        except ProviderNotConfigured:
            raise
        except ProviderError as exc:
            last = exc
            logger.warning("market data attempt %s/%s failed: %s", attempt + 1, retries, exc)
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 8))
    raise last


def _cached(key, fn, *args):
    ttl = settings.MARKET_DATA["CACHE_SECONDS"]
    if ttl > 0:
        hit = cache.get(key)
        if hit is not None:
            return hit
    value = _with_retries(fn, *args)
    if ttl > 0 and value is not None:
        cache.set(key, value, ttl)
    return value


def fetch_snapshot(instrument, timeframes=("1h", "15m", "5m"), *, provider=None, now=None, with_order_flow=True):
    provider = provider or get_provider(instrument.provider)
    provider.check_configured()
    now = now or timezone.now()
    snap = MarketSnapshot(
        symbol=instrument.symbol, provider=provider.key, provider_name=provider.name,
        provider_symbol=instrument.provider_symbol, is_live=provider.is_live, volume_type=provider.volume_type,
        candles={}, forming={}, fetched_at=now,
    )
    sym = instrument.provider_symbol
    for tf in timeframes:
        raw = _cached(f"md:{provider.key}:{sym}:{tf}", provider.fetch_candles, sym, tf, DEFAULT_LIMITS[tf])
        clean, report = validate_candles(raw, tf)
        completed, forming = split_completed(clean, now)
        snap.candles[tf] = completed
        snap.forming[tf] = forming
        snap.reports[tf] = report
        if report.dropped_invalid:
            snap.issues.append(f"{tf}: dropped {report.dropped_invalid} malformed candle(s).")
        if report.gaps:
            snap.issues.append(f"{tf}: {report.missing_candles} missing candle(s) in {len(report.gaps)} gap(s).")
    try:
        snap.quote = _cached(f"md:{provider.key}:{sym}:quote", provider.fetch_quote, sym)
    except ProviderError as exc:
        snap.issues.append(f"Quote unavailable: {exc}")
    if with_order_flow and provider.supports_order_flow:
        try:
            snap.order_flow = _with_retries(provider.fetch_order_flow, sym)
        except ProviderError as exc:
            snap.issues.append(f"Order flow unavailable: {exc}")

    # Freshness: every timeframe used by the engine must be current and gap-free
    # in the window the engine relies on.
    reasons = []
    for tf in timeframes:
        stale, why = is_stale(snap.candles.get(tf, []), tf, now)
        if stale:
            reasons.append(why)
    critical = {"1h": 4, "15m": 8, "5m": 24}
    for tf, window in critical.items():
        if tf in snap.reports and recent_gaps(snap.reports[tf], snap.candles.get(tf, []), window):
            reasons.append(f"Missing {tf} candles in the analysis window.")
    if snap.quote and snap.quote.time:
        age = (now - snap.quote.time).total_seconds()
        if age > settings.MARKET_DATA["QUOTE_MAX_AGE_SECONDS"] and provider.is_live:
            snap.issues.append(f"Quote is {int(age)}s old.")
    snap.stale = bool(reasons)
    snap.stale_reason = " ".join(reasons)
    return snap


def persist_candles(instrument, snapshot, keep_days=30):
    rows = []
    for tf, candles in snapshot.candles.items():
        for c in candles:
            rows.append(MarketCandle(
                instrument=instrument, provider=snapshot.provider, timeframe=tf, open_time=c.open_time,
                open=_dec(c.open), high=_dec(c.high), low=_dec(c.low), close=_dec(c.close), volume=_dec(c.volume),
                volume_type=snapshot.volume_type, is_sample=not snapshot.is_live,
            ))
    with transaction.atomic():
        if rows:
            MarketCandle.objects.bulk_create(
                rows, batch_size=500, update_conflicts=True,
                unique_fields=["instrument", "provider", "timeframe", "open_time"],
                update_fields=["open", "high", "low", "close", "volume", "volume_type", "is_sample", "fetched_at"],
            )
        cutoff = timezone.now() - datetime.timedelta(days=keep_days)
        MarketCandle.objects.filter(instrument=instrument, open_time__lt=cutoff).delete()
    return len(rows)


def load_candles(instrument, timeframe, limit=300, provider=None):
    """Load stored candles (ascending) as Candle objects, e.g. for charts and signal tracking."""
    qs = MarketCandle.objects.filter(instrument=instrument, timeframe=timeframe)
    if provider:
        qs = qs.filter(provider=provider)
    rows = list(qs.order_by("-open_time")[:limit])
    rows.reverse()
    return [Candle(r.open_time, float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume), timeframe)
            for r in rows]


def update_status(instrument, snapshot=None, error=None):
    status, _ = MarketDataStatus.objects.get_or_create(instrument=instrument)
    now = timezone.now()
    status.provider = snapshot.provider if snapshot else instrument.provider
    status.provider_symbol = instrument.provider_symbol
    if snapshot is not None:
        q = snapshot.quote
        status.is_live = snapshot.is_live
        status.last_price = _dec(snapshot.price) if snapshot.price is not None else None
        status.bid = _dec(q.bid) if q and q.bid else None
        status.ask = _dec(q.ask) if q and q.ask else None
        status.quote_time = (q.time if q and q.time else now)
        status.change_24h_pct = Decimal(f"{q.change_24h_pct:.3f}") if q and q.change_24h_pct is not None else None
        h1 = snapshot.candles.get("1h") or []
        ltf = snapshot.candles.get("5m") or h1
        status.last_candle_close_at = ltf[-1].close_time if ltf else None
        status.is_stale = snapshot.stale
        status.stale_reason = snapshot.stale_reason[:255]
        status.volume_type = snapshot.volume_type
        status.order_flow_available = bool(snapshot.order_flow and snapshot.order_flow.available)
        status.last_success_at = now
        status.consecutive_failures = 0
        status.last_error = "; ".join(snapshot.issues)[:2000]
    if error is not None:
        status.is_stale = True
        status.stale_reason = str(error)[:255]
        status.last_error = str(error)[:2000]
        status.last_error_at = now
        status.consecutive_failures += 1
    status.save()
    return status


def _dec(x):
    return Decimal(str(round(float(x), 8)))


def enabled_instruments():
    return MarketInstrument.objects.filter(is_enabled=True)
