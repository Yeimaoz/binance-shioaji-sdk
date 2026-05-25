"""v0.4.0 unified typed exception hierarchy.

All SDK errors inherit from BinanceSDKError so consumers can write a single
`except BinanceSDKError` to catch any SDK-level failure (auth, account,
market data). Migrated from _internal/types.BinanceAuthError; reparented
from Exception to BinanceSDKError.
"""
from __future__ import annotations


class BinanceSDKError(Exception):
    """Base for all v0.4.0+ typed errors. Single root for unified catch."""


class BinanceMarketDataError(BinanceSDKError):
    """Raised when market_info endpoint returns API error or parse fail."""


class BinanceAccountError(BinanceSDKError):
    """Raised when account / position / balance endpoint returns API error."""


class BinanceAuthError(BinanceSDKError):
    """Login or auth failure (401/403). Migrated from _internal/types.py
    in v0.4.0; previously was `class BinanceAuthError(Exception)`. Now
    subclass of BinanceSDKError so consumers can catch all SDK errors
    via `except BinanceSDKError`."""
