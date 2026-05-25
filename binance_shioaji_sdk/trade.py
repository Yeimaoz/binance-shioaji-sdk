"""v0.4.0 Trade composite — mirror sj.Trade structure.

Trade = contract + order + status, where status is OrderStatusInfo equiv
(carries broker-assigned id post-submit, fill quantities, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from binance_shioaji_sdk.contracts import BinanceContract
from binance_shioaji_sdk.order import Order


class BinanceOrderStatusEnum(StrEnum):
    """Mirror of sj.OrderStatus — CamelCase member names, identical to shioaji."""
    Cancelled = "Cancelled"
    Failed = "Failed"
    Filled = "Filled"
    Inactive = "Inactive"
    PartFilled = "PartFilled"
    PendingSubmit = "PendingSubmit"
    PreSubmitted = "PreSubmitted"
    Submitted = "Submitted"


@dataclass(frozen=True)
class BinanceTradeStatus:
    """Mirror of sj.OrderStatusInfo — order lifecycle snapshot.

    Broker-assigned order id lives HERE (status.id), NOT on order.
    Consumers access via trade.status.id — matches shioaji idiom exactly.
    """
    id: str                                  # broker order id (mirrors sj.OrderStatusInfo.id)
    status: BinanceOrderStatusEnum
    status_code: str
    order_datetime: str                       # ISO 8601 UTC
    deal_quantity: Optional[int] = None       # cumulative filled qty (Binance: executedQty)
    order_quantity: Optional[int] = None      # original submitted qty (Binance: origQty)
    cancel_quantity: Optional[int] = None     # qty remaining after cancellation
    modified_price: float = 0.0               # weighted avg fill price (0.0 if no fill)
    msg: str = ""                             # broker message (error reason on failure)


@dataclass(frozen=True)
class BinanceTrade:
    """Mirror of sj.Trade — composite returned by place_order().

    contract = the contract that was traded (BinanceContract)
    order    = the user-input order params (Order — no id field per shioaji)
    status   = current status snapshot (BinanceTradeStatus carries broker id)

    Note: shioaji's sj.Trade.order is actually sj.OrderResult (broker-enriched
    with seqno/ordno/ca). v0.4.0 deliberately keeps `order` as the user-input
    Order — Binance has no seqno/ordno equivalent; the only post-submit identifier
    is orderId (captured in status.id).
    """
    contract: BinanceContract
    order: Order
    status: BinanceTradeStatus
