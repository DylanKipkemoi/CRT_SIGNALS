# Signal rules & scoring

All thresholds are in `signals/engine/config.py` (`EngineConfig`). Weights, the A+ threshold, min R:R and the order-flow policy can be overridden in **Site configuration**.

## 1H Candle Range Theory
- **Reference candle (C1)**: a *completed* 1H candle. Its range is high − low, with midpoint (H+L)/2. The range must be ≥ `crt_min_range_atr` × 1H ATR(14).
- **Manipulation candle (C2)**: the next 1H candle.
  - **Bullish CRT**: C2 trades below C1's low by 3–75% of C1's range (sweep), then **closes back above C1's low** and not above C1's high (reclaim).
  - **Bearish CRT**: the mirror image.
  - **Invalid**: no sweep; both sides swept (outside bar); sweep too shallow; sweep too deep (treated as breakout or breakdown); no reclaim close; close beyond the opposite side.
- A sweep is **never** a signal on its own. The engine then needs lower-timeframe confirmation.
- **Provisional**: when C2 is still forming, a setup can be published as *provisional*. It is superseded when confirmed, or invalidated if the candle closes without confirming. Provisional signals cannot use the free entitlement.

## ICT / SMC (5m confirmation by default)
- **Swing**: pivot high/low with `swing_lookback` bars on each side (confirmed only after those bars close, so no look-ahead).
- **BOS**: close beyond the last confirmed swing *in* the trend direction. **CHOCH**: close beyond it *against* the prior trend. **MSS**: a CHOCH whose break candle is a displacement candle.
- **Displacement**: body ≥ 1.2 × ATR and body/range ≥ 0.6.
- **FVG**: 3-candle gap (C1.high < C3.low for bullish) of at least 0.15 × ATR. Tracked as mitigated (touched) or filled (fully closed).
- **Order block**: the last opposite-colour candle before the displacement leg that caused the MSS.
- **Liquidity**: swing highs/lows clustered within 0.1 × ATR (equal highs/lows add touches). Pools are marked swept once traded through.
- **Premium/discount**: position inside the latest swing dealing range. Buys prefer discount, sells prefer premium.

## Entry, stop, targets
- Entry zone: FVG ∩ OB overlap, else the FVG, else the OB. Entry is the zone midpoint.
- Stop: beyond the sweep extreme plus 0.25 × LTF ATR.
- Targets: CRT midpoint, the opposite CRT extreme, then unswept liquidity pools. Only levels beyond both the entry zone and the current price count. Up to 3.
- Rejected when: R:R to the final target < min (default 2.0), stop > 2.5 × 1H ATR, price already beyond the stop or TP1, entry > 1.5 × 1H ATR from price, levels on the wrong side, or order flow opposes.

## Score (100 points, default weights)
| Factor | Pts | Measured by |
|---|---|---|
| CRT alignment | 15 | valid CRT; reclaim beyond midpoint; discount/premium or HTF bias agreement |
| Liquidity sweep | 15 | sweep depth sweet spot (8–50%), rejection wick, sweep of a resting pool |
| Structure shift | 15 | CHOCH+displacement 15, BOS+displacement 12, CHOCH 9, BOS 7.5 |
| Displacement | 10 | strongest leg candle body vs ATR |
| Entry confluence | 10 | FVG+OB 10, FVG 7.5, OB 6 |
| Price action | 10 | rejection wick, break-candle body, engulfing, retest |
| Order flow | 10 | delta, CVD slope, book imbalance, large trades (BTC only). Unavailable = 0 by default |
| Risk/reward | 10 | ≥ min R:R, scaled to 3R |
| Market conditions | 5 | fresh data, normal volatility, premium/discount |

**A+ = score ≥ threshold (default 80) and no rejection reasons.** Scores are confluence measures, not probabilities.

## Lifecycle and outcomes
ACTIVE → TRIGGERED (entry zone touched) → CLOSED (TP3, stop, breakeven after TP1, or timeout). ACTIVE → INVALIDATED (stop or TP1 reached before entry) or EXPIRED (not filled in time). PROVISIONAL → SUPERSEDED/INVALIDATED. If one candle touches both the stop and a target, the stop is assumed hit first (conservative). Realized R assumes equal partials at each target and the stop moved to breakeven after TP1. Public statistics include **every** published live signal.
