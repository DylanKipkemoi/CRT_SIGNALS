from django.contrib import admin

from .models import DailySignalAccess, FreeSignalEntitlement, SignalUnlock


@admin.register(FreeSignalEntitlement)
class FreeSignalEntitlementAdmin(admin.ModelAdmin):
    list_display = ("user", "allowance", "used", "granted_at", "consumed_at")
    search_fields = ("user__email",)
    readonly_fields = ("user", "used", "granted_at", "consumed_at")


@admin.register(SignalUnlock)
class SignalUnlockAdmin(admin.ModelAdmin):
    list_display = ("user", "signal", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("user__email",)
    readonly_fields = [f.name for f in SignalUnlock._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(DailySignalAccess)
class DailySignalAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "access_date", "starts_at", "expires_at", "source", "payment")
    list_filter = ("source", "access_date")
    search_fields = ("user__email",)
    raw_id_fields = ("user", "payment", "granted_by")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.source = DailySignalAccess.Source.ADMIN
            obj.granted_by = request.user
        super().save_model(request, obj, form, change)
        from core.audit import audit
        audit("access.admin_change", request=request, target=obj, created=not change)
