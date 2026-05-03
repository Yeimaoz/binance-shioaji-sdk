"""Smoke tests for lcz_binance_sdk._internal.rest_client.

Bootstrap-level: only verify imports and pure-function behavior (sign_request,
_TokenBucket arithmetic). Network-touching tests come in v0.1.x.
"""
from __future__ import annotations

import pytest


def test_top_level_imports() -> None:
    from lcz_binance_sdk import (
        BinanceRestClient,
        BinanceWSManager,
        ExecutionReport,
        _TokenBucket,
        __version__,
        sign_request,
    )

    assert __version__ == "0.0.1"
    assert BinanceRestClient is not None
    assert BinanceWSManager is not None
    assert ExecutionReport is not None
    assert _TokenBucket is not None
    assert callable(sign_request)


def test_internal_imports() -> None:
    from lcz_binance_sdk._internal import (
        _ENDPOINT_WEIGHTS,
        _WEIGHT_LIMIT_PER_MIN,
        LISTEN_KEY_KEEPALIVE_INTERVAL,
        VALID_KLINE_INTERVALS,
        WS_RECONNECT_BASE,
        WS_RECONNECT_MAX,
    )

    assert _WEIGHT_LIMIT_PER_MIN == 2400
    assert isinstance(_ENDPOINT_WEIGHTS, dict)
    assert "1m" in VALID_KLINE_INTERVALS
    assert LISTEN_KEY_KEEPALIVE_INTERVAL == 30 * 60
    assert WS_RECONNECT_BASE == 1.0
    assert WS_RECONNECT_MAX == 60.0


def test_sign_request_pure_function() -> None:
    from lcz_binance_sdk import sign_request

    out = sign_request("test_secret", {"symbol": "BTCUSDT"})
    assert "timestamp" in out
    assert "signature" in out
    assert out["symbol"] == "BTCUSDT"
    # signature is hex-encoded HMAC-SHA256 → 64 hex chars
    assert len(out["signature"]) == 64
    assert all(c in "0123456789abcdef" for c in out["signature"])


def test_sign_request_rejects_empty_secret() -> None:
    from lcz_binance_sdk import sign_request

    with pytest.raises(ValueError):
        sign_request("", {"symbol": "BTCUSDT"})


def test_token_bucket_initial_capacity() -> None:
    from lcz_binance_sdk import _TokenBucket

    bucket = _TokenBucket(capacity=100, window_seconds=10.0)
    assert bucket.capacity == 100
    assert bucket._tokens == 100.0


def test_execution_report_dataclass() -> None:
    from lcz_binance_sdk import ExecutionReport

    rpt = ExecutionReport(
        order_id="123",
        symbol="BTCUSDT",
        status="FILLED",
        side="BUY",
        order_type="MARKET",
        qty=1.0,
        filled_qty=1.0,
        last_filled_price=50000.0,
        avg_price=50000.0,
    )
    assert rpt.order_id == "123"
    assert rpt.raw == {}
