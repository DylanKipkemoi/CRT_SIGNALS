from django.contrib import admin

from .audit import audit
from .models import AuditLog, ContactMessage, SiteConfiguration


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Pricing & access", {"fields": ("daily_fee_kes", "free_signals_per_user", "daily_access_end_time")}),
        ("Signal quality", {"fields": ("a_plus_threshold", "score_weights", "min_risk_reward", "require_order_flow",
                                       "order_flow_unavailable_credit", "allow_provisional_signals")}),
        ("Lifecycle", {"fields": ("signal_expiry_hours", "trade_timeout_hours")}),
        ("Scanner", {"fields": ("scanner_enabled", "engine_overrides")}),
    )

    def has_add_permission(self, request):
        return not SiteConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit("config.updated", request=request, target=obj, changed=list(form.changed_data))


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target_type", "target_id", "message", "ip_address")
    list_filter = ("action", "target_type")
    search_fields = ("action", "message", "target_id", "actor__email")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "subject", "name", "email", "handled")
    list_filter = ("handled",)
    search_fields = ("subject", "email", "name")
