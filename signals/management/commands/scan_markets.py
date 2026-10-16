from django.core.management.base import BaseCommand

from signals.models import MarketScanRun
from signals.scanner import run_scan


class Command(BaseCommand):
    help = "Run one market scan (use with cron / Windows Task Scheduler)."

    def handle(self, *args, **options):
        run = run_scan(trigger=MarketScanRun.Trigger.COMMAND)
        self.stdout.write(f"Scan {run.pk}: {run.status} - created {run.signals_created}, updated {run.signals_updated}")
        for symbol, info in run.results.items():
            self.stdout.write(f"  {symbol}: {info.get('state')} {info.get('summary') or info.get('error') or ''}")
        for err in run.errors:
            self.stderr.write(f"  error: {err}")
