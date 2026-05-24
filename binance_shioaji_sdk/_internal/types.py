"""
binance_sdk/_internal/types.py — internal dataclasses shared by BinanceRestClient / BinanceWSManager
====================================================================================================

Step 1 of Binance SDK mirror design (internal design study§6).

Public API stability：本 module 為 _internal，不對外公開。
broker_binance.py 仍 re-export ExecutionReport，public 介面不變。
"""
from __future__ import annotations

from dataclasses import dataclass, field


class BinanceAuthError(Exception):
    """Raised when Binance REST endpoint returns 401 or 403.

    Distinguishes authentication failure (bad credentials) from transient
    errors (5xx / network). Used so callers like ``BinanceClient.login()``
    can fail fast on bad keys instead of returning a half-connected client.
    """


@dataclass
class ExecutionReport:
    """Binance executionReport 事件的結構化表示。

    用途：userDataStream 推送 order 事件時，BinanceAdapter 解析後
    存入 _execution_reports[order_id]，wait_fill() 監聽這份資料。
    """
    order_id: str
    symbol: str
    status: str          # "NEW" | "PARTIALLY_FILLED" | "FILLED" | "CANCELED" | "EXPIRED"
    side: str            # "BUY" | "SELL"
    order_type: str      # "MARKET" | "LIMIT"
    qty: float           # 委託量
    filled_qty: float    # 已成交量（累計）
    last_filled_price: float  # 最後成交均價
    avg_price: float     # 整單均價
    raw: dict = field(default_factory=dict)
