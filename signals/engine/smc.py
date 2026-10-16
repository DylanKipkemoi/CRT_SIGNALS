"""ICT / SMC primitives with explicit, testable definitions.

Definitions
-----------
Swing high (pivot): bar i whose high is strictly greater than the highs of the
``lookback`` bars on each side. Swing low mirrors this. A pivot is only
confirmed ``lookback`` bars after it forms (no look-ahead).

Break of Structure (BOS): a candle *closes* beyond the most recent confirmed
swing in the direction of the prevailing trend.
Change of Character (CHOCH): a close beyond the most recent confirmed swing
against the prevailing trend. A CHOCH/BOS made by a displacement candle is a
Market Structure Shift (MSS).

Fair Value Gap (FVG): three-candle imbalance. Bullish when candle[i-2].high <
candle[i].low (gap = [c1.high, c3.low]); bearish when candle[i-2].low >
candle[i].high. Gaps smaller than ``fvg_min_atr_frac * ATR`` are ignored.

Order block (OB): the last opposite-coloured candle before the displacement leg
that produced a BOS/MSS. Bullish OB = last bearish candle before the bullish
break; zone = that candle's [low, high]. Bearish mirrors.

Liquidity: buy-side liquidity rests above swing highs (and equal highs),
sell-side below swing lows (and equal lows). A sweep is a wick beyond the level
with a close back on the original side.

Premium/discount: relative to the dealing range between the most recent
confirmed swing high and swing low; above equilibrium (50%) is premium.
"""

from dataclasses import dataclass, field

from .indicators import atr, is_displacement


@dataclass
class Swing:
    index: int
    price: float
    kind: str  # "high" | "low"
    time: object = None


@dataclass
class StructureBreak:
    index: int
    direction: str  # "bullish" | "bearish"
    kind: str  # "BOS" | "CHOCH"
    level: float
    swing_index: int
    displacement: bool
    time: object = None

    @property
    def is_mss(self):
        return self.kind == "CHOCH" and self.displacement

    def as_dict(self):
        return {
            "index": self.index, "direction": self.direction, "kind": self.kind, "level": self.level,
            "displacement": self.displacement, "mss": self.is_mss, "time": self.time.isoformat() if self.time else None,
        }


@dataclass
class FairValueGap:
    index: int  # index of the third candle
    direction: str
    bottom: float
    top: float
    time: object = None
    mitigated: bool = False
    filled: bool = False

    @property
    def mid(self):
        return (self.top + self.bottom) / 2

    def as_dict(self):
        return {"type": "FVG", "direction": self.direction, "bottom": self.bottom, "top": self.top,
                "time": self.time.isoformat() if self.time else None, "mitigated": self.mitigated, "filled": self.filled}


@dataclass
class OrderBlock:
    index: int
    direction: str
    low: float
    high: float
    time: object = None
    mitigated: bool = False

    def as_dict(self):
        return {"type": "OB", "direction": self.direction, "bottom": self.low, "top": self.high,
                "time": self.time.isoformat() if self.time else None, "mitigated": self.mitigated}


@dataclass
class LiquidityLevel:
    price: float
    side: str  # "buy" (above highs) | "sell" (below lows)
    touches: int = 1
    swept: bool = False
    indices: list = field(default_factory=list)


def find_swings(candles, lookback):
    swings = []
    n = len(candles)
    for i in range(lookback, n - lookback):
        hi = candles[i].high
        lo = candles[i].low
        left = candles[i - lookback:i]
        right = candles[i + 1:i + 1 + lookback]
        if all(hi > c.high for c in left) and all(hi > c.high for c in right):
            swings.append(Swing(i, hi, "high", candles[i].open_time))
        if all(lo < c.low for c in left) and all(lo < c.low for c in right):
            swings.append(Swing(i, lo, "low", candles[i].open_time))
    return swings


def trend_from_swings(swings):
    highs = [s for s in swings if s.kind == "high"][-2:]
    lows = [s for s in swings if s.kind == "low"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return "ranging"
    hh, hl = highs[1].price > highs[0].price, lows[1].price > lows[0].price
    lh, ll = highs[1].price < highs[0].price, lows[1].price < lows[0].price
    if hh and hl:
        return "bullish"
    if lh and ll:
        return "bearish"
    return "ranging"


def detect_structure_breaks(candles, lookback, cfg, start_index=0):
    """Walk candles in order and emit BOS/CHOCH events using only confirmed swings."""
    swings = find_swings(candles, lookback)
    confirmed_at = {}
    for s in swings:
        confirmed_at.setdefault(s.index + lookback, []).append(s)
    trend = "ranging"
    last_high = last_low = None
    broken_high = broken_low = None
    events = []
    for i, c in enumerate(candles):
        for s in confirmed_at.get(i, []):
            if s.kind == "high":
                last_high = s
            else:
                last_low = s
        if i < start_index:
            # still track trend from earlier breaks
            pass
        a = atr(candles, cfg.atr_period, i - 1) if i > 0 else c.range
        if last_high and broken_high is not last_high and c.close > last_high.price and i > last_high.index:
            kind = "BOS" if trend == "bullish" else "CHOCH"
            disp = is_displacement(c, a, cfg, "bullish")
            if i >= start_index:
                events.append(StructureBreak(i, "bullish", kind, last_high.price, last_high.index, disp, c.open_time))
            trend = "bullish"
            broken_high = last_high
        if last_low and broken_low is not last_low and c.close < last_low.price and i > last_low.index:
            kind = "BOS" if trend == "bearish" else "CHOCH"
            disp = is_displacement(c, a, cfg, "bearish")
            if i >= start_index:
                events.append(StructureBreak(i, "bearish", kind, last_low.price, last_low.index, disp, c.open_time))
            trend = "bearish"
            broken_low = last_low
    return events, trend


def find_fvgs(candles, cfg, start_index=2):
    gaps = []
    for i in range(max(2, start_index), len(candles)):
        c1, c3 = candles[i - 2], candles[i]
        a = atr(candles, cfg.atr_period, i)
        min_size = cfg.fvg_min_atr_frac * a
        if c1.high < c3.low and (c3.low - c1.high) >= min_size:
            gaps.append(FairValueGap(i, "bullish", c1.high, c3.low, candles[i - 1].open_time))
        elif c1.low > c3.high and (c1.low - c3.high) >= min_size:
            gaps.append(FairValueGap(i, "bearish", c3.high, c1.low, candles[i - 1].open_time))
    for g in gaps:
        for c in candles[g.index + 1:]:
            if g.direction == "bullish":
                if c.low <= g.top:
                    g.mitigated = True
                if c.low <= g.bottom:
                    g.filled = True
            else:
                if c.high >= g.bottom:
                    g.mitigated = True
                if c.high >= g.top:
                    g.filled = True
    return gaps


def find_order_block(candles, break_event, search_from=0):
    """Last opposite candle before the displacement leg that caused ``break_event``."""
    want_bearish = break_event.direction == "bullish"
    for i in range(break_event.index - 1, max(search_from, 0) - 1, -1):
        c = candles[i]
        if (want_bearish and c.is_bearish) or (not want_bearish and c.is_bullish):
            ob = OrderBlock(i, break_event.direction, c.low, c.high, c.open_time)
            for later in candles[break_event.index + 1:]:
                if (want_bearish and later.low <= ob.high) or (not want_bearish and later.high >= ob.low):
                    ob.mitigated = True
                    break
            return ob
    return None


def liquidity_levels(candles, swings, atr_value, cfg):
    """Cluster swing highs/lows into liquidity pools (equal highs/lows get more touches)."""
    tol = cfg.equal_level_atr_frac * atr_value
    pools = []
    for s in swings:
        side = "buy" if s.kind == "high" else "sell"
        for p in pools:
            if p.side == side and abs(p.price - s.price) <= tol:
                p.touches += 1
                p.price = max(p.price, s.price) if side == "buy" else min(p.price, s.price)
                p.indices.append(s.index)
                break
        else:
            pools.append(LiquidityLevel(s.price, side, 1, False, [s.index]))
    for p in pools:
        after = candles[max(p.indices) + 1:]
        if p.side == "buy":
            p.swept = any(c.high > p.price for c in after)
        else:
            p.swept = any(c.low < p.price for c in after)
    return pools


def dealing_range(swings):
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if not highs or not lows:
        return None
    hi, lo = highs[-1].price, lows[-1].price
    if hi <= lo:
        return None
    return {"high": hi, "low": lo, "equilibrium": (hi + lo) / 2}


def premium_discount(price, rng):
    if not rng:
        return "unknown", None
    pos = (price - rng["low"]) / (rng["high"] - rng["low"])
    if pos > 0.5:
        return "premium", pos
    if pos < 0.5:
        return "discount", pos
    return "equilibrium", pos
