from django.contrib import admin

from .models import InstrumentAnalysis, MarketScanRun, SignalEvent, TradingSignal


class SignalEventInline(admin.TabularInline):
    model = SignalEvent
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in SignalEvent._meta.fields]


@admin.register(TradingSignal)
class TradingSignalAdmin(admin.ModelAdmin):
    list_display = ("id", "instrument", "direction", "score", "classification", "status", "outcome", "realized_r",
                    "is_sample", "created_at")
    list_filter = ("instrument", "direction", "status", "outcome", "is_sample", "is_provisional")
    search_fields = ("setup_key",)
    inlines = [SignalEventInline]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in TradingSignal._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(MarketScanRun)
class MarketScanRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "trigger", "status", "instruments_scanned", "signals_created", "signals_updated",
                    "duration_seconds")
    list_filter = ("status", "trigger")
    readonly_fields = [f.name for f in MarketScanRun._meta.fields]


@admin.register(InstrumentAnalysis)
class InstrumentAnalysisAdmin(admin.ModelAdmin):
    list_display = ("instrument", "state", "bias", "best_score", "summary", "updated_at")
    readonly_fields = [f.name for f in InstrumentAnalysis._meta.fields]
