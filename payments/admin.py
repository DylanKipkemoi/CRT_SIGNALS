from django.contrib import admin, messages

from core.audit import audit

from .models import MpesaCallbackLog, PaymentTransaction
from .services import reconcile_payment


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "amount", "status", "mpesa_receipt", "phone_masked", "access_date",
                    "needs_review")
    list_filter = ("status", "needs_review", "environment")
    search_fields = ("user__email", "mpesa_receipt", "checkout_request_id", "reference")
    readonly_fields = [f.name for f in PaymentTransaction._meta.fields if f.name not in ("needs_review", "review_note")]
    actions = ["reconcile"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Reconcile with M-Pesa (STK query)")
    def reconcile(self, request, queryset):
        for p in queryset:
            result = reconcile_payment(p)
            audit("payment.admin_reconcile", request=request, target=p, result=str(result))
        self.message_user(request, "Reconciliation attempted.", messages.INFO)


@admin.register(MpesaCallbackLog)
class MpesaCallbackLogAdmin(admin.ModelAdmin):
    list_display = ("received_at", "checkout_request_id", "source_ip", "accepted", "outcome")
    list_filter = ("accepted",)
    search_fields = ("checkout_request_id",)
    readonly_fields = [f.name for f in MpesaCallbackLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
