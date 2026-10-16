import datetime

from ..orderflow import compute_order_flow
from ..types import Candle, OrderBook, Quote, Trade
from .base import MarketDataProvider, ProviderError, aggregate

GRANULARITY = {"5m": 300, "15m": 900, "1h": 3600}


class CoinbaseProvider(MarketDataProvider):
    """Coinbase Exchange public market data (BTC-USD spot)."""

    key = "coinbase"
    name = "Coinbase Exchange"
    base_url = "https://api.exchange.coinbase.com"
    volume_type = "exchange"
    supports_order_flow = True
    min_request_interval = 0.15
    notes = "Spot BTC-USD on a single exchange; prices differ slightly from other venues."

    def fetch_candles(self, symbol, timeframe, limit):
        if timeframe == "4h":
            hourly = self.fetch_candles(symbol, "1h", min(limit * 4, 300))
            return aggregate(hourly, "4h")[-limit:]
        gran = GRANULARITY[timeframe]
        limit = min(limit, 300)
        end = datetime.datetime.now(datetime.UTC)
        start = end - datetime.timedelta(seconds=gran * limit)
        rows = self.get_json(f"/products/{symbol}/candles", params={
            "granularity": gran, "start": start.isoformat(), "end": end.isoformat(),
        })
        if not isinstance(rows, list):
            raise ProviderError(f"{self.name}: unexpected candle payload")
        # Row format: [time, low, high, open, close, volume], newest first.
        candles = [
            Candle(self.ts(r[0]), float(r[3]), float(r[2]), float(r[1]), float(r[4]), float(r[5]), timeframe)
            for r in rows
        ]
        return sorted(candles, key=lambda c: c.open_time)

    def fetch_quote(self, symbol):
        t = self.get_json(f"/products/{symbol}/ticker")
        change = None
        try:
            stats = self.get_json(f"/products/{symbol}/stats")
            if float(stats.get("open") or 0):
                change = (float(stats["last"]) - float(stats["open"])) / float(stats["open"]) * 100
        except ProviderError:
            pass
        return Quote(
            last=float(t["price"]), bid=float(t["bid"]), ask=float(t["ask"]),
            time=_parse_time(t["time"]),
            change_24h_pct=change,
        )

    def fetch_order_flow(self, symbol):
        rows = self.get_json(f"/products/{symbol}/trades", params={"limit": 1000})
        trades = []
        for r in rows:
            # Coinbase "side" is the maker order side; the aggressor is the opposite.
            taker = "sell" if r["side"] == "buy" else "buy"
            trades.append(Trade(_parse_time(r["time"]), float(r["price"]), float(r["size"]), taker))
        book_raw = self.get_json(f"/products/{symbol}/book", params={"level": 2})
        book = OrderBook(
            bids=[(float(p), float(s)) for p, s, *_ in book_raw.get("bids", [])],
            asks=[(float(p), float(s)) for p, s, *_ in book_raw.get("asks", [])],
        )
        return compute_order_flow(trades, book, source=f"{self.name} trades + L2 book")


def _parse_time(value):
    value = value.replace("Z", "")
    if "." in value:
        head, frac = value.split(".")
        value = f"{head}.{frac[:6]}"
    return datetime.datetime.fromisoformat(value).replace(tzinfo=datetime.UTC)
