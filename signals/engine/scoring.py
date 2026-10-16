"""Transparent rule-based confluence scoring (0-100).

Each factor yields a quality in [0, 1] that is multiplied by its configured
weight. The total is a confluence score, NOT a probability of success.
"""

FACTOR_LABELS = {
    "crt_alignment": "1H CRT alignment",
    "liquidity_sweep": "Liquidity sweep quality",
    "structure_shift": "Market structure shift",
    "displacement": "Displacement strength",
    "entry_confluence": "FVG / order-block confluence",
    "price_action": "Price-action confirmation",
    "order_flow": "Order-flow confirmation",
    "risk_reward": "Risk:reward & invalidation distance",
    "market_conditions": "Market conditions & data freshness",
}


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def score(qualities, weights, notes=None):
    breakdown = {}
    total = 0.0
    for factor, weight in weights.items():
        q = clamp(qualities.get(factor, 0.0))
        pts = q * weight
        total += pts
        breakdown[factor] = {
            "label": FACTOR_LABELS.get(factor, factor),
            "weight": weight,
            "quality": round(q, 3),
            "points": round(pts, 1),
            "note": (notes or {}).get(factor, ""),
        }
    return int(round(total)), breakdown


def classify(total, threshold):
    if total >= threshold:
        return "A+"
    if total >= threshold - 10:
        return "A"
    if total >= threshold - 25:
        return "B"
    return "C"


def order_flow_quality(snapshot, direction, cfg):
    """Return (status, quality, note)."""
    if snapshot is None or not snapshot.available:
        reason = getattr(snapshot, "reason", "") or "Provider does not supply genuine order-flow data."
        credit = cfg.order_flow_unavailable_credit
        weight = cfg.weights.get("order_flow", 0) or 1
        return "unavailable", credit / weight, f"Order-flow confirmation unavailable: {reason}"
    sign = 1 if direction == "BUY" else -1
    d = snapshot.delta_ratio * sign
    cvd = snapshot.cvd_slope * sign
    book = (snapshot.book_imbalance or 0.0) * sign
    large = snapshot.large_trade_bias * sign
    composite = 0.4 * d + 0.25 * cvd + 0.2 * book + 0.15 * large
    note = (f"delta {snapshot.delta_ratio:+.2f}, CVD slope {snapshot.cvd_slope:+.2f}, "
            f"book imbalance {snapshot.book_imbalance if snapshot.book_imbalance is not None else 'n/a'}, "
            f"large-trade bias {snapshot.large_trade_bias:+.2f}")
    if snapshot.absorption:
        note += f"; {snapshot.absorption}"
    if composite >= 0.1:
        return "confirmed", clamp(0.7 + composite), note
    if composite <= -0.1:
        return "opposing", 0.0, note
    return "neutral", 0.5, note
