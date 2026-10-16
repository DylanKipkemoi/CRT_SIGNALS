from ..orderflow import compute_order_flow
from ..types import Candle, OrderBook, Quote, Trade
from .base import MarketDataProvider, ProviderError

INTERVAL = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}


class KrakenProvider(MarketDataProvider):
    """Kraken public market data (XBT/USD spot)."""

    key = "kraken"
    name = "Kraken"
    base_url = "https://api.kraken.com/0/public"
    volume_type = "exchange"
    supports_order_flow = True
    min_request_interval = 1.0
    notes = "Spot XBT/USD on Kraken; prices differ slightly from other venues."

    def _result(self, path, params):
        data = self.get_json(path, params=params)
        if data.get("error"):
            raise ProviderError(f"{self.name}: {', '.join(data['error'])}")
        result = data.get("result") or {}
        for key, value in result.items():
            if key != "last":
                return value
        raise ProviderError(f"{self.name}: empty result")

    def fetch_candles(self, symbol, timeframe, limit):
        rows = self._result("/OHLC", {"pair": symbol, "interval": INTERVAL[timeframe]})
        # Row: [time, open, high, low, close, vwap, volume, count], oldest first.
        candles = [
            Candle(self.ts(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6]), timeframe)
            for r in rows
        ]
        return candles[-limit:]

    def fetch_quote(self, symbol):
        t = self._result("/Ticker", {"pair": symbol})
        last, opening = float(t["c"][0]), float(t["o"])
        return Quote(
            last=last, bid=float(t["b"][0]), ask=float(t["a"][0]), time=None,
            change_24h_pct=(last - opening) / opening * 100 if opening else None,
        )

    def fetch_order_flow(self, symbol):
        rows = self._result("/Trades", {"pair": symbol, "count": 1000})
        # Row: [price, volume, time, side(b/s = taker side), type, misc, id]
        trades = [Trade(self.ts(r[2]), float(r[0]), float(r[1]), "buy" if r[3] == "b" else "sell") for r in rows]
        depth = self._result("/Depth", {"pair": symbol, "count": 100})
        book = OrderBook(
            bids=[(float(p), float(v)) for p, v, *_ in depth.get("bids", [])],
            asks=[(float(p), float(v)) for p, v, *_ in depth.get("asks", [])],
        )
        return compute_order_flow(trades, book, source=f"{self.name} trades + depth")
