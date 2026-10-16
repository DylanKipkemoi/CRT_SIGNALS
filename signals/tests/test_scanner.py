import datetime
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from core.testing import make_signal
from markets.models import MarketInstrument
from markets.providers.base import MarketDataProvider, ProviderError
from markets.types import OrderFlowSnapshot, Quote
from signals.models import InstrumentAnalysis, MarketScanRun, Outcome, SignalStatus, TradingSignal
from signals.scanner import LOCK_KEY, run_scan
from signals.scenarios import aggregate, bullish_crt_scenario, continuation_5m
from signals.services import performance_stats
from signals.tracking import apply_candles


class FakeProvider(MarketDataProvider):
    key = "fake"
    name = "Fake test feed"
    volume_type = "exchange"
    supports_order_flow = True

    def __init__(self, scn, fail=False):
        super().__init__()
        self.scn, self.fail = scn, fail

    def fetch_candles(self, symbol, timeframe, limit):
        if self.fail:
            raise ProviderError("connection refused")
        return {"1h": self.scn["h1"], "5m": self.scn["m5"], "15m": aggregate(self.scn["m5"], "15m", 900)}[timeframe]

    def fetch_quote(self, symbol):
        return Quote(self.scn["price"], None, None, self.scn["now"])

    def fetch_order_flow(self, symbol):
        return OrderFlowSnapshot(True, "test", delta_ratio=0.4, cvd_slope=0.3, book_imbalance=0.2,
                                 large_trade_bias=0.2)


class ScannerTests(TestCase):
    def setUp(self):
        cache.clear()
        MarketInstrument.objects.filter(symbol="XAUUSD").update(is_enabled=False)
        self.scn = bullish_crt_scenario()

    def scan(self, provider=None, now=None):
        return run_scan(trigger=MarketScanRun.Trigger.COMMAND, now=now or self.scn["now"],
                        providers={"BTCUSD": provider or FakeProvider(self.scn)})

    def test_scan_creates_a_plus_signal_once(self):
        run = self.scan()
        self.assertEqual(run.status, MarketScanRun.Status.SUCCESS)
        self.assertEqual(run.signals_created, 1)
        sig = TradingSignal.objects.get()
        self.assertEqual((sig.direction, sig.status, sig.is_sample), ("BUY", SignalStatus.ACTIVE, False))
        self.assertGreaterEqual(sig.score, 80)
        self.assertLess(sig.stop_loss, sig.entry_low)
        self.assertEqual(sig.order_flow_status, "confirmed")
        self.assertTrue(sig.events.filter(event_type="created").exists())
        cache.clear()
        self.assertEqual(self.scan().signals_created, 0)
        self.assertEqual(TradingSignal.objects.count(), 1)
        self.assertEqual(InstrumentAnalysis.objects.get(instrument__symbol="BTCUSD").state, "BUY")

    def test_stale_data_produces_no_signal(self):
        run = self.scan(now=self.scn["now"] + datetime.timedelta(hours=3))
        self.assertEqual(run.signals_created, 0)
        self.assertEqual(InstrumentAnalysis.objects.get(instrument__symbol="BTCUSD").state, "NO_TRADE")
        self.assertTrue(MarketInstrument.objects.get(symbol="BTCUSD").data_status.is_stale)

    def test_missing_candles_mark_stale(self):
        scn = dict(self.scn)
        scn["m5"] = self.scn["m5"][:-6] + self.scn["m5"][-3:]
        run = self.scan(FakeProvider(scn))
        self.assertEqual(run.signals_created, 0)

    def test_provider_failure_is_safe(self):
        run = self.scan(FakeProvider(self.scn, fail=True))
        self.assertEqual(run.status, MarketScanRun.Status.FAILED)
        self.assertTrue(run.errors)
        status = MarketInstrument.objects.get(symbol="BTCUSD").data_status
        self.assertEqual(status.consecutive_failures, 1)

    def test_unconfigured_gold_feed_is_unavailable_not_fake(self):
        MarketInstrument.objects.filter(symbol="XAUUSD").update(is_enabled=True)
        with self.settings(MARKET_DATA={**__import__("django.conf").conf.settings.MARKET_DATA,
                                        "TWELVEDATA_API_KEY": "", "OANDA_API_TOKEN": ""}):
            run = self.scan()
        self.assertEqual(run.results["XAUUSD"]["state"], "UNAVAILABLE")
        self.assertFalse(TradingSignal.objects.filter(instrument__symbol="XAUUSD").exists())

    def test_concurrent_scan_skipped(self):
        cache.add(LOCK_KEY, "1", 60)
        self.assertEqual(self.scan().status, MarketScanRun.Status.SKIPPED)


class TrackingTests(TestCase):
    def setUp(self):
        self.scn = bullish_crt_scenario()
        self.now = self.scn["now"]
        self.sig = make_signal(created_at=self.now)

    def run_path(self, path, now=None):
        candles = continuation_5m(self.scn, path, start=self.now)
        apply_candles(self.sig, candles, now=now or candles[-1].close_time)
        self.sig.refresh_from_db()

    def test_full_target_run(self):
        self.run_path([(1002, 1003, 996, 997), (997, 998, 993, 994), (994, 1013, 993.5, 1012.5),
                       (1012.5, 1031, 1010, 1030.5), (1030.5, 1036, 1029, 1035.5)])
        self.assertEqual((self.sig.status, self.sig.outcome, self.sig.max_tp_hit), (SignalStatus.CLOSED, Outcome.TP3, 3))
        expected = sum(self.sig.r_multiple(t) for t in self.sig.targets) / 3
        self.assertEqual(self.sig.realized_r, expected.quantize(Decimal("0.01")))
        stats = performance_stats(include_sample=True)
        self.assertEqual((stats["wins"], stats["losses"]), (1, 0))

    def test_stop_loss(self):
        self.run_path([(1002, 1003, 993, 994), (994, 995, 983, 984)])
        self.assertEqual((self.sig.status, self.sig.outcome, self.sig.realized_r),
                         (SignalStatus.CLOSED, Outcome.STOP, Decimal("-1.00")))

    def test_breakeven_after_tp1(self):
        self.run_path([(1002, 1003, 993, 994), (994, 1013, 993.5, 1012), (1012, 1012, 993, 993.1)])
        self.assertEqual((self.sig.outcome, self.sig.max_tp_hit), (Outcome.TP1, 1))
        self.assertEqual(self.sig.realized_r, (self.sig.r_multiple(self.sig.take_profit_1) / 3).quantize(Decimal("0.01")))

    def test_missed_entry_invalidated(self):
        self.run_path([(1002, 1013, 1001, 1012)])
        self.assertEqual(self.sig.status, SignalStatus.INVALIDATED)

    def test_expiry(self):
        self.run_path([(1002, 1004, 1000, 1003)], now=self.sig.expires_at + datetime.timedelta(minutes=1))
        self.assertEqual(self.sig.status, SignalStatus.EXPIRED)

    def test_sell_direction(self):
        sig = make_signal(direction="SELL", created_at=self.now)
        candles = continuation_5m(self.scn, [(998, 1007, 997, 1006), (1006, 1006.5, 987, 988)], start=self.now)
        apply_candles(sig, candles, now=candles[-1].close_time)
        sig.refresh_from_db()
        self.assertEqual((sig.status, sig.max_tp_hit), (SignalStatus.TRIGGERED, 1))
