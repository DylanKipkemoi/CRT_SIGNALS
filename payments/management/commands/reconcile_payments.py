from django.core.management.base import BaseCommand

from payments.services import reconcile_pending_payments


class Command(BaseCommand):
    help = "Resolve stale pending M-Pesa payments using the STK Push Query API."

    def handle(self, *args, **options):
        count = reconcile_pending_payments()
        self.stdout.write(f"Reconciled {count} payment(s).")
