"""Plain data types shared by market-data providers and the signal engine."""

import datetime
from dataclasses import dataclass, field

TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


@dataclass(frozen=True, slots=True)
class Candle:
    open_time: datetime.datetime  # timezone-aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    timeframe: str = "1h"

    @property
    def seconds(self):
        return TF_SECONDS[self.timeframe]

    @property
    def close_time(self):
        return self.open_time + datetime.timedelta(seconds=self.seconds)

    @property
    def body(self):
        return abs(self.close - self.open)

    @property
    def range(self):
        return self.high - self.low

    @property
    def upper_wick(self):
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self):
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self):
        return self.close > self.open

    @property
    def is_bearish(self):
        return self.close < self.open

    @property
    def mid(self):
        return (self.high + self.low) / 2

    def body_ratio(self):
        return self.body / self.range if self.range > 0 else 0.0


@dataclass(slots=True)
class Quote:
    last: float | None
    bid: float | None
    ask: float | None
    time: datetime.datetime | None
    change_24h_pct: float | None = None


@dataclass(slots=True)
class Trade:
    time: datetime.datetime
    price: float
    size: float
    taker_side: str  # "buy" (aggressive buyer) or "sell" (aggressive seller)


@dataclass(slots=True)
class OrderBook:
    bids: list  # [(price, size)] best first
    asks: list
    time: datetime.datetime | None = None


@dataclass(slots=True)
class OrderFlowSnapshot:
    available: bool
    source: str = ""
    reason: str = ""
    window_seconds: int = 0
    trade_count: int = 0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    delta: float = 0.0
    delta_ratio: float = 0.0  # delta / total volume, -1..1
    cvd_slope: float = 0.0  # change in CVD over the second half of the window, normalised -1..1
    large_trade_bias: float = 0.0  # -1..1
    book_imbalance: float | None = None  # (bid - ask) / (bid + ask) near mid, -1..1
    absorption: str = ""
    notes: list = field(default_factory=list)

    def as_dict(self):
        return {
            "available": self.available,
            "source": self.source,
            "reason": self.reason,
            "window_seconds": self.window_seconds,
            "trade_count": self.trade_count,
            "buy_volume": round(self.buy_volume, 6),
            "sell_volume": round(self.sell_volume, 6),
            "delta": round(self.delta, 6),
            "delta_ratio": round(self.delta_ratio, 4),
            "cvd_slope": round(self.cvd_slope, 4),
            "large_trade_bias": round(self.large_trade_bias, 4),
            "book_imbalance": None if self.book_imbalance is None else round(self.book_imbalance, 4),
            "absorption": self.absorption,
            "notes": self.notes,
        }
