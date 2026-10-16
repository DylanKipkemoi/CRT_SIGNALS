"""Price-action confirmation checks."""


def rejection_quality(candle, direction):
    """Wick-to-range ratio on the rejection side (0..1)."""
    if candle.range <= 0:
        return 0.0
    wick = candle.lower_wick if direction == "bullish" else candle.upper_wick
    return wick / candle.range


def is_engulfing(prev, cur, direction):
    if direction == "bullish":
        return cur.is_bullish and prev.is_bearish and cur.close >= prev.open and cur.open <= prev.close
    return cur.is_bearish and prev.is_bullish and cur.close <= prev.open and cur.open >= prev.close


def find_engulfing(candles, start, end, direction):
    for i in range(max(start, 1), min(end, len(candles) - 1) + 1):
        if is_engulfing(candles[i - 1], candles[i], direction):
            return i
    return None


def retest_index(candles, after_index, zone_low, zone_high):
    """First candle after ``after_index`` that trades into the zone."""
    for i in range(after_index + 1, len(candles)):
        c = candles[i]
        if c.low <= zone_high and c.high >= zone_low:
            return i
    return None
