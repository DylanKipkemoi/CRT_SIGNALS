"""Deterministic synthetic candle scenarios.

Used by the test-suite and by ``generate_sample_data`` (offline demo data).
These are constructed price paths, NOT market data.
"""

import datetime
import math

from markets.types import Candle

T0 = datetime.datetime(2026, 1, 5, tzinfo=datetime.UTC)
H = datetime.timedelta(hours=1)
M5 = datetime.timedelta(minutes=5)

# 5m candles inside the bullish manipulation hour (open, high, low, close).
_BULL_MANIP_5M = [
    (1004, 1005, 1000, 1001),
    (1001, 1002, 996, 997),
    (997, 999, 993, 994),
    (994, 998, 992, 996),
    (996, 999.5, 995, 998),      # swing high later broken (MSS level)
    (998, 998.5, 990, 991),
    (991, 992, 985, 988),        # sweep extreme / order block
    (988, 994, 987.5, 993.5),
    (994.5, 1003, 994.5, 1002.5),  # displacement candle breaks 999.5 -> MSS, leaves FVG 992-994.5
    (1002.5, 1006, 1000, 1005),
    (1005, 1005.5, 994, 997),    # retest into the FVG
    (997, 1003, 996, 1002),
]


def _walk(waypoints, start_time, step=4.0, wick=3.0):
    """Hourly candles that travel through ``waypoints``."""
    candles = []
    t = start_time
    price = waypoints[0]
    for target in waypoints[1:]:
        n = max(1, int(abs(target - price) // step))
        for k in range(n):
            o = price
            c = price + (target - price) / (n - k)
            hi, lo = max(o, c) + wick, min(o, c) - wick
            if k == n - 1:  # turning candle gets a distinct extreme so it forms a clean swing pivot
                hi, lo = (hi + 2, lo) if target > o else (hi, lo - 2)
            candles.append(Candle(t, round(o, 2), round(hi, 2), round(lo, 2), round(c, 2), 100.0, "1h"))
            price = c
            t += H
    return candles, price, t


def _mirror(candles, pivot):
    out = []
    for c in candles:
        out.append(Candle(c.open_time, 2 * pivot - c.open, 2 * pivot - c.low, 2 * pivot - c.high, 2 * pivot - c.close,
                          c.volume, c.timeframe))
    return out


def bullish_crt_scenario(start=T0):
    """Return dict(h1, m5, now, price) containing a complete A+ bullish CRT setup.

    * Reference 1H candle: H 1012 / L 990 (mid 1001).
    * Manipulation candle sweeps to 985 and closes back inside at 1002.
    * 5m: MSS through 999.5 with displacement, FVG 992–994.5 overlapping a bearish OB, retest.
    * Unswept buy-side liquidity at ~1025/1030 provides targets.
    """
    history, price, t = _walk([1000, 1030, 980, 1025, 985, 1000], start)
    h1 = list(history)
    ref = Candle(t, 1000, 1012, 990, 1005, 120.0, "1h")
    h1.append(ref)
    manip_time = t + H
    m5_manip = []
    for k, (o, hi, lo, c) in enumerate(_BULL_MANIP_5M):
        m5_manip.append(Candle(manip_time + k * M5, o, hi, lo, c, 10.0, "5m"))
    manip = Candle(manip_time, 1004, max(c.high for c in m5_manip), min(c.low for c in m5_manip), m5_manip[-1].close,
                   150.0, "1h")
    h1.append(manip)
    m5_hist = []
    for k in range(36):
        tt = manip_time - (36 - k) * M5
        mid = 1004 + 4 * math.sin(k / 3)
        o = mid - 1
        c = mid + (1 if k % 2 else -1.5)
        m5_hist.append(Candle(tt, round(o, 2), round(max(o, c) + 1.5, 2), round(min(o, c) - 1.5, 2), round(c, 2),
                              8.0, "5m"))
    m5 = m5_hist + m5_manip
    now = manip_time + H
    return {"h1": h1, "m5": m5, "now": now, "price": m5[-1].close, "manip_time": manip_time}


def bearish_crt_scenario(start=T0):
    """Mirror image of the bullish scenario around 1000 (prices 2000 - x)."""
    s = bullish_crt_scenario(start)
    pivot = 1000
    return {"h1": _mirror(s["h1"], pivot), "m5": _mirror(s["m5"], pivot), "now": s["now"],
            "price": 2 * pivot - s["price"], "manip_time": s["manip_time"]}


def continuation_5m(scn, path, start=None):
    """Append 5m candles following (o, h, l, c) tuples after the scenario's last candle."""
    t = start or scn["m5"][-1].open_time + M5
    return [Candle(t + k * M5, o, h, lo, c, 10.0, "5m") for k, (o, h, lo, c) in enumerate(path)]


def aggregate(candles, timeframe, seconds):
    """Aggregate lower-timeframe candles into ``timeframe`` buckets."""
    out = {}
    for c in candles:
        key = int(c.open_time.timestamp()) // seconds * seconds
        b = out.get(key)
        if b is None:
            out[key] = [c.open, c.high, c.low, c.close, c.volume]
        else:
            b[1] = max(b[1], c.high)
            b[2] = min(b[2], c.low)
            b[3] = c.close
            b[4] += c.volume
    return [Candle(datetime.datetime.fromtimestamp(k, tz=datetime.UTC), *v, timeframe) for k, v in sorted(out.items())]
