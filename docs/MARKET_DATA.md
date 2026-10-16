# Market data providers

Each instrument in Django admin names a provider key and a provider symbol. Providers implement `markets/providers/base.py::MarketDataProvider` (`fetch_candles`, `fetch_quote`, optional `fetch_trades` / `fetch_order_book`).

| Key | Instruments | Credentials | Volume type | Order flow |
|---|---|---|---|---|
| `coinbase` (default BTC) | BTC-USD | none (public) | Exchange volume (Coinbase only, not global) | Yes: recent trades (aggressor side) + level-2 book |
| `kraken` | XBTUSD | none (public) | Exchange volume (Kraken only) | Yes: recent trades + depth |
| `twelvedata` (default gold) | XAU/USD | `TWELVEDATA_API_KEY` | **None**: aggregated OTC quotes | **No** |
| `oanda` | XAU_USD | `OANDA_API_TOKEN` (+ `OANDA_ENVIRONMENT`) | **Tick volume** (broker price-change count) | **No** |
| `sample` | any | none | synthetic | synthetic, labelled SAMPLE |

**Honesty rules enforced in code**
- Spot gold is OTC and has no centralized volume, tape or order book. Gold signals are always labelled *order flow unavailable*, and that factor scores 0 (or rejects the setup if "require order flow" is enabled).
- BTC order flow is one venue's flow, not the whole market. The UI says which exchange.
- Binance is not used: its API returned a restricted-location error from the development host. Check your jurisdiction before adding it.
- A missing API key shows the feed as **unavailable**. Prices are never invented. Sample data is never shown as live, and sample signals are excluded from statistics.

**Validation / freshness** (`markets/services.py`): drops candles with invalid OHLC (high < max(open, close), etc.) or NaN values, de-duplicates by open time, sorts, counts gaps, splits off the forming candle, and marks a timeframe stale when its last completed candle is older than one interval + `MARKET_DATA_STALE_GRACE_SECONDS`. Responses are cached (`MARKET_DATA_CACHE_SECONDS`) and retried with backoff. Each instrument's health (`MarketDataStatus`) is shown on the market overview and staff dashboard.

Timestamps are stored in UTC and displayed in Africa/Nairobi time.
