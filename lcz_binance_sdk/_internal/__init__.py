"""
lcz_binance_sdk/_internal — Binance SDK private plumbing layer
==============================================================

Step 1 of Binance SDK mirror design: protocol-level plumbing
(HMAC sign / httpx REST / TokenBucket / WS reconnect / listen_key keepalive).

對外不公開，public API 由 lcz_binance_sdk 套件 re-export 必要 symbol。
"""
from lcz_binance_sdk._internal.rest_client import (
    BinanceRestClient,
    _TokenBucket,
    sign_request,
    _ENDPOINT_WEIGHTS,
    _WEIGHT_LIMIT_PER_MIN,
)
from lcz_binance_sdk._internal.types import ExecutionReport
from lcz_binance_sdk._internal.ws_manager import (
    BinanceWSManager,
    LISTEN_KEY_KEEPALIVE_INTERVAL,
    VALID_KLINE_INTERVALS,
    WS_RECONNECT_BASE,
    WS_RECONNECT_MAX,
)

__all__ = [
    "BinanceRestClient",
    "BinanceWSManager",
    "ExecutionReport",
    "_TokenBucket",
    "sign_request",
    "_ENDPOINT_WEIGHTS",
    "_WEIGHT_LIMIT_PER_MIN",
    "LISTEN_KEY_KEEPALIVE_INTERVAL",
    "VALID_KLINE_INTERVALS",
    "WS_RECONNECT_BASE",
    "WS_RECONNECT_MAX",
]
