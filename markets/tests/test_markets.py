import datetime

from django.test import SimpleTestCase

from markets.orderflow import compute_order_flow
from markets.services import is_stale, split_completed, validate_candles
from markets.types import Candle, OrderBook, Trade

T = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def c(i, o=100, h=101, lo=99, cl=100.5, tf="5m"):
    return Candle(T + datetime.timedelta(minutes=5 * i), o, h, lo, cl, 1, tf)


class ValidationTests(SimpleTestCase):
    def test_drops_invalid_and_detects_gaps(self):
        rows = [c(0), c(1), c(1), c(2, h=98), c(5)]
        clean, report = validate_candles(rows, "5m")
        self.assertEqual([x.open_time for x in clean], [c(0).open_time, c(1).open_time, c(5).open_time])
        self.assertEqual(report.dropped_invalid, 1)
        self.assertEqual(report.missing_candles, 3)

    def test_split_completed_and_stale(self):
        rows = [c(i) for i in range(10)]
        now = c(9).open_time + datetime.timedelta(minutes=2)
        done, forming = split_completed(rows, now)
        self.assertEqual(len(done), 9)
        self.assertEqual(forming.open_time, c(9).open_time)
        self.assertFalse(is_stale(done, "5m", now)[0])
        self.assertTrue(is_stale(done, "5m", now + datetime.timedelta(hours=1))[0])
        self.assertTrue(is_stale([], "5m", now)[0])


class OrderFlowTests(SimpleTestCase):
    def test_buy_pressure(self):
        trades = [Trade(T + datetime.timedelta(seconds=i), 100, 1.0, "buy" if i % 4 else "sell") for i in range(40)]
        book = OrderBook(bids=[(99.9, 10)], asks=[(100.1, 2)], time=T)
        snap = compute_order_flow(trades, book, "test")
        self.assertTrue(snap.available)
        self.assertGreater(snap.delta_ratio, 0)
        self.assertGreater(snap.book_imbalance, 0)

    def test_no_trades_unavailable(self):
        self.assertFalse(compute_order_flow([], None, "test").available)
