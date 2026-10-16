"""Order-flow metrics computed from genuine exchange trades and order books."""

import datetime

from .types import OrderBook, OrderFlowSnapshot, Trade


def compute_order_flow(trades: list[Trade], book: OrderBook | None, source: str, depth_pct: float = 0.0025):
    if not trades:
        return OrderFlowSnapshot(available=False, source=source, reason="No recent trades returned by provider.")
    trades = sorted(trades, key=lambda t: t.time)
    buy = sum(t.size for t in trades if t.taker_side == "buy")
    sell = sum(t.size for t in trades if t.taker_side == "sell")
    total = buy + sell
    delta = buy - sell
    window = int((trades[-1].time - trades[0].time).total_seconds())

    half = trades[0].time + datetime.timedelta(seconds=window / 2)
    second = [t for t in trades if t.time >= half]
    second_total = sum(t.size for t in second)
    second_delta = sum(t.size if t.taker_side == "buy" else -t.size for t in second)
    cvd_slope = second_delta / second_total if second_total else 0.0

    sizes = sorted(t.size for t in trades)
    threshold = sizes[int(len(sizes) * 0.9)] if len(sizes) >= 10 else float("inf")
    large = [t for t in trades if t.size >= threshold]
    large_total = sum(t.size for t in large)
    large_bias = (sum(t.size if t.taker_side == "buy" else -t.size for t in large) / large_total) if large_total else 0.0

    imbalance = None
    notes = []
    if book and book.bids and book.asks:
        mid = (book.bids[0][0] + book.asks[0][0]) / 2
        lo, hi = mid * (1 - depth_pct), mid * (1 + depth_pct)
        bid_vol = sum(size for price, size in book.bids if price >= lo)
        ask_vol = sum(size for price, size in book.asks if price <= hi)
        if bid_vol + ask_vol > 0:
            imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
    else:
        notes.append("Order book unavailable; imbalance not computed.")

    prices = [t.price for t in trades]
    price_change = (prices[-1] - prices[0]) / prices[0] if prices[0] else 0.0
    absorption = ""
    delta_ratio = delta / total if total else 0.0
    # Absorption proxy: strong one-sided aggression that fails to move price.
    if abs(delta_ratio) > 0.3 and abs(price_change) < 0.0005:
        absorption = "buying absorbed" if delta_ratio > 0 else "selling absorbed"

    return OrderFlowSnapshot(
        available=True,
        source=source,
        window_seconds=window,
        trade_count=len(trades),
        buy_volume=buy,
        sell_volume=sell,
        delta=delta,
        delta_ratio=delta_ratio,
        cvd_slope=cvd_slope,
        large_trade_bias=large_bias,
        book_imbalance=imbalance,
        absorption=absorption,
        notes=notes,
    )
