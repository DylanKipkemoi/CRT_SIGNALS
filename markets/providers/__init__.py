from .base import MarketDataProvider, ProviderError, ProviderNotConfigured
from .coinbase import CoinbaseProvider
from .kraken import KrakenProvider
from .oanda import OandaProvider
from .sample import SampleProvider
from .twelvedata import TwelveDataProvider

PROVIDERS = {
    cls.key: cls
    for cls in (CoinbaseProvider, KrakenProvider, OandaProvider, TwelveDataProvider, SampleProvider)
}

PROVIDER_CHOICES = [(key, cls.name) for key, cls in PROVIDERS.items()]


def get_provider(key):
    try:
        return PROVIDERS[key]()
    except KeyError as exc:
        raise ProviderNotConfigured(f"Unknown market-data provider '{key}'.") from exc


__all__ = [
    "MarketDataProvider", "ProviderError", "ProviderNotConfigured", "PROVIDERS", "PROVIDER_CHOICES", "get_provider",
]
