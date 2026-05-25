"""
binance_shioaji_sdk/_internal — Binance SDK private plumbing layer
==============================================================

Step 1 of Binance SDK mirror design: protocol-level plumbing
(HMAC sign / httpx REST / TokenBucket / WS reconnect / listen_key keepalive).

對外不公開，public API 由 binance_shioaji_sdk 套件 re-export 必要 symbol。
"""
from binance_shioaji_sdk._internal.rest_client import (
    BinanceRestClient,
    _TokenBucket,
    sign_request,
    _ENDPOINT_WEIGHTS,
    _WEIGHT_LIMIT_PER_MIN,
)
# v0.4.0: BinanceAuthError now lives in top-level exceptions.py.
# ExecutionReport replaced by BinanceFillReport (top-level fill_report.py);
# the old ExecutionReport class is still defined in types.py for backwards-compat
# of internal callers but the top-level __init__.py exposes the new name only
# (via __getattr__ deprecation hook).
from binance_shioaji_sdk.exceptions import BinanceAuthError
from binance_shioaji_sdk._internal.types import ExecutionReport  # legacy internal use
from binance_shioaji_sdk.fill_report import BinanceFillReport
from binance_shioaji_sdk._internal.ws_manager import (
    BinanceWSManager,
    LISTEN_KEY_KEEPALIVE_INTERVAL,
    VALID_KLINE_INTERVALS,
    WS_RECONNECT_BASE,
    WS_RECONNECT_MAX,
)

__all__ = [
    "BinanceAuthError",
    "BinanceFillReport",
    "BinanceRestClient",
    "BinanceWSManager",
    "ExecutionReport",   # legacy — Task 10 quote.py migrates away from this
    "_TokenBucket",
    "sign_request",
    "_ENDPOINT_WEIGHTS",
    "_WEIGHT_LIMIT_PER_MIN",
    "LISTEN_KEY_KEEPALIVE_INTERVAL",
    "VALID_KLINE_INTERVALS",
    "WS_RECONNECT_BASE",
    "WS_RECONNECT_MAX",
]
