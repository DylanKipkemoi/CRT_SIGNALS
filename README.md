# CRT Signals: BTCUSD & XAUUSD A+ trading signals platform

A Django platform that scans BTCUSD and XAUUSD with **1H Candle Range Theory (CRT)** plus ICT/SMC structure, price action and (where genuine data exists) order flow. Each setup is scored out of 100 using transparent rules, and only **A+** setups are published. Users get **one free signal**. After that, **KSh 500 via M-Pesa STK Push** unlocks that day's signals (Africa/Nairobi day).

> Signals are rule-based analysis, not financial advice. No win rate or profit is promised. Scores measure confluence, not probability.

## What's included
| Area | Where |
|---|---|
| Registration, email verification, login rate limiting, password reset, suspension | `accounts/` |
| Site configuration (fee, A+ threshold, weights, expiry), audit log, CSP, rate limiter | `core/` |
| Market-data providers (Coinbase, Kraken, OANDA, Twelve Data, offline sample), validation, caching, freshness, candle storage | `markets/` |
| CRT/ICT/SMC engine (pure Python), scanner, lifecycle tracking, charts API | `signals/` |
| One-time free entitlement, paid daily access | `access/` |
| Daraja STK Push, callbacks, verification, reconciliation | `payments/` |
| Staff dashboard (health, feeds, payments, audit, manual scan) | `/staff/` |

Further docs: [Architecture](docs/ARCHITECTURE.md) · [Signal rules & scoring](docs/SCORING.md) · [Market data](docs/MARKET_DATA.md) · [M-Pesa Daraja](docs/DARAJA.md) · [Deployment & security](docs/DEPLOYMENT.md)

## Requirements
- Python **3.14** (tested with 3.14.8). Also works on 3.12 and 3.13.
- Django **5.2 LTS**, requests, python-dotenv, whitenoise, tzdata (see `requirements.txt`).
- SQLite for development. Use PostgreSQL in production (`DATABASE_ENGINE`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, ...; see DEPLOYMENT.md).

## Windows PowerShell quick start
```powershell
git clone https://github.com/<you>/crt-signals.git
cd crt-signals
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env            # then edit .env (DJANGO_DEBUG=true for local dev)
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
Open http://127.0.0.1:8000. Verification and reset emails print to the console in development.

### Run the scanner
```powershell
python manage.py scan_markets          # one scan
python manage.py run_scanner           # loop every SCANNER_INTERVAL_SECONDS (default 300); Ctrl+C to stop
python manage.py reconcile_payments    # resolve stale pending M-Pesa payments
```
In production, run `scan_markets` from cron, systemd timers or Windows Task Scheduler, or run `run_scanner` as a service (see DEPLOYMENT.md).

### Offline demo (sample data, clearly labelled)
```powershell
python manage.py generate_sample_data --activate   # points both instruments at SAMPLE data
python manage.py scan_markets
```
All sample candles and signals are marked **SAMPLE — not live** and left out of public statistics. To switch back to live feeds, set the provider of each instrument in Django admin (Markets → Instruments): BTCUSD → `coinbase` / `BTC-USD`, XAUUSD → `twelvedata` / `XAU/USD` or `oanda` / `XAU_USD`.

### Tests
```powershell
python manage.py test
```
The tests cover registration/login, the once-only free signal, denial after use, KSh 500 payment success/failed/duplicate/mismatch callbacks, Nairobi expiry, stale and missing data, CRT sweeps, BOS/CHOCH/MSS, FVG and order blocks, scoring, BUY/SELL risk/reward, duplicate signals and lifecycle transitions.

## Configuration
All secrets come from environment variables or `.env` (never commit it). See `.env.example`. Key items:
- `DJANGO_SECRET_KEY`: required when `DJANGO_DEBUG` is false.
- `TWELVEDATA_API_KEY` or `OANDA_API_TOKEN`: required for the XAUUSD feed. Without one, gold shows *feed unavailable* (never fake prices).
- `DARAJA_*`: M-Pesa credentials, see [DARAJA.md](docs/DARAJA.md).

Business rules (fee, free allowance, A+ threshold, score weights, min R:R, order-flow requirement, signal expiry) can be edited in **Django admin → Site configuration**.
