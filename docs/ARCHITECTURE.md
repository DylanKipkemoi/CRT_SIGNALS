# Architecture

```
            ┌──────────── scheduler (cron / run_scanner) ────────────┐
            ▼                                                        │
 markets.providers ──► markets.services.fetch_snapshot ──► signals.engine.analyze (pure)
 (Coinbase/Kraken/       validate · dedupe · gaps ·            CRT → SMC → PA → order flow
  OANDA/TwelveData/      completed vs forming · stale ·        → risk → score/100
  Sample)                cache · retries                            │
            │                     │                                 ▼
            ▼                     ▼                     signals.scanner.save_signal (unique setup_key)
      MarketDataStatus       MarketCandle               signals.tracking.update_open_signals
                                                         (triggered / TP / SL / expired / invalidated)
 Users ─► accounts ─► access.services.can_view_signal ◄── DailySignalAccess ◄── payments.services.mark_success
                         (free entitlement, paid day)                         ▲
                                                     Daraja STK Push ─► callback ─► verify (query) ─┘
```

## Data flow
1. **Fetch**: each enabled `MarketInstrument` names a provider. `fetch_snapshot` gets 1H/15M/5M candles, a quote and (BTC only) trades + order book.
2. **Validate**: malformed OHLC rows are dropped, duplicates removed, gaps counted. The forming candle is separated out. A snapshot is **stale** if any timeframe is overdue or the analysis window has gaps. A stale snapshot means NO TRADE.
3. **Analyze**: `signals/engine` is pure Python with no Django imports, so it is fully unit-testable. It returns BUY/SELL (A+ confirmed), WAIT, or NO_TRADE plus every candidate's score breakdown.
4. **Persist**: qualifying candidates become `TradingSignal` rows. `setup_key` (symbol, direction, reference candle time) is unique, so re-scans cannot duplicate them. Provisional signals are superseded on confirmation, or invalidated if the candle closes without confirming.
5. **Track**: open signals advance through completed 5m candles. Every transition is written to `SignalEvent`.
6. **Access**: `can_view_signal` checks staff, then existing unlock, then active paid day. The free entitlement is consumed atomically (`select_for_update`) and recorded as a `SignalUnlock`.
7. **Payments**: STK Push is initiated server-side. Callbacks are authenticated by a secret URL token (plus an optional IP allowlist), parsed, correlated by `CheckoutRequestID`/`MerchantRequestID`, amount-checked, optionally confirmed via STK Query, and finalised idempotently.

## Models
`accounts.User` (email login, normalized Kenyan phone, verification, suspension) · `core.SiteConfiguration` (singleton) · `core.AuditLog` · `core.ContactMessage` · `markets.MarketInstrument` · `markets.MarketCandle` (unique per instrument/provider/timeframe/open_time) · `markets.MarketDataStatus` · `signals.TradingSignal` (DB check constraints enforce direction-correct levels) · `signals.SignalEvent` · `signals.MarketScanRun` · `signals.InstrumentAnalysis` · `access.FreeSignalEntitlement` · `access.SignalUnlock` · `access.DailySignalAccess` (unique user+date) · `payments.PaymentTransaction` (unique checkout id, unique receipt, one open payment per user) · `payments.MpesaCallbackLog` (sanitised payloads).

## Folder structure
```
config/      settings, urls
core/        site config, audit, rate limiting, CSP middleware, legal pages, staff dashboard
accounts/    custom user, auth views, verification
markets/     providers/, services.py, orderflow.py, sample_data/
signals/     engine/ (config, indicators, smc, crt, price_action, risk, scoring, engine), scanner.py, tracking.py, scenarios.py
access/      entitlement + daily access services
payments/    daraja.py (HTTP client), services.py (workflow), views (callback)
templates/   Bootstrap 5 templates;  static/ css, js, vendored Bootstrap + Lightweight Charts
```
