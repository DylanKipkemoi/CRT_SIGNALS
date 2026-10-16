import csv

from django.core.management.base import BaseCommand

from core.audit import audit
from markets.models import MarketInstrument
from markets.providers.sample import SAMPLE_DIR
from signals.scenarios import aggregate, bearish_crt_scenario, bullish_crt_scenario


class Command(BaseCommand):
    help = ("Write deterministic SAMPLE candles (not market data) for offline demos. "
            "Use --activate to point instruments at the sample provider.")

    def add_arguments(self, parser):
        parser.add_argument("--activate", action="store_true", help="Switch BTCUSD/XAUUSD to the sample provider.")

    def handle(self, *args, **opts):
        SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
        scenarios = {"BTCUSD": bullish_crt_scenario(), "XAUUSD": bearish_crt_scenario()}
        for symbol, scn in scenarios.items():
            series = {"1h": scn["h1"], "5m": scn["m5"], "15m": aggregate(scn["m5"], "15m", 900)}
            for tf, candles in series.items():
                path = SAMPLE_DIR / f"{symbol}_{tf}.csv"
                with path.open("w", newline="") as fh:
                    w = csv.writer(fh)
                    w.writerow(["open_time", "open", "high", "low", "close", "volume"])
                    for c in candles:
                        w.writerow([c.open_time.isoformat(), c.open, c.high, c.low, c.close, c.volume])
                self.stdout.write(f"wrote {path.name} ({len(candles)} candles)")
        if opts["activate"]:
            for symbol in scenarios:
                MarketInstrument.objects.filter(symbol=symbol).update(provider="sample", provider_symbol=symbol)
                audit("instrument.sample_activated", message=symbol)
            self.stdout.write(self.style.WARNING("Instruments now use SAMPLE data. Every signal will be labelled sample."))
