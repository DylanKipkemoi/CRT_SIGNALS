"""Basic candle measurements used across the engine."""


def true_range(candle, prev_close=None):
    if prev_close is None:
        return candle.high - candle.low
    return max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close))


def atr(candles, period=14, end=None):
    """Simple average true range over ``period`` bars ending at index ``end`` (inclusive)."""
    if not candles:
        return 0.0
    end = len(candles) - 1 if end is None else end
    start = max(0, end - period + 1)
    trs = []
    for i in range(start, end + 1):
        prev = candles[i - 1].close if i > 0 else None
        trs.append(true_range(candles[i], prev))
    return sum(trs) / len(trs) if trs else 0.0


def is_displacement(candle, atr_value, cfg, direction=None):
    """A displacement candle has a large body relative to ATR and to its own range."""
    if atr_value <= 0 or candle.range <= 0:
        return False
    if direction == "bullish" and not candle.is_bullish:
        return False
    if direction == "bearish" and not candle.is_bearish:
        return False
    return candle.body >= cfg.displacement_atr_mult * atr_value and candle.body_ratio() >= cfg.displacement_body_ratio


def displacement_strength(candle, atr_value):
    """Body size in ATR units (0 when ATR unknown)."""
    return candle.body / atr_value if atr_value > 0 else 0.0
