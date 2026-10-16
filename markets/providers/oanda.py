import datetime

from ..types import Candle, Quote
from .base import MarketDataProvider, ProviderError, ProviderNotConfigured

GRANULARITY = {"5m": "M5", "15m": "M15", "1h": "H1", "4h": "H4"}


def _parse(value):
    head, _, frac = value.rstrip("Z").partition(".")
    return datetime.datetime.fromisoformat(head + (f".{frac[:6]}" if frac else "")).replace(tzinfo=datetime.UTC)


class OandaProvider(MarketDataProvider):
    """OANDA v20 REST (broker OTC quotes, e.g. XAU_USD). Volume is tick volume."""

    key = "oanda"
    name = "OANDA v20"
    volume_type = "tick"
    supports_order_flow = False
    min_request_interval = 0.1
    notes = "Broker OTC gold quotes; volume is tick count, not centralized traded volume. No order book/delta."

    @property
    def base_url(self):
        env = self.config["OANDA_ENVIRONMENT"]
        return "https://api-fxtrade.oanda.com" if env == "live" else "https://api-fxpractice.oanda.com"

    def check_configured(self):
        if not self.config["OANDA_API_TOKEN"]:
            raise ProviderNotConfigured("Set OANDA_API_TOKEN (and OANDA_ACCOUNT_ID for live bid/ask) in .env.")

    def _headers(self):
        return {"Authorization": f"Bearer {self.config['OANDA_API_TOKEN']}", "Accept-Datetime-Format": "RFC3339"}

    def fetch_candles(self, symbol, timeframe, limit):
        self.check_configured()
        data = self.get_json(f"/v3/instruments/{symbol}/candles", params={
            "granularity": GRANULARITY[timeframe], "count": min(limit, 5000), "price": "M",
        }, headers=self._headers())
        out = []
        for c in data.get("candles", []):
            mid = c.get("mid")
            if not mid:
                continue
            out.append(Candle(_parse(c["time"]), float(mid["o"]), float(mid["h"]), float(mid["l"]), float(mid["c"]),
                              float(c.get("volume", 0)), timeframe))
        return out

    def fetch_quote(self, symbol):
        self.check_configured()
        account = self.config["OANDA_ACCOUNT_ID"]
        if not account:
            return None
        data = self.get_json(f"/v3/accounts/{account}/pricing", params={"instruments": symbol}, headers=self._headers())
        prices = data.get("prices") or []
        if not prices:
            raise ProviderError(f"{self.name}: no pricing returned")
        p = prices[0]
        bid = float(p["bids"][0]["price"]) if p.get("bids") else None
        ask = float(p["asks"][0]["price"]) if p.get("asks") else None
        last = (bid + ask) / 2 if bid and ask else None
        return Quote(last=last, bid=bid, ask=ask, time=_parse(p["time"]))
