import signal as os_signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from payments.services import reconcile_pending_payments
from signals.scanner import run_scan


class Command(BaseCommand):
    help = "Run the scanner continuously (development / simple production worker)."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=settings.SCANNER["INTERVAL_SECONDS"])
        parser.add_argument("--iterations", type=int, default=0, help="Stop after N scans (0 = forever).")

    def handle(self, *args, **opts):
        stop = {"flag": False}

        def _stop(*_):
            stop["flag"] = True

        os_signal.signal(os_signal.SIGINT, _stop)
        if hasattr(os_signal, "SIGTERM"):
            os_signal.signal(os_signal.SIGTERM, _stop)
        count = 0
        self.stdout.write(f"Scanner started; interval {opts['interval']}s. Ctrl+C to stop.")
        while not stop["flag"]:
            started = time.monotonic()
            try:
                run = run_scan()
                self.stdout.write(f"[{run.started_at:%H:%M:%S}] scan {run.status}: +{run.signals_created} signals, "
                                  f"{run.signals_updated} updated")
                reconciled = reconcile_pending_payments()
                if reconciled:
                    self.stdout.write(f"  reconciled {reconciled} pending payment(s)")
            except Exception as exc:  # noqa: BLE001 - keep the worker alive
                self.stderr.write(f"scan loop error: {exc}")
            count += 1
            if opts["iterations"] and count >= opts["iterations"]:
                break
            while not stop["flag"] and time.monotonic() - started < opts["interval"]:
                time.sleep(1)
        self.stdout.write("Scanner stopped.")
