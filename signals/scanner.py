"""Market scanner: fetch data -> run engine -> persist signals -> track lifecycle."""

import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import SiteConfiguration
from markets import services as md
from markets.providers import ProviderError, ProviderNotConfigured

from .engine import EngineConfig, analyze
from .models import OPEN_STATUSES, InstrumentAnalysis, MarketScanRun, SignalEvent, SignalStatus, TradingSignal
from .tracking import update_open_signals

logger = logging.getLogger(__name__)
LOCK_KEY = "scanner:lock"


def _q(x, digits):
    return Decimal(str(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def save_signal(instrument, snapshot, cand, site, now):
    """Persist a qualifying candidate once (setup_key is unique). Returns the signal or None."""
    if TradingSignal.objects.filter(setup_key=cand.setup_key).exists():
        return None
    if not cand.provisional and TradingSignal.objects.filter(
        instrument=instrument, direction=cand.direction,
        status__in=[SignalStatus.ACTIVE, SignalStatus.TRIGGERED],
    ).exists():
        return None
    d = instrument.price_decimals
    targets = [_q(t, d) for t in cand.targets]
    entry_low, entry_high = _q(cand.entry_low, d), _q(cand.entry_high, d)
    entry = _q(cand.entry, d)
    stop = _q(cand.stop, d)
    # Quantization must not collapse levels onto the wrong side.
    if cand.direction == "BUY" and not (stop < entry_low and targets[0] > entry_high):
        return None
    if cand.direction == "SELL" and not (stop > entry_high and targets[0] < entry_low):
        return None
    s = cand.crt
    try:
        with transaction.atomic():
            signal = TradingSignal.objects.create(
                instrument=instrument,
                direction=cand.direction,
                status=SignalStatus.PROVISIONAL if cand.provisional else SignalStatus.ACTIVE,
                is_provisional=cand.provisional,
                is_sample=not snapshot.is_live,
                score=cand.score,
                score_breakdown=cand.breakdown,
                classification=cand.classification,
                setup_type=cand.setup_type,
                entry_low=entry_low, entry_high=entry_high, entry_price=entry, stop_loss=stop,
                take_profit_1=targets[0],
                take_profit_2=targets[1] if len(targets) > 1 else None,
                take_profit_3=targets[2] if len(targets) > 2 else None,
                risk_reward=Decimal(f"{cand.rr_final:.2f}"),
                risk_reward_tp1=Decimal(f"{cand.rr_tp1:.2f}"),
                ref_candle_open=s.ref_time, ref_high=_q(s.ref_high, d), ref_low=_q(s.ref_low, d), ref_mid=_q(s.ref_mid, d),
                sweep_details=cand.context.get("sweep", s.as_dict()),
                structure_details=cand.structure,
                poi_details=cand.poi,
                order_flow_status=cand.order_flow_status,
                order_flow_details=cand.order_flow_details,
                market_context={k: v for k, v in cand.context.items() if k not in ("sweep",)},
                timeframes=f"1H / {EngineConfig().confirmation_timeframe.upper()}",
                provider=snapshot.provider_name,
                provider_symbol=snapshot.provider_symbol,
                explanation=cand.explanation,
                invalidation_conditions=cand.invalidation,
                setup_key=cand.setup_key,
                created_at=now,
                expires_at=now + datetime.timedelta(hours=site.signal_expiry_hours),
            )
            SignalEvent.objects.create(signal=signal, event_type="created", to_status=signal.status,
                                       price=entry, note=f"{cand.classification} {cand.score}/100", occurred_at=now)
            if not cand.provisional:
                for prov in TradingSignal.objects.filter(setup_key=cand.setup_key + ":P", status=SignalStatus.PROVISIONAL):
                    SignalEvent.objects.create(signal=prov, event_type="confirmed", from_status=prov.status,
                                               to_status=SignalStatus.SUPERSEDED, note=f"Confirmed as #{signal.pk}",
                                               occurred_at=now)
                    prov.status = SignalStatus.SUPERSEDED
                    prov.superseded_by = signal
                    prov.closed_at = now
                    prov.save(update_fields=["status", "superseded_by", "closed_at"])
            return signal
    except IntegrityError:
        logger.info("Duplicate setup %s ignored", cand.setup_key)
        return None


def scan_instrument(instrument, run, site, cfg, now, provider=None):
    result_info = {"symbol": instrument.symbol}
    try:
        snapshot = md.fetch_snapshot(instrument, provider=provider, now=now)
    except ProviderNotConfigured as exc:
        md.update_status(instrument, error=exc)
        InstrumentAnalysis.objects.update_or_create(instrument=instrument, defaults={
            "state": InstrumentAnalysis.State.UNAVAILABLE, "summary": f"Feed not configured: {exc}"[:255],
            "details": {}, "scan_run": run, "best_score": None, "bias": ""})
        return result_info | {"state": "UNAVAILABLE", "error": str(exc), "not_configured": True}, 0, 0
    except ProviderError as exc:
        md.update_status(instrument, error=exc)
        InstrumentAnalysis.objects.update_or_create(instrument=instrument, defaults={
            "state": InstrumentAnalysis.State.UNAVAILABLE, "summary": f"Feed error: {exc}"[:255],
            "details": {}, "scan_run": run, "best_score": None, "bias": ""})
        raise

    md.persist_candles(instrument, snapshot)
    md.update_status(instrument, snapshot)
    ltf = snapshot.candles.get(cfg.confirmation_timeframe, [])
    result = analyze(
        instrument.symbol, snapshot.candles.get("1h", []), ltf, cfg,
        price=snapshot.price, order_flow=snapshot.order_flow, forming_h1=snapshot.forming.get("1h"),
        data_fresh=not snapshot.stale, digits=instrument.price_decimals,
    )
    created = 0
    for cand in sorted(result.candidates, key=lambda c: (c.provisional, -c.score)):
        if cand.qualifies and (not cand.provisional or cfg.allow_provisional):
            if save_signal(instrument, snapshot, cand, site, now):
                created += 1
    updated = update_open_signals(instrument, ltf, now, site.trade_timeout_hours)

    details = result.as_dict()
    details["data"] = {"provider": snapshot.provider_name, "provider_symbol": snapshot.provider_symbol,
                       "is_live": snapshot.is_live, "stale": snapshot.stale, "stale_reason": snapshot.stale_reason,
                       "issues": snapshot.issues, "volume_type": snapshot.volume_type,
                       "order_flow": snapshot.order_flow.as_dict() if snapshot.order_flow else None}
    state = result.state
    if snapshot.stale:
        state = "NO_TRADE"
    best_score = max((c.score for c in result.candidates), default=None)
    InstrumentAnalysis.objects.update_or_create(instrument=instrument, defaults={
        "state": state, "bias": result.bias, "best_score": best_score, "summary": result.summary[:255],
        "details": details, "scan_run": run})
    return result_info | {"state": state, "summary": result.summary, "created": created, "updated": updated,
                          "stale": snapshot.stale}, created, updated


def run_scan(trigger=MarketScanRun.Trigger.SCHEDULER, user=None, now=None, providers=None):
    """Scan all enabled instruments. ``providers`` maps symbol -> provider instance (tests)."""
    site = SiteConfiguration.load()
    if trigger == MarketScanRun.Trigger.SCHEDULER and not site.scanner_enabled:
        return MarketScanRun.objects.create(trigger=trigger, status=MarketScanRun.Status.SKIPPED,
                                            finished_at=timezone.now(), errors=["Scanner disabled in configuration."])
    if not cache.add(LOCK_KEY, "1", settings.SCANNER["LOCK_SECONDS"]):
        return MarketScanRun.objects.create(trigger=trigger, triggered_by=user, status=MarketScanRun.Status.SKIPPED,
                                            finished_at=timezone.now(), errors=["Another scan is already running."])
    run = MarketScanRun.objects.create(trigger=trigger, triggered_by=user)
    try:
        now = now or timezone.now()
        cfg = EngineConfig.from_site_config(site)
        failures = 0
        instruments = list(md.enabled_instruments())
        for instrument in instruments:
            try:
                info, created, updated = scan_instrument(
                    instrument, run, site, cfg, now, provider=(providers or {}).get(instrument.symbol))
                run.results[instrument.symbol] = info
                run.signals_created += created
                run.signals_updated += updated
            except Exception as exc:  # noqa: BLE001 - one instrument must not break the scan
                failures += 1
                logger.exception("Scan failed for %s", instrument.symbol)
                run.errors.append(f"{instrument.symbol}: {exc.__class__.__name__}: {exc}"[:500])
                run.results[instrument.symbol] = {"symbol": instrument.symbol, "state": "UNAVAILABLE", "error": str(exc)}
            run.instruments_scanned += 1
        if failures == 0:
            run.status = MarketScanRun.Status.SUCCESS
        elif failures < len(instruments):
            run.status = MarketScanRun.Status.PARTIAL
        else:
            run.status = MarketScanRun.Status.FAILED
    except Exception as exc:  # noqa: BLE001
        logger.exception("Scan run failed")
        run.status = MarketScanRun.Status.FAILED
        run.errors.append(f"{exc.__class__.__name__}: {exc}"[:500])
    finally:
        run.finished_at = timezone.now()
        run.save()
        cache.delete(LOCK_KEY)
    return run


def scanner_health():
    last = MarketScanRun.objects.exclude(status=MarketScanRun.Status.SKIPPED).first()
    if last is None:
        return {"status": "never_run", "label": "Scanner has not run yet", "last": None, "healthy": False}
    age = (timezone.now() - last.started_at).total_seconds()
    healthy = last.status in (MarketScanRun.Status.SUCCESS, MarketScanRun.Status.PARTIAL) and \
        age <= settings.SCANNER["HEALTHY_MAX_AGE_SECONDS"]
    label = "Healthy" if healthy else ("Overdue" if age > settings.SCANNER["HEALTHY_MAX_AGE_SECONDS"] else "Errors")
    return {"status": last.status, "label": label, "last": last, "healthy": healthy, "age_seconds": int(age)}


def open_signals():
    return TradingSignal.objects.filter(status__in=OPEN_STATUSES)
