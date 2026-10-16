import datetime
import time

import requests
from django.conf import settings
from django.core.cache import cache

from ..types import TF_SECONDS, Candle


class ProviderError(Exception):
    """Transient or permanent failure talking to a provider."""


class ProviderNotConfigured(ProviderError):
    """Provider credentials are missing; the feed cannot be activated."""


def aggregate(candles, target_tf):
    """Aggregate lower-timeframe candles (sorted ascending) into ``target_tf`` buckets.

    Only complete buckets (all constituent candles present) are returned, plus a
    final forming bucket.
    """
    seconds = TF_SECONDS[target_tf]
    if not candles:
        return []
    per_bucket = seconds // candles[0].seconds
    buckets = {}
    for c in candles:
        epoch = int(c.open_time.timestamp())
        start = epoch - epoch % seconds
        buckets.setdefault(start, []).append(c)
    out = []
    keys = sorted(buckets)
    for i, start in enumerate(keys):
        group = buckets[start]
        if len(group) != per_bucket and i != len(keys) - 1:
            continue
        out.append(Candle(
            open_time=datetime.datetime.fromtimestamp(start, tz=datetime.UTC),
            open=group[0].open, high=max(c.high for c in group), low=min(c.low for c in group),
            close=group[-1].close, volume=sum(c.volume for c in group), timeframe=target_tf,
        ))
    return out


class MarketDataProvider:
    key = "base"
    name = "Base provider"
    base_url = ""
    volume_type = "none"
    is_live = True
    supports_order_flow = False
    min_request_interval = None  # seconds; defaults to settings.MARKET_DATA["MIN_REQUEST_INTERVAL"]
    notes = ""

    def __init__(self):
        self.config = settings.MARKET_DATA
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "crt-signals/1.0"

    # -- interface -----------------------------------------------------------
    def check_configured(self):
        """Raise ProviderNotConfigured when credentials are missing."""

    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        raise NotImplementedError

    def fetch_quote(self, symbol: str):
        return None

    def fetch_order_flow(self, symbol: str):
        return None

    # -- helpers -------------------------------------------------------------
    def _throttle(self):
        interval = self.min_request_interval
        if interval is None:
            interval = self.config["MIN_REQUEST_INTERVAL"]
        key = f"md:last-request:{self.key}"
        last = cache.get(key)
        now = time.monotonic()
        if last is not None and 0 <= now - last < interval:
            time.sleep(interval - (now - last))
        cache.set(key, time.monotonic(), 3600)

    def get_json(self, path, params=None, headers=None):
        self._throttle()
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=self.config["HTTP_TIMEOUT"])
        except requests.RequestException as exc:
            raise ProviderError(f"{self.name}: network error: {exc.__class__.__name__}") from exc
        if resp.status_code == 429:
            raise ProviderError(f"{self.name}: rate limited (HTTP 429)")
        if resp.status_code >= 400:
            raise ProviderError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError(f"{self.name}: invalid JSON response") from exc

    @staticmethod
    def ts(epoch):
        return datetime.datetime.fromtimestamp(float(epoch), tz=datetime.UTC)
