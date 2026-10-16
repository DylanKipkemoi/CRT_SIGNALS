"""Signal engine: 1H CRT + LTF ICT/SMC confirmation + scoring.

Pure functions over Candle lists — no database or network access — so every
rule is unit-testable with offline sample data.
"""

from dataclasses import dataclass, field

from . import crt as crt_mod
from . import price_action as pa
from . import smc
from .indicators import atr, displacement_strength
from .risk import InvalidLevels, risk_reward, validate_levels
from .scoring import classify, clamp, order_flow_quality, score


@dataclass
class SetupCandidate:
    symbol: str
    direction: str  # BUY | SELL
    crt: object
    provisional: bool = False
    mss: object = None
    poi: dict = field(default_factory=dict)
    entry_low: float | None = None
    entry_high: float | None = None
    entry: float | None = None
    stop: float | None = None
    targets: list = field(default_factory=list)
    rr_final: float | None = None
    rr_tp1: float | None = None
    score: int = 0
    breakdown: dict = field(default_factory=dict)
    classification: str = "C"
    order_flow_status: str = "unavailable"
    order_flow_details: dict = field(default_factory=dict)
    rejections: list = field(default_factory=list)
    context: dict = field(default_factory=dict)
    structure: dict = field(default_factory=dict)
    explanation: str = ""
    invalidation: str = ""
    qualifies: bool = False

    @property
    def setup_key(self):
        key = f"{self.symbol}:{self.direction}:{self.crt.ref_time:%Y%m%d%H}"
        return key + ":P" if self.provisional else key

    @property
    def setup_type(self):
        side = "sell-side" if self.direction == "BUY" else "buy-side"
        mss = self.mss.kind if self.mss else "no MSS"
        poi = self.poi.get("type", "no POI")
        return f"1H CRT {side} sweep + {mss} + {poi} entry"

    def summary(self):
        if self.qualifies:
            return f"{self.direction} {self.classification} setup {self.score}/100"
        reason = self.rejections[0] if self.rejections else f"score {self.score}/100 below threshold"
        return f"{self.direction} setup forming ({self.score}/100): {reason}"


@dataclass
class AnalysisResult:
    symbol: str
    state: str  # BUY | SELL | WAIT | NO_TRADE
    bias: str
    candidates: list
    best: SetupCandidate | None
    summary: str
    notes: list = field(default_factory=list)
    context: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "state": self.state,
            "bias": self.bias,
            "summary": self.summary,
            "notes": self.notes,
            "context": self.context,
            "candidates": [
                {"direction": c.direction, "score": c.score, "classification": c.classification,
                 "provisional": c.provisional, "qualifies": c.qualifies, "rejections": c.rejections,
                 "summary": c.summary()}
                for c in self.candidates
            ],
        }


def _fmt(x, digits=2):
    return f"{x:,.{digits}f}"


def _targets(direction, crt, entry_high, entry_low, liquidity, tol, price=None):
    """Structural targets beyond both the entry zone and the current price (levels already traded are not targets)."""
    if direction == "BUY":
        floor = max(entry_high, price) if price is not None else entry_high
        cands = [crt.ref_mid, crt.ref_high] + sorted(p.price for p in liquidity if p.side == "buy" and not p.swept)
        cands = sorted(t for t in cands if t > floor)
    else:
        ceiling = min(entry_low, price) if price is not None else entry_low
        cands = [crt.ref_mid, crt.ref_low] + sorted((p.price for p in liquidity if p.side == "sell" and not p.swept),
                                                    reverse=True)
        cands = sorted((t for t in cands if t < ceiling), reverse=True)
    out = []
    for t in cands:
        if not out or abs(t - out[-1]) > tol:
            out.append(t)
    return out[:3]


def _evaluate(symbol, setup, h1, ltf, price, order_flow, cfg, ctx, digits):
    direction = "BUY" if setup.direction == "bullish" else "SELL"
    bull = direction == "BUY"
    cand = SetupCandidate(symbol, direction, setup, provisional=setup.provisional, context=dict(ctx))
    atr_h1 = ctx["atr_h1"]

    window_start = next((i for i, c in enumerate(ltf) if c.open_time >= setup.manip_time), None)
    if window_start is None:
        cand.rejections.append("No lower-timeframe data since the manipulation candle opened.")
        return _finish(cand, cfg, order_flow, {}, digits)
    window = range(window_start, len(ltf))
    extreme_idx = min(window, key=lambda i: ltf[i].low) if bull else max(window, key=lambda i: ltf[i].high)
    atr_ltf = atr(ltf, cfg.atr_period, len(ltf) - 1)

    breaks, _ = smc.detect_structure_breaks(ltf, cfg.swing_lookback_ltf, cfg, start_index=extreme_idx + 1)
    want = "bullish" if bull else "bearish"
    mss = next((b for b in breaks if b.direction == want and b.index > extreme_idx), None)
    qualities, notes = {}, {}

    # CRT alignment
    strong_reclaim = setup.reclaim_close > setup.ref_mid if bull else setup.reclaim_close < setup.ref_mid
    pd_zone = ctx.get("pd_zone")
    pd_aligned = (pd_zone == "discount") if bull else (pd_zone == "premium")
    bias_aligned = ctx.get("htf_bias") == ("bullish" if bull else "bearish")
    q = 0.6 + (0.2 if strong_reclaim else 0) + (0.2 if (pd_aligned or bias_aligned) else 0)
    if setup.provisional:
        q *= 0.7
    qualities["crt_alignment"] = q
    notes["crt_alignment"] = (f"{'Bullish' if bull else 'Bearish'} CRT on {setup.ref_time:%H:%M} UTC reference; "
                              f"reclaim {'beyond' if strong_reclaim else 'inside'} midpoint"
                              + ("; provisional (candle still forming)" if setup.provisional else ""))

    # Liquidity sweep quality
    swept_level = setup.ref_low if bull else setup.ref_high
    tol = cfg.equal_level_atr_frac * atr_h1 * 2
    pool_hit = any(abs(p.price - swept_level) <= tol and p.side == ("sell" if bull else "buy") for p in ctx["_liquidity"])
    sweet = 0.5 if 0.08 <= setup.sweep_frac <= 0.5 else 0.3
    qualities["liquidity_sweep"] = sweet + clamp(setup.rejection_wick_ratio / 0.6) * 0.3 + (0.2 if pool_hit else 0)
    notes["liquidity_sweep"] = (f"Swept {'low' if bull else 'high'} {_fmt(swept_level, digits)} by "
                                f"{setup.sweep_frac:.0%} of range; rejection wick {setup.rejection_wick_ratio:.0%}"
                                + ("; level coincided with resting liquidity" if pool_hit else ""))
    cand.context["sweep"] = setup.as_dict() | {"liquidity_pool": pool_hit}

    if mss is None:
        cand.rejections.append(f"Awaiting {cfg.confirmation_timeframe} market-structure shift after the sweep.")
        qualities["structure_shift"] = 0.0
        return _finish(cand, cfg, order_flow, qualities, digits, notes)

    cand.mss = mss
    qualities["structure_shift"] = {("CHOCH", True): 1.0, ("BOS", True): 0.8, ("CHOCH", False): 0.6,
                                    ("BOS", False): 0.5}[(mss.kind, mss.displacement)]
    notes["structure_shift"] = (f"{cfg.confirmation_timeframe} {mss.kind}{' (MSS)' if mss.is_mss else ''} through "
                                f"{_fmt(mss.level, digits)} at {mss.time:%H:%M} UTC")
    cand.structure = {"ltf_break": mss.as_dict(), "htf_bias": ctx.get("htf_bias"),
                      "htf_breaks": ctx.get("htf_breaks", [])}

    leg = ltf[extreme_idx:mss.index + 1]
    strength = max((displacement_strength(c, atr_ltf) for c in leg if (c.is_bullish if bull else c.is_bearish)),
                   default=0.0)
    qualities["displacement"] = clamp((strength - 0.5) / 1.5)
    notes["displacement"] = f"Strongest leg candle body {strength:.2f}x {cfg.confirmation_timeframe} ATR"

    fvgs = [g for g in smc.find_fvgs(ltf, cfg, start_index=extreme_idx + 2)
            if g.direction == want and g.index <= mss.index + 2 and not g.filled]
    fvg = fvgs[-1] if fvgs else None
    ob = smc.find_order_block(ltf, mss, search_from=max(0, extreme_idx - 3))
    if ob and ob.index < extreme_idx - 3:
        ob = None
    if fvg and ob and ob.low <= fvg.top and ob.high >= fvg.bottom:
        zone = (max(fvg.bottom, ob.low), min(fvg.top, ob.high))
        if zone[1] - zone[0] < 0.1 * atr_ltf:
            zone = (fvg.bottom, fvg.top)
        cand.poi = {"type": "FVG + OB", "fvg": fvg.as_dict(), "order_block": ob.as_dict()}
        qualities["entry_confluence"] = 1.0
    elif fvg:
        zone = (fvg.bottom, fvg.top)
        cand.poi = {"type": "FVG", "fvg": fvg.as_dict(), "order_block": ob.as_dict() if ob else None}
        qualities["entry_confluence"] = 0.75
    elif ob:
        zone = (ob.low, ob.high)
        cand.poi = {"type": "OB", "fvg": None, "order_block": ob.as_dict()}
        qualities["entry_confluence"] = 0.6
    else:
        cand.rejections.append("No unfilled FVG or order block in the displacement leg to define entry.")
        qualities["entry_confluence"] = 0.0
        return _finish(cand, cfg, order_flow, qualities, digits, notes)
    notes["entry_confluence"] = f"Entry zone {_fmt(zone[0], digits)} – {_fmt(zone[1], digits)} from {cand.poi['type']}"

    cand.entry_low, cand.entry_high = zone
    cand.entry = (zone[0] + zone[1]) / 2
    buffer = cfg.stop_buffer_atr_frac * atr_ltf
    cand.stop = (setup.sweep_price - buffer) if bull else (setup.sweep_price + buffer)
    cand.targets = _targets(direction, setup, cand.entry_high, cand.entry_low, ctx["_liquidity"], 0.1 * atr_h1,
                            price if price is not None else (ltf[-1].close if ltf else None))

    # Price action
    rej = setup.rejection_wick_ratio
    break_candle = ltf[mss.index]
    engulf = pa.find_engulfing(ltf, extreme_idx, mss.index, want)
    poi_index = (fvg.index if fvg else mss.index)
    retest = pa.retest_index(ltf, poi_index, cand.entry_low, cand.entry_high)
    pa_q = clamp(rej / 0.5) * 0.3 + (0.3 if break_candle.body_ratio() >= cfg.displacement_body_ratio else 0.1)
    pa_q += 0.2 if engulf is not None else 0
    pa_q += 0.2 if retest is not None else 0.1
    qualities["price_action"] = pa_q
    notes["price_action"] = ", ".join(filter(None, [
        f"1H rejection wick {rej:.0%}",
        f"break candle body {break_candle.body_ratio():.0%}",
        "engulfing at reversal" if engulf is not None else "",
        "zone retested" if retest is not None else "awaiting retest",
    ]))
    cand.structure["retest_time"] = ltf[retest].open_time.isoformat() if retest is not None else None

    # Order flow
    status, of_q, of_note = order_flow_quality(order_flow, direction, cfg)
    cand.order_flow_status = status
    cand.order_flow_details = (order_flow.as_dict() if order_flow is not None else {"available": False}) | {"note": of_note}
    qualities["order_flow"] = of_q
    notes["order_flow"] = of_note
    if status == "unavailable" and cfg.require_order_flow:
        cand.rejections.append("Order-flow confirmation required but unavailable.")
    if status == "opposing":
        cand.rejections.append("Order flow opposes the trade direction.")

    # Levels & risk checks
    if not cand.targets:
        cand.rejections.append("No structural take-profit target beyond the entry zone.")
        qualities["risk_reward"] = 0.0
        return _finish(cand, cfg, order_flow, qualities, digits, notes)
    try:
        validate_levels(direction, cand.entry_low, cand.entry_high, cand.stop, cand.targets)
        cand.rr_final = risk_reward(direction, cand.entry, cand.stop, cand.targets[-1])
        cand.rr_tp1 = risk_reward(direction, cand.entry, cand.stop, cand.targets[0])
    except InvalidLevels as exc:
        cand.rejections.append(str(exc))
        qualities["risk_reward"] = 0.0
        return _finish(cand, cfg, order_flow, qualities, digits, notes)

    stop_atr = abs(cand.entry - cand.stop) / atr_h1 if atr_h1 else 0
    rr_q = 0.0
    if cand.rr_final >= cfg.min_risk_reward:
        rr_q = 0.6 + 0.4 * clamp((cand.rr_final - cfg.min_risk_reward) / max(3.0 - cfg.min_risk_reward, 0.01))
    if stop_atr > cfg.max_stop_atr:
        cand.rejections.append(f"Stop is {stop_atr:.1f} ATR from entry (max {cfg.max_stop_atr}).")
        rr_q *= 0.5
    if cand.rr_final < cfg.min_risk_reward:
        cand.rejections.append(f"Risk:reward 1:{cand.rr_final:.2f} below minimum 1:{cfg.min_risk_reward:.2f}.")
    qualities["risk_reward"] = rr_q
    notes["risk_reward"] = f"1:{cand.rr_final:.2f} to final target, 1:{cand.rr_tp1:.2f} to TP1; stop {stop_atr:.2f}x 1H ATR"

    if price is not None:
        if (bull and price <= cand.stop) or (not bull and price >= cand.stop):
            cand.rejections.append("Price is already beyond the stop loss — setup invalidated.")
        elif (bull and price >= cand.targets[0]) or (not bull and price <= cand.targets[0]):
            cand.rejections.append("Price already reached TP1 — move missed.")
        else:
            dist = abs(price - cand.entry) / atr_h1 if atr_h1 else 0
            if dist > cfg.max_entry_distance_atr:
                cand.rejections.append(f"Price is {dist:.1f} ATR from entry — too far to chase.")

    # Market conditions
    mc = 0.4 if ctx.get("data_fresh") else 0.0
    vr = ctx.get("volatility_ratio")
    if vr is not None and 0.5 <= vr <= 2.5:
        mc += 0.3
    if pd_aligned:
        mc += 0.3
    qualities["market_conditions"] = mc
    notes["market_conditions"] = (f"data {'fresh' if ctx.get('data_fresh') else 'stale'}; volatility ratio "
                                  f"{vr:.2f}" if vr is not None else "volatility n/a") + f"; price in {pd_zone or 'n/a'}"
    return _finish(cand, cfg, order_flow, qualities, digits, notes)


def _finish(cand, cfg, order_flow, qualities, digits, notes=None):
    if "order_flow" not in qualities:
        status, q, note = order_flow_quality(order_flow, cand.direction, cfg)
        cand.order_flow_status, qualities["order_flow"] = status, q
        cand.order_flow_details = {"available": bool(order_flow and order_flow.available), "note": note}
    cand.score, cand.breakdown = score(qualities, cfg.weights, notes)
    cand.classification = classify(cand.score, cfg.a_plus_threshold)
    cand.qualifies = not cand.rejections and cand.score >= cfg.a_plus_threshold and cand.entry is not None
    if cand.entry is not None:
        cand.explanation = _explain(cand, digits)
        cand.invalidation = _invalidation(cand, cfg, digits)
    return cand


def _explain(c, digits):
    s = c.crt
    bull = c.direction == "BUY"
    parts = [
        f"The {s.ref_time:%H:%M} UTC 1H candle formed a CRT range of {_fmt(s.ref_low, digits)} – "
        f"{_fmt(s.ref_high, digits)} (mid {_fmt(s.ref_mid, digits)}).",
        f"The following hour swept {'sell-side liquidity below the low' if bull else 'buy-side liquidity above the high'} "
        f"to {_fmt(s.sweep_price, digits)} and closed back inside the range at {_fmt(s.reclaim_close, digits)}"
        + (" (provisional — candle not yet closed)." if c.provisional else "."),
    ]
    if c.mss:
        parts.append(f"On the lower timeframe price then {'broke above' if bull else 'broke below'} the swing at "
                     f"{_fmt(c.mss.level, digits)} ({c.mss.kind}{', with displacement' if c.mss.displacement else ''}).")
    if c.poi:
        parts.append(f"Entry is the {c.poi['type']} left by that move, {_fmt(c.entry_low, digits)} – "
                     f"{_fmt(c.entry_high, digits)}, with the stop beyond the sweep extreme at {_fmt(c.stop, digits)}.")
    if c.targets:
        parts.append("Targets: " + ", ".join(f"TP{i + 1} {_fmt(t, digits)}" for i, t in enumerate(c.targets))
                     + f" (1:{c.rr_final:.2f} to final target)." if c.rr_final else "")
    parts.append(f"Order flow: {c.order_flow_status.replace('_', ' ')}.")
    parts.append(f"Confluence score {c.score}/100 ({c.classification}). This is a rule-based score, not a probability "
                 "of success.")
    return " ".join(p for p in parts if p)


def _invalidation(c, cfg, digits):
    bull = c.direction == "BUY"
    lines = [
        f"Invalid if price trades {'below' if bull else 'above'} {_fmt(c.stop, digits)} before entry.",
        f"Invalid if price reaches TP1 {_fmt(c.targets[0], digits)} before filling the entry zone (move missed)."
        if c.targets else "",
        "Expires if the entry zone is not reached before the signal expiry time.",
        f"A 1H close {'below' if bull else 'above'} the sweep extreme {_fmt(c.crt.sweep_price, digits)} invalidates "
        "the CRT premise.",
    ]
    return "\n".join(line for line in lines if line)


def build_context(h1, ltf, cfg, data_fresh=True):
    atr_h1 = atr(h1, cfg.atr_period)
    swings = smc.find_swings(h1, cfg.swing_lookback_htf)
    htf_breaks, htf_trend = smc.detect_structure_breaks(h1, cfg.swing_lookback_htf, cfg)
    bias = smc.trend_from_swings(swings)
    if bias == "ranging" and htf_breaks:
        bias = htf_breaks[-1].direction
    rng = smc.dealing_range(swings)
    last_price = ltf[-1].close if ltf else (h1[-1].close if h1 else None)
    zone, pos = smc.premium_discount(last_price, rng) if last_price is not None else ("unknown", None)
    long_atr = atr(h1, min(50, len(h1)))
    liquidity = smc.liquidity_levels(h1, swings, atr_h1, cfg)
    return {
        "atr_h1": atr_h1,
        "htf_bias": bias,
        "htf_breaks": [b.as_dict() for b in htf_breaks[-3:]],
        "dealing_range": rng,
        "pd_zone": zone,
        "pd_position": round(pos, 3) if pos is not None else None,
        "volatility_ratio": (atr_h1 / long_atr) if long_atr else None,
        "data_fresh": data_fresh,
        "liquidity": [
            {"price": p.price, "side": p.side, "touches": p.touches, "swept": p.swept} for p in liquidity[-12:]
        ],
        "_liquidity": liquidity,
    }


def analyze(symbol, h1, ltf, cfg, *, price=None, order_flow=None, forming_h1=None, data_fresh=True, digits=2):
    """Analyze completed 1H candles plus completed LTF candles.

    Returns an AnalysisResult whose ``state`` is BUY/SELL (a qualifying A+
    confirmed setup), WAIT (a CRT setup exists but is not yet A+ / confirmed) or
    NO_TRADE.
    """
    notes = []
    if not data_fresh:
        return AnalysisResult(symbol, "NO_TRADE", "unknown", [], None,
                              "NO TRADE — market data is stale or missing.", ["Stale data: signals suppressed."])
    if len(h1) < max(30, cfg.atr_period + 2) or len(ltf) < 30:
        return AnalysisResult(symbol, "NO_TRADE", "unknown", [], None,
                              "NO TRADE — not enough candle history.", ["Insufficient history."])
    ctx = build_context(h1, ltf, cfg, data_fresh)
    public_ctx = {k: v for k, v in ctx.items() if not k.startswith("_")}
    results = crt_mod.find_crt_setups(h1, ctx["atr_h1"], cfg, forming=forming_h1)
    candidates = []
    for setup, reason, _ in results:
        if setup is None:
            notes.append(reason)
            continue
        candidates.append(_evaluate(symbol, setup, h1, ltf, price, order_flow, cfg, ctx, digits))
    for c in candidates:
        c.context = {k: v for k, v in c.context.items() if not k.startswith("_")}
    confirmed = sorted((c for c in candidates if c.qualifies and not c.provisional), key=lambda c: -c.score)
    if confirmed:
        best = confirmed[0]
        return AnalysisResult(symbol, best.direction, ctx["htf_bias"], candidates, best, best.summary(), notes, public_ctx)
    if candidates:
        best = max(candidates, key=lambda c: c.score)
        return AnalysisResult(symbol, "WAIT", ctx["htf_bias"], candidates, None,
                              f"WAIT — {best.summary()}", notes, public_ctx)
    return AnalysisResult(symbol, "NO_TRADE", ctx["htf_bias"], [], None,
                          "NO TRADE — no A+ setup currently available.", notes, public_ctx)
