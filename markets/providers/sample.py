import csv
import datetime
from pathlib import Path

from ..types import TF_SECONDS, Candle
from .base import MarketDataProvider, ProviderError

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


class SampleProvider(MarketDataProvider):
    """Offline sample OHLCV from CSV files. NEVER live data.

    Timestamps are shifted so the newest sample candle is the most recently
    completed one, which lets the full pipeline be demonstrated offline. Every
    candle, status and signal produced from it is flagged as SAMPLE.
    """

    key = "sample"
    name = "Sample data (offline, not live)"
    volume_type = "exchange"
    is_live = False
    supports_order_flow = False
    min_request_interval = 0
    notes = "Synthetic sample candles for demos and tests. Not market data."

    def __init__(self, shift_to_now=True, now=None):
        super().__init__()
        self.shift_to_now = shift_to_now
        self.now = now

    def _load(self, symbol, timeframe):
        path = SAMPLE_DIR / f"{symbol}_{timeframe}.csv"
        if not path.exists():
            raise ProviderError(f"No sample file {path.name}")
        rows = []
        with path.open(newline="") as fh:
            for r in csv.DictReader(fh):
                rows.append(Candle(
                    datetime.datetime.fromisoformat(r["open_time"]), float(r["open"]), float(r["high"]),
                    float(r["low"]), float(r["close"]), float(r.get("volume") or 0), timeframe,
                ))
        return rows

    def _offset(self, symbol):
        """Shift that maps the sample's 5m end to the latest completed 1h boundary."""
        if not self.shift_to_now:
            return datetime.timedelta(0)
        base = self._load(symbol, "1h")
        last_close = base[-1].close_time
        now = self.now or datetime.datetime.now(datetime.UTC)
        epoch = int(now.timestamp())
        boundary = datetime.datetime.fromtimestamp(epoch - epoch % TF_SECONDS["1h"], tz=datetime.UTC)
        return boundary - last_close

    def fetch_candles(self, symbol, timeframe, limit):
        offset = self._offset(symbol)
        candles = [
            Candle(c.open_time + offset, c.open, c.high, c.low, c.close, c.volume, c.timeframe)
            for c in self._load(symbol, timeframe)
        ]
        return candles[-limit:]

    def fetch_quote(self, symbol):
        from ..types import Quote

        last = self.fetch_candles(symbol, "5m", 1)[-1]
        return Quote(last=last.close, bid=None, ask=None, time=last.close_time)
