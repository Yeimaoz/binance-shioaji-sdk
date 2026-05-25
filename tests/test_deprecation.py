"""v0.4.0 deprecation alias mechanism — __init__.py __getattr__ hook."""
from __future__ import annotations

import warnings

import pytest


def test_old_OrderResponse_emits_deprecation_warning():
    """Old name accessed via module attribute → DeprecationWarning."""
    import binance_shioaji_sdk
    with pytest.warns(DeprecationWarning, match="OrderResponse"):
        _ = binance_shioaji_sdk.OrderResponse


def test_old_ExecutionReport_emits_deprecation_warning():
    import binance_shioaji_sdk
    with pytest.warns(DeprecationWarning, match="ExecutionReport"):
        _ = binance_shioaji_sdk.ExecutionReport


def test_old_OrderResponse_forwards_to_BinanceTrade():
    """Deprecated name resolves to new class identity."""
    import binance_shioaji_sdk
    from binance_shioaji_sdk import BinanceTrade
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert binance_shioaji_sdk.OrderResponse is BinanceTrade


def test_old_ExecutionReport_forwards_to_BinanceFillReport():
    import binance_shioaji_sdk
    from binance_shioaji_sdk import BinanceFillReport
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert binance_shioaji_sdk.ExecutionReport is BinanceFillReport


def test_new_BinanceTrade_no_warning_on_import():
    """Positive test (V5): new name path does NOT trigger __getattr__."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from binance_shioaji_sdk import BinanceTrade
        assert BinanceTrade is not None
        assert not any(
            issubclass(x.category, DeprecationWarning) for x in w
        ), f"unexpected DeprecationWarning: {[str(x.message) for x in w]}"


def test_new_BinanceFillReport_no_warning_on_import():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from binance_shioaji_sdk import BinanceFillReport
        assert BinanceFillReport is not None
        assert not any(
            issubclass(x.category, DeprecationWarning) for x in w
        )


def test_unknown_attr_raises_attribute_error():
    import binance_shioaji_sdk
    with pytest.raises(AttributeError, match="no attribute"):
        _ = binance_shioaji_sdk.NonExistentClass
