"""Signal lifecycle tracking against completed candles.

Rules (conservative, documented in docs/SCORING.md):
* ACTIVE -> TRIGGERED when a candle trades into the entry zone.
* ACTIVE -> INVALIDATED if the stop or TP1 is reached before entry.
* ACTIVE -> EXPIRED when expires_at passes without entry.
* TRIGGERED: if a candle touches both the stop and a target, the stop is
  assumed to have been hit first.
* Position is split equally across the targets; after TP1 the stop moves to
  entry (breakeven). Realized R is the average across those parts.
* TRIGGERED -> CLOSED on the final target, stop/breakeven, or trade timeout.
"""

import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import OPEN_STATUSES, Outcome, SignalEvent, SignalStatus, TradingSignal

TP_OUTCOMES = {1: Outcome.TP1, 2: Outcome.TP2, 3: Outcome.TP3}


def _event(signal, event_type, to_status=None, price=None, note="", at=None):
    SignalEvent.objects.create(
        signal=signal, event_type=event_type, from_status=signal.status, to_status=to_status or signal.status,
        price=Decimal(str(price)) if price is not None else None, note=note[:255], occurred_at=at or timezone.now(),
    )
    if to_status:
        signal.status = to_status


def _realized_r(signal, exit_part_r):
    targets = signal.targets
    n = len(targets)
    hit = signal.max_tp_hit
    parts = [signal.r_multiple(t) for t in targets[:hit]]
    remaining = n - hit
    total = sum(parts, Decimal("0")) + Decimal(remaining) * Decimal(str(exit_part_r))
    return (total / n).quantize(Decimal("0.01"))


def _close(signal, outcome, exit_price, exit_part_r, at, note):
    signal.outcome = outcome
    signal.exit_price = Decimal(str(exit_price))
    signal.realized_r = _realized_r(signal, exit_part_r)
    signal.closed_at = at
    _event(signal, "closed", SignalStatus.CLOSED, exit_price, note, at)


def apply_candles(signal: TradingSignal, candles, now=None, trade_timeout_hours=48):
    """Advance an open signal through ``candles`` (completed, ascending). Returns True if changed."""
    if signal.status not in OPEN_STATUSES or signal.status == SignalStatus.PROVISIONAL:
        return False
    now = now or timezone.now()
    start_status, start_tp = signal.status, signal.max_tp_hit
    bull = signal.direction == "BUY"
    lo, hi = float(signal.entry_low), float(signal.entry_high)
    stop = float(signal.stop_loss)
    targets = [float(t) for t in signal.targets]
    after = signal.last_checked_at or signal.created_at

    for c in candles:
        if c.open_time < after or c.open_time < signal.created_at:
            continue
        at = c.close_time
        if signal.status == SignalStatus.ACTIVE:
            if at > signal.expires_at and c.open_time >= signal.expires_at:
                break
            hit_stop = c.low <= stop if bull else c.high >= stop
            touched = c.low <= hi and c.high >= lo
            hit_tp1 = c.high >= targets[0] if bull else c.low <= targets[0]
            if touched:
                signal.triggered_at = at
                _event(signal, "triggered", SignalStatus.TRIGGERED, signal.entry_price, "Entry zone reached", at)
                if hit_stop:
                    _close(signal, Outcome.STOP, stop, -1, at, "Stop loss hit in entry candle")
                    break
                continue
            if hit_stop:
                signal.outcome = Outcome.INVALIDATED
                signal.closed_at = at
                _event(signal, "invalidated", SignalStatus.INVALIDATED, stop, "Stop level reached before entry", at)
                break
            if hit_tp1:
                signal.outcome = Outcome.INVALIDATED
                signal.closed_at = at
                _event(signal, "invalidated", SignalStatus.INVALIDATED, targets[0], "TP1 reached before entry (missed)", at)
                break
        elif signal.status == SignalStatus.TRIGGERED:
            current_stop = float(signal.entry_price) if signal.max_tp_hit >= 1 else stop
            hit_stop = c.low <= current_stop if bull else c.high >= current_stop
            if hit_stop:
                if signal.max_tp_hit >= 1:
                    _close(signal, TP_OUTCOMES[signal.max_tp_hit], current_stop, 0, at, "Breakeven stop after TP")
                else:
                    _close(signal, Outcome.STOP, stop, -1, at, "Stop loss hit")
                break
            for level in range(signal.max_tp_hit + 1, len(targets) + 1):
                t = targets[level - 1]
                if (c.high >= t) if bull else (c.low <= t):
                    signal.max_tp_hit = level
                    _event(signal, f"tp{level}_hit", None, t, f"Take-profit {level} reached", at)
            if signal.max_tp_hit == len(targets):
                _close(signal, TP_OUTCOMES[signal.max_tp_hit], targets[-1], 0, at, "Final target reached")
                break
            if signal.triggered_at and at - signal.triggered_at >= datetime.timedelta(hours=trade_timeout_hours):
                part_r = signal.r_multiple(c.close)
                _close(signal, TP_OUTCOMES.get(signal.max_tp_hit, Outcome.TIMEOUT) if signal.max_tp_hit else Outcome.TIMEOUT,
                       c.close, part_r, at, "Trade timeout")
                break
        signal.last_checked_at = c.close_time

    if signal.status == SignalStatus.ACTIVE and now >= signal.expires_at:
        signal.outcome = Outcome.EXPIRED
        signal.closed_at = signal.expires_at
        _event(signal, "expired", SignalStatus.EXPIRED, None, "Entry not reached before expiry", signal.expires_at)
    changed = signal.status != start_status or signal.max_tp_hit != start_tp
    signal.save()
    return changed


def update_open_signals(instrument, candles, now=None, trade_timeout_hours=48):
    now = now or timezone.now()
    updated = 0
    open_qs = TradingSignal.objects.filter(instrument=instrument, status__in=OPEN_STATUSES)
    for signal in open_qs:
        with transaction.atomic():
            signal = TradingSignal.objects.select_for_update().get(pk=signal.pk)
            if signal.status == SignalStatus.PROVISIONAL:
                if now >= signal.ref_candle_open + datetime.timedelta(hours=2):
                    signal.outcome = Outcome.INVALIDATED
                    signal.closed_at = now
                    _event(signal, "provisional_lapsed", SignalStatus.INVALIDATED, None,
                           "Provisional setup was not confirmed when the 1H candle closed", now)
                    signal.save()
                    updated += 1
                continue
            if apply_candles(signal, candles, now, trade_timeout_hours):
                updated += 1
    return updated
