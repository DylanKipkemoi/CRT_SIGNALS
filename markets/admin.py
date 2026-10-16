from django import forms
from django.contrib import admin

from .models import MarketCandle, MarketDataStatus, MarketInstrument
from .providers import PROVIDER_CHOICES


class InstrumentForm(forms.ModelForm):
    provider = forms.ChoiceField(choices=PROVIDER_CHOICES)

    class Meta:
        model = MarketInstrument
        fields = "__all__"


@admin.register(MarketInstrument)
class MarketInstrumentAdmin(admin.ModelAdmin):
    form = InstrumentForm
    list_display = ("symbol", "name", "provider", "provider_symbol", "is_enabled")
    list_editable = ("is_enabled",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from core.audit import audit
        audit("instrument.updated", request=request, target=obj, changed=list(form.changed_data))


@admin.register(MarketDataStatus)
class MarketDataStatusAdmin(admin.ModelAdmin):
    list_display = ("instrument", "provider", "is_live", "last_price", "last_success_at", "is_stale",
                    "consecutive_failures", "order_flow_available")
    readonly_fields = [f.name for f in MarketDataStatus._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(MarketCandle)
class MarketCandleAdmin(admin.ModelAdmin):
    list_display = ("instrument", "timeframe", "open_time", "open", "high", "low", "close", "volume", "provider",
                    "is_sample")
    list_filter = ("instrument", "timeframe", "provider", "is_sample")
    date_hierarchy = "open_time"
