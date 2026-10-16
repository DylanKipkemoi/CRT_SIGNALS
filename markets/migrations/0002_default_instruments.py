from django.db import migrations


def create_defaults(apps, schema_editor):
    Instrument = apps.get_model("markets", "MarketInstrument")
    Instrument.objects.get_or_create(symbol="BTCUSD", defaults={
        "name": "Bitcoin vs US Dollar", "asset_class": "crypto", "provider": "coinbase",
        "provider_symbol": "BTC-USD", "price_decimals": 2, "sort_order": 1})
    Instrument.objects.get_or_create(symbol="XAUUSD", defaults={
        "name": "Gold vs US Dollar", "asset_class": "metal", "provider": "twelvedata",
        "provider_symbol": "XAU/USD", "price_decimals": 2, "sort_order": 2})
    SiteConfiguration = apps.get_model("core", "SiteConfiguration")
    SiteConfiguration.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("markets", "0001_initial"), ("core", "0001_initial")]
    operations = [migrations.RunPython(create_defaults, migrations.RunPython.noop)]
