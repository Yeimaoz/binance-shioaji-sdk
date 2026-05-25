"""
binance_shioaji_sdk/fill_report.py — public BinanceFillReport dataclass
========================================================================

This module exposes ``BinanceFillReport``, a rename of the internal
``ExecutionReport`` found in ``_internal/types.py``.

H-1 vocabulary exemption (design §3.7)
---------------------------------------
Field names intentionally retain Binance-native vocabulary (``order_id``,
``filled_qty``, ``last_filled_price``, etc.) rather than being renamed to
shioaji-styled equivalents. ``sj.Deal`` has no field-by-field mirror analog,
so a vocabulary translation would introduce ambiguity without adding clarity.

Usage::

    from binance_shioaji_sdk.fill_report import BinanceFillReport
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BinanceFillReport:
    """Structured representation of a Binance executionReport event.

    H-1 vocabulary exemption per design §3.7: field names keep Binance-native
    vocabulary (``order_id``, ``filled_qty``, ``last_filled_price``, etc.).
    ``sj.Deal`` has no field-by-field mirror analog, so shioaji-styled names
    would only add confusion.

    Fields copied verbatim from ``_internal/types.py`` ``ExecutionReport``.

    NOTE (L-1): ``frozen=True`` upgrade in v0.4.0 (shioaji coding style).
    Original ``ExecutionReport`` is mutable; ``BinanceFillReport`` is not.
    Post-construction assignment (e.g. ``report.status = "FILLED"``) raises
    ``dataclasses.FrozenInstanceError``.

    Usage::

        report = BinanceFillReport(
            order_id="123",
            symbol="BTCUSDT",
            status="FILLED",
            side="BUY",
            order_type="MARKET",
            qty=0.001,
            filled_qty=0.001,
            last_filled_price=65000.0,
            avg_price=65000.0,
        )
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
