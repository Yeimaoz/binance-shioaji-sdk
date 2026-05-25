"""
binance_sdk/_internal/types.py — internal re-exports.

v0.5.0: ExecutionReport dataclass removed; use BinanceFillReport from
top-level binance_shioaji_sdk.fill_report instead. Module kept only for
ws_manager.py's BinanceAuthError import path.
"""
from __future__ import annotations

# v0.4.0: BinanceAuthError moved to top-level binance_shioaji_sdk.exceptions.
# Re-exported here for ws_manager.py. New code: import from .exceptions.
from binance_shioaji_sdk.exceptions import BinanceAuthError  # noqa: F401
