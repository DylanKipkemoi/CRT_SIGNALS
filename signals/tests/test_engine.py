import datetime

from django.test import SimpleTestCase

from markets.types import Candle, OrderFlowSnapshot
from signals.engine import EngineConfig, analyze
from signals.engine import crt, smc
from signals.engine.risk import InvalidLevels, risk_reward, validate_levels
from signals.engine.scoring import classify, score
from signals.scenarios import bearish_crt_scenario, bullish_crt_scenario
from core.models import DEFAULT_SCORE_WEIGHTS

T = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
BULL_FLOW = OrderFlowSnapshot(True, "test", delta_ratio=0.4, cvd_slope=0.3, book_imbalance=0.2, large_trade_bias=0.2)
BEAR_FLOW = OrderFlowSnapshot(True, "test", delta_ratio=-0.4, cvd_slope=-0.3, book_imbalance=-0.2,
                              large_trade_bias=-0.2)


def bars(rows, tf="1h", step=3600):
    return [Candle(T + datetime.timedelta(seconds=i * step), o, h, lo, c, 1.0, tf) for i, (o, h, lo, c) in enumerate(rows)]


class CRTRuleTests(SimpleTestCase):
    cfg = EngineConfig()
    ref = Candle(T, 100, 110, 90, 105, 1, "1h")

    def manip(self, o, h, lo, c):
        return Candle(T + datetime.timedelta(hours=1), o, h, lo, c, 1, "1h")

    def test_bullish_sweep_and_reclaim(self):
        setup, _ = crt.evaluate_pair(self.ref, self.manip(104, 106, 86, 98), 10, self.cfg)
        self.assertEqual(setup.direction, "bullish")
        self.assertEqual(setup.ref_mid, 100)
        self.assertAlmostEqual(setup.sweep_frac, 0.2)

    def test_bearish_sweep_and_reject(self):
        setup, _ = crt.evaluate_pair(self.ref, self.manip(104, 114, 95, 101), 10, self.cfg)
        self.assertEqual(setup.direction, "bearish")

    def test_sweep_without_reclaim_is_not_a_setup(self):
        setup, reason = crt.evaluate_pair(self.ref, self.manip(95, 96, 85, 88), 10, self.cfg)
        self.assertIsNone(setup)
        self.assertIn("not reclaimed", reason)

    def test_two_sided_sweep_rejected(self):
        self.assertIsNone(crt.evaluate_pair(self.ref, self.manip(100, 112, 88, 101), 10, self.cfg)[0])

    def test_too_deep_and_too_shallow(self):
        self.assertIsNone(crt.evaluate_pair(self.ref, self.manip(100, 105, 70, 95), 10, self.cfg)[0])
        self.assertIsNone(crt.evaluate_pair(self.ref, self.manip(100, 105, 89.9, 95), 10, self.cfg)[0])

    def test_no_sweep(self):
        setup, reason = crt.evaluate_pair(self.ref, self.manip(100, 108, 92, 101), 10, self.cfg)
        self.assertIsNone(setup)
        self.assertIn("No sweep", reason)


class SMCTests(SimpleTestCase):
    cfg = EngineConfig()
    series = bars([(10, 11, 9, 10.5), (10.5, 12, 10, 11.5), (11.5, 11.8, 10.5, 11), (11, 11.2, 9.5, 9.8),
                   (9.8, 12.5, 9.7, 12.4), (12.4, 13, 12, 12.8), (12.8, 12.9, 12.2, 12.5),
                   (12.5, 13.6, 12.4, 13.5), (13.5, 13.6, 9, 9.2)])

    def test_swings(self):
        swings = smc.find_swings(self.series, 1)
        self.assertIn((1, "high", 12), [(s.index, s.kind, s.price) for s in swings])
        self.assertIn((3, "low", 9.5), [(s.index, s.kind, s.price) for s in swings])

    def test_bos_choch_sequence(self):
        events, trend = smc.detect_structure_breaks(self.series, 1, self.cfg)
        self.assertEqual([(e.index, e.direction, e.kind) for e in events],
                         [(4, "bullish", "CHOCH"), (7, "bullish", "BOS"), (8, "bearish", "CHOCH")])
        self.assertEqual(trend, "bearish")

    def test_mss_requires_displacement(self):
        events, _ = smc.detect_structure_breaks(self.series, 1, self.cfg)
        for e in events:
            self.assertEqual(e.is_mss, e.kind == "CHOCH" and e.displacement)

    def test_fvg_detection_and_fill(self):
        rows = [(10, 11, 9, 10.8), (10.8, 14, 10.7, 13.8), (13.8, 15, 12, 14.5), (14.5, 14.6, 11.5, 12)]
        gaps = smc.find_fvgs(bars(rows), self.cfg)
        self.assertEqual((gaps[0].direction, gaps[0].bottom, gaps[0].top), ("bullish", 11, 12))
        self.assertTrue(gaps[0].mitigated)
        self.assertFalse(gaps[0].filled)
        filled = smc.find_fvgs(bars(rows + [(12, 12.2, 10.9, 11)]), self.cfg)
        self.assertTrue(filled[0].filled)

    def test_bearish_fvg(self):
        rows = [(15, 16, 14, 14.2), (14.2, 14.3, 11, 11.2), (11.2, 13, 10, 10.5)]
        gaps = smc.find_fvgs(bars(rows), self.cfg)
        self.assertEqual((gaps[0].direction, gaps[0].bottom, gaps[0].top), ("bearish", 13, 14))

    def test_order_block_is_last_opposite_candle(self):
        events, _ = smc.detect_structure_breaks(self.series, 1, self.cfg)
        ob = smc.find_order_block(self.series, events[0])
        self.assertEqual((ob.index, ob.low, ob.high), (3, 9.5, 11.2))

    def test_premium_discount(self):
        rng = {"high": 110, "low": 90, "equilibrium": 100}
        self.assertEqual(smc.premium_discount(95, rng)[0], "discount")
        self.assertEqual(smc.premium_discount(105, rng)[0], "premium")


class RiskAndScoringTests(SimpleTestCase):
    def test_risk_reward_buy_and_sell(self):
        self.assertAlmostEqual(risk_reward("BUY", 100, 95, 110), 2.0)
        self.assertAlmostEqual(risk_reward("SELL", 100, 105, 85), 3.0)

    def test_invalid_levels(self):
        with self.assertRaises(InvalidLevels):
            validate_levels("BUY", 99, 101, 102, [110])
        with self.assertRaises(InvalidLevels):
            validate_levels("SELL", 99, 101, 98, [90])
        with self.assertRaises(InvalidLevels):
            validate_levels("BUY", 99, 101, 95, [100])
        validate_levels("SELL", 99, 101, 103, [95, 90])

    def test_score_is_out_of_100(self):
        self.assertEqual(sum(DEFAULT_SCORE_WEIGHTS.values()), 100)
        total, breakdown = score({k: 1.0 for k in DEFAULT_SCORE_WEIGHTS}, DEFAULT_SCORE_WEIGHTS)
        self.assertEqual(total, 100)
        total, _ = score({k: 5.0 for k in DEFAULT_SCORE_WEIGHTS}, DEFAULT_SCORE_WEIGHTS)
        self.assertEqual(total, 100)
        self.assertEqual(classify(80, 80), "A+")
        self.assertNotEqual(classify(79, 80), "A+")


class AnalyzeTests(SimpleTestCase):
    def run_bull(self, cfg=None, **kw):
        s = bullish_crt_scenario()
        kw.setdefault("price", s["price"])
        kw.setdefault("order_flow", BULL_FLOW)
        return analyze("BTCUSD", s["h1"], kw.pop("ltf", s["m5"]), cfg or EngineConfig(), **kw)

    def test_bullish_a_plus(self):
        r = self.run_bull()
        self.assertEqual(r.state, "BUY")
        c = r.best
        self.assertGreaterEqual(c.score, 80)
        self.assertEqual(c.classification, "A+")
        self.assertLess(c.stop, c.entry_low)
        self.assertTrue(all(t > c.entry_high for t in c.targets))
        self.assertEqual(c.targets, sorted(c.targets))
        self.assertGreaterEqual(c.rr_final, 2.0)
        self.assertEqual(c.poi["type"], "FVG + OB")
        self.assertEqual(c.order_flow_status, "confirmed")
        self.assertIn("structure_shift", c.breakdown)
        self.assertEqual(sum(f["weight"] for f in c.breakdown.values()), 100)

    def test_bearish_a_plus(self):
        s = bearish_crt_scenario()
        r = analyze("XAUUSD", s["h1"], s["m5"], EngineConfig(), price=s["price"], order_flow=BEAR_FLOW)
        self.assertEqual(r.state, "SELL")
        c = r.best
        self.assertGreater(c.stop, c.entry_high)
        self.assertTrue(all(t < c.entry_low for t in c.targets))
        self.assertEqual(c.targets, sorted(c.targets, reverse=True))

    def test_unavailable_order_flow_is_labelled_and_penalised(self):
        with_flow = self.run_bull().best.score
        r = self.run_bull(order_flow=None)
        self.assertEqual(r.best.order_flow_status, "unavailable")
        self.assertEqual(r.best.breakdown["order_flow"]["points"], 0)
        self.assertEqual(with_flow - r.best.score, DEFAULT_SCORE_WEIGHTS["order_flow"])

    def test_required_order_flow_rejects_when_unavailable(self):
        r = self.run_bull(cfg=EngineConfig(require_order_flow=True), order_flow=None)
        self.assertEqual(r.state, "WAIT")

    def test_opposing_order_flow_rejects(self):
        self.assertEqual(self.run_bull(order_flow=BEAR_FLOW).state, "WAIT")

    def test_threshold_is_configurable(self):
        self.assertEqual(self.run_bull(cfg=EngineConfig(a_plus_threshold=99)).state, "WAIT")

    def test_stale_data_never_signals(self):
        r = self.run_bull(data_fresh=False)
        self.assertEqual(r.state, "NO_TRADE")
        self.assertEqual(r.candidates, [])

    def test_insufficient_history(self):
        s = bullish_crt_scenario()
        self.assertEqual(analyze("BTCUSD", s["h1"][-10:], s["m5"], EngineConfig()).state, "NO_TRADE")

    def test_sweep_alone_waits_for_structure_shift(self):
        s = bullish_crt_scenario()
        r = self.run_bull(ltf=s["m5"][:-4], price=s["m5"][-5].close)
        self.assertEqual(r.state, "WAIT")
        self.assertTrue(any("market-structure shift" in x for c in r.candidates for x in c.rejections))

    def test_price_beyond_stop_invalidates(self):
        self.assertNotEqual(self.run_bull(price=980).state, "BUY")

    def test_chasing_far_from_entry_rejected(self):
        self.assertNotEqual(self.run_bull(cfg=EngineConfig(max_entry_distance_atr=0.1)).state, "BUY")

    def test_min_risk_reward_enforced(self):
        self.assertNotEqual(self.run_bull(cfg=EngineConfig(min_risk_reward=10)).state, "BUY")
