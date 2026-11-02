"""Builds provider adapters from configuration."""

from pydantic import SecretStr

from app.core.config import Settings
from app.data.providers.base import MarketDataProvider
from app.data.providers.dhan import DhanProvider
from app.data.providers.upstox import UpstoxProvider

SUPPORTED_PROVIDERS = frozenset({DhanProvider.code, UpstoxProvider.code})


def _token(code: str, settings: Settings) -> SecretStr | None:
    return {
        DhanProvider.code: settings.dhan_access_token,
        UpstoxProvider.code: settings.upstox_access_token,
    }.get(code)


def is_configured(code: str, settings: Settings) -> bool:
    return _token(code, settings) is not None


def build_provider(code: str, settings: Settings) -> MarketDataProvider:
    if code == DhanProvider.code:
        return DhanProvider(settings.dhan_access_token)
    if code == UpstoxProvider.code:
        return UpstoxProvider(settings.upstox_access_token)
    raise ValueError(f"Unknown market data provider: {code}")
