"""v0.4.0 exception hierarchy tests."""
from __future__ import annotations

import pytest


def test_binance_sdk_error_is_base():
    from binance_shioaji_sdk.exceptions import BinanceSDKError
    assert issubclass(BinanceSDKError, Exception)


def test_market_data_error_is_subclass():
    from binance_shioaji_sdk.exceptions import BinanceSDKError, BinanceMarketDataError
    assert issubclass(BinanceMarketDataError, BinanceSDKError)


def test_account_error_is_subclass():
    from binance_shioaji_sdk.exceptions import BinanceSDKError, BinanceAccountError
    assert issubclass(BinanceAccountError, BinanceSDKError)


def test_auth_error_is_subclass_of_sdk_error():
    """v0.4.0 reparents BinanceAuthError under BinanceSDKError for unified catch."""
    from binance_shioaji_sdk.exceptions import BinanceSDKError, BinanceAuthError
    assert issubclass(BinanceAuthError, BinanceSDKError)


def test_unified_catch_via_sdk_error():
    from binance_shioaji_sdk.exceptions import (
        BinanceSDKError, BinanceMarketDataError, BinanceAccountError, BinanceAuthError,
    )
    for cls in (BinanceMarketDataError, BinanceAccountError, BinanceAuthError):
        with pytest.raises(BinanceSDKError):
            raise cls("test")
