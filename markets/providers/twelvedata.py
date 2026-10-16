import datetime

from ..types import Candle, Quote
from .base import MarketDataProvider, ProviderError, ProviderNotConfigured

INTERVAL = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}


class TwelveDataProvider(MarketDataProvider):
    """Twelve Data REST (aggregated FX/metal quotes, e.g. XAU/USD)."""

    key = "twelvedata"
    name = "Twelve Data"
    base_url = "https://api.twelvedata.com"
    volume_type = "none"
    supports_order_flow = False
    min_request_interval = 8.0  # free plan: 8 requests/minute
    notes = "Aggregated OTC gold quotes; no genuine volume, order book or delta for spot gold."

    def check_configured(self):
        if not self.config["TWELVEDATA_API_KEY"]:
            raise ProviderNotConfigured("Set TWELVEDATA_API_KEY in .env to activate the XAUUSD feed.")

    def _get(self, path, params):
        self.check_configured()
        data = self.get_json(path, params={**params, "apikey": self.config["TWELVEDATA_API_KEY"]})
        if isinstance(data, dict) and data.get("status") == "error":
            raise ProviderError(f"{self.name}: {data.get('message', 'error')}")
        return data

    def fetch_candles(self, symbol, timeframe, limit):
        data = self._get("/time_series", {
            "symbol": symbol, "interval": INTERVAL[timeframe], "outputsize": min(limit, 5000), "timezone": "UTC",
        })
        out = []
        for v in data.get("values", []):
            out.append(Candle(
                datetime.datetime.fromisoformat(v["datetime"]).replace(tzinfo=datetime.UTC),
                float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"]),
                float(v.get("volume") or 0), timeframe,
            ))
        return sorted(out, key=lambda c: c.open_time)

    def fetch_quote(self, symbol):
        q = self._get("/quote", {"symbol": symbol, "timezone": "UTC"})
        last = float(q["close"]) if q.get("close") else None
        ts = q.get("last_quote_at") or q.get("timestamp")
        return Quote(
            last=last, bid=None, ask=None,
            time=datetime.datetime.fromtimestamp(int(ts), tz=datetime.UTC) if ts else None,
            change_24h_pct=float(q["percent_change"]) if q.get("percent_change") else None,
        )
