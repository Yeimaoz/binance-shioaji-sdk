"""
binance_shioaji_sdk/_internal — Binance SDK private plumbing layer
==============================================================

Step 1 of Binance SDK mirror design: protocol-level plumbing
(HMAC sign / httpx REST / TokenBucket / WS reconnect / listen_key keepalive).

對外不公開，public API 由 binance_shioaji_sdk 套件 re-export 必要 symbol。
"""
from binance_shioaji_sdk._internal.rest_client import (
    BinanceRestClient,
    _TokenBucket,  # noqa: F401 — re-exported for test access; not in __all__ (underscore = private)
    sign_request,  # noqa: F401 — re-exported for test access; not in __all__
    _ENDPOINT_WEIGHTS,  # noqa: F401 — re-exported for test access; not in __all__
    _WEIGHT_LIMIT_PER_MIN,  # noqa: F401 — re-exported for test access; not in __all__
)
# v0.4.0: BinanceAuthError lives in top-level exceptions.py.
# v0.5.0: ExecutionReport alias removed; use BinanceFillReport.
from binance_shioaji_sdk.exceptions import BinanceAuthError
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
    # Note: _TokenBucket, sign_request, _ENDPOINT_WEIGHTS, _WEIGHT_LIMIT_PER_MIN
    # are private implementation details (underscore-prefixed) and intentionally
    # omitted from __all__ to prevent `import *` re-export.
    "LISTEN_KEY_KEEPALIVE_INTERVAL",
    "VALID_KLINE_INTERVALS",
    "WS_RECONNECT_BASE",
    "WS_RECONNECT_MAX",
]
