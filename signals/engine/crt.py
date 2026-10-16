"""1-Hour Candle Range Theory (CRT).

Rules (all configurable via EngineConfig):

* Reference candle (C1): a completed 1H candle. Its high, low, midpoint and
  range define the CRT range. Its range must be >= ``crt_min_range_atr`` x ATR
  so tiny inside bars are ignored.
* Manipulation candle (C2): the next 1H candle.
  - Bullish CRT: C2 trades below C1.low by at least ``crt_min_sweep_frac`` of
    the range (sell-side sweep) but no more than ``crt_max_sweep_frac`` (deeper
    moves are treated as genuine breakdowns), and C2 closes back above C1.low
    (reclaim) without having swept C1.high as well.
  - Bearish CRT mirrors this above C1.high.
  - If C2 sweeps both sides, or closes outside the range, the setup is invalid.
* Expansion target: the opposite side of the reference range (C1.high for a
  bullish CRT), with the midpoint as the first objective.
* A sweep alone is never a signal: lower-timeframe confirmation (MSS + FVG/OB
  retest) is required by the engine.
"""

from dataclasses import dataclass


@dataclass
class CRTSetup:
    direction: str  # "bullish" | "bearish"
    ref_index: int
    ref_time: object
    ref_high: float
    ref_low: float
    manip_index: int
    manip_time: object
    sweep_price: float
    sweep_depth: float
    sweep_frac: float
    reclaim_close: float
    rejection_wick_ratio: float
    provisional: bool = False

    @property
    def ref_mid(self):
        return (self.ref_high + self.ref_low) / 2

    @property
    def ref_range(self):
        return self.ref_high - self.ref_low

    def as_dict(self):
        return {
            "direction": self.direction,
            "reference_candle_open": self.ref_time.isoformat(),
            "reference_high": self.ref_high,
            "reference_low": self.ref_low,
            "reference_mid": self.ref_mid,
            "manipulation_candle_open": self.manip_time.isoformat(),
            "sweep_price": self.sweep_price,
            "sweep_depth": self.sweep_depth,
            "sweep_fraction_of_range": round(self.sweep_frac, 4),
            "reclaim_close": self.reclaim_close,
            "rejection_wick_ratio": round(self.rejection_wick_ratio, 3),
            "provisional": self.provisional,
        }


def evaluate_pair(ref, manip, atr_value, cfg, ref_index=0, manip_index=1, provisional=False):
    """Return (CRTSetup | None, reason)."""
    rng = ref.range
    if rng <= 0:
        return None, "Reference candle has zero range."
    if atr_value > 0 and rng < cfg.crt_min_range_atr * atr_value:
        return None, "Reference candle range too small relative to ATR."
    swept_low = manip.low < ref.low
    swept_high = manip.high > ref.high
    if swept_low and swept_high:
        return None, "Manipulation candle swept both sides of the range (outside bar) — ambiguous."
    if not swept_low and not swept_high:
        return None, "No sweep of the reference high or low."
    if swept_low:
        depth = ref.low - manip.low
        frac = depth / rng
        if frac < cfg.crt_min_sweep_frac:
            return None, "Sell-side sweep too shallow."
        if frac > cfg.crt_max_sweep_frac:
            return None, "Move below the range too deep — treated as breakdown, not manipulation."
        if manip.close <= ref.low:
            return None, "Price swept the low but has not reclaimed the range."
        if manip.close > ref.high:
            return None, "Closed above the range — not a CRT reclaim."
        wick = manip.lower_wick / manip.range if manip.range else 0.0
        return CRTSetup("bullish", ref_index, ref.open_time, ref.high, ref.low, manip_index, manip.open_time,
                        manip.low, depth, frac, manip.close, wick, provisional), "Bullish CRT: sell-side sweep reclaimed."
    depth = manip.high - ref.high
    frac = depth / rng
    if frac < cfg.crt_min_sweep_frac:
        return None, "Buy-side sweep too shallow."
    if frac > cfg.crt_max_sweep_frac:
        return None, "Move above the range too deep — treated as breakout, not manipulation."
    if manip.close >= ref.high:
        return None, "Price swept the high but has not closed back inside the range."
    if manip.close < ref.low:
        return None, "Closed below the range — not a CRT reclaim."
    wick = manip.upper_wick / manip.range if manip.range else 0.0
    return CRTSetup("bearish", ref_index, ref.open_time, ref.high, ref.low, manip_index, manip.open_time,
                    manip.high, depth, frac, manip.close, wick, provisional), "Bearish CRT: buy-side sweep rejected."


def find_crt_setups(h1, atr_value, cfg, forming=None):
    """Evaluate the most recent completed (C1, C2) pairs, newest first.

    When ``forming`` (the incomplete current 1H candle) is given and provisional
    setups are allowed, the last completed candle is also evaluated as C1 with
    the forming candle as a provisional C2.
    """
    results = []
    n = len(h1)
    if forming is not None and cfg.allow_provisional and n >= 1:
        setup, reason = evaluate_pair(h1[-1], forming, atr_value, cfg, n - 1, n, provisional=True)
        results.append((setup, reason, n - 1))
    for k in range(cfg.crt_lookback_pairs):
        m = n - 1 - k
        r = m - 1
        if r < 0:
            break
        setup, reason = evaluate_pair(h1[r], h1[m], atr_value, cfg, r, m)
        results.append((setup, reason, r))
    return results
