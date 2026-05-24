"""
binance_shioaji_sdk/order.py - Order public API
===========================================

Mirrors shioaji `sj.Order` shape: a frozen dataclass describing the order
parameters the user sends to the broker, plus an `OrderResponse` wrapping
the broker ack.

This module also exposes module-level helpers (`place_order_via`,
`cancel_order_via`, `list_trades_via`) that contain the actual REST logic
and accept an injected `rest_client`. The wire-in to `Binance`
methods lands in a follow-up PR.

Logic adapted from an upstream shioaji-style broker adapter
(`place_order` / `cancel_order`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from binance_shioaji_sdk.contracts import BinanceContract
    from binance_shioaji_sdk._internal import BinanceRestClient


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Order:
    """User-facing order parameter struct.

    Attributes
    ----------
    price          : limit price (ignored when price_type='MKT')
    quantity       : order size (in contracts; integer for parity with shioaji)
    action         : 'long' (BUY) or 'short' (SELL)
    price_type     : 'MKT' or 'LMT'
    reduce_only    : Binance reduceOnly flag (close-only orders)
    time_in_force  : 'GTC' | 'IOC' | 'FOK' | 'GTX'
    client_order_id: optional caller-supplied id (Binance: newClientOrderId)
    """

    price: float
    quantity: int
    action: str  # 'long' | 'short'
    price_type: str  # 'MKT' | 'LMT'
    reduce_only: bool = False
    time_in_force: str = "GTC"
    client_order_id: str | None = None


@dataclass(frozen=True)
class OrderResponse:
    """Wrap broker ack into a stable shape.

    Mirrors an upstream broker adapter `OrderAck` but extends with `client_order_id` and
    `filled_quantity` for parity with shioaji's `Trade`.
    """

    order_id: str
    client_order_id: str
    symbol: str
    status: str
    filled_quantity: int = 0
    avg_filled_price: float | None = None
    raw: dict[str, Any] | None = field(default=None)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_TIF = frozenset({"GTC", "IOC", "FOK", "GTX"})
_VALID_ACTION = frozenset({"long", "short"})
_VALID_PRICE_TYPE = frozenset({"MKT", "LMT"})


def _normalize_symbol(raw: str) -> str:
    sym = raw.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    return sym


# ---------------------------------------------------------------------------
# Module-level helpers (called by Binance methods in wire-in PR)
# ---------------------------------------------------------------------------


async def place_order_via(
    rest_client: "BinanceRestClient",
    contract: "BinanceContract",
    order: Order,
    *,
    base_url: str | None = None,  # accepted for API parity; not used (rest_client owns it)
) -> OrderResponse:
    """Send a Binance USDM order (HMAC-signed POST /fapi/v1/order).

    Parameters
    ----------
    rest_client : `BinanceRestClient` (already connected)
    contract    : `BinanceContract` (provides symbol)
    order       : `Order` value
    base_url    : ignored; kept so the call-site signature can read naturally

    Returns
    -------
    `OrderResponse`. On 4xx the response carries `status='REJECTED'` plus the
    raw error payload — the caller decides whether to raise.
    """
    if order.action not in _VALID_ACTION:
        raise ValueError(f"[order] action must be 'long' or 'short', got {order.action!r}")
    if order.price_type not in _VALID_PRICE_TYPE:
        raise ValueError(f"[order] price_type must be 'MKT' or 'LMT', got {order.price_type!r}")
    if order.time_in_force not in _VALID_TIF:
        raise ValueError(
            f"[order] time_in_force must be one of {sorted(_VALID_TIF)}, got {order.time_in_force!r}"
        )
    if order.price_type == "LMT" and order.price <= 0:
        raise ValueError("[order] LMT order requires positive price")
    if order.quantity <= 0:
        raise ValueError("[order] quantity must be positive")

    sym = _normalize_symbol(contract.symbol)
    side = "BUY" if order.action == "long" else "SELL"
    binance_type = "MARKET" if order.price_type == "MKT" else "LIMIT"

    params: dict[str, Any] = {
        "symbol": sym,
        "side": side,
        "type": binance_type,
        "quantity": str(order.quantity),
    }
    if binance_type == "LIMIT":
        params["price"] = str(order.price)
        params["timeInForce"] = order.time_in_force
    if order.reduce_only:
        params["reduceOnly"] = "true"
    if order.client_order_id:
        params["newClientOrderId"] = order.client_order_id

    raw = await rest_client.post("/fapi/v1/order", params=params, signed=True)

    if isinstance(raw, dict) and "error" in raw:
        return OrderResponse(
            order_id="",
            client_order_id=order.client_order_id or "",
            symbol=sym,
            status="REJECTED",
            raw=raw,
        )

    avg_raw = raw.get("avgPrice", "0") if isinstance(raw, dict) else "0"
    try:
        avg = float(avg_raw)
    except (TypeError, ValueError):
        avg = 0.0
    avg_filled = avg if avg > 0 else None

    try:
        executed_qty = int(float(raw.get("executedQty", "0") or "0"))
    except (TypeError, ValueError):
        executed_qty = 0

    return OrderResponse(
        order_id=str(raw.get("orderId", "")),
        client_order_id=str(raw.get("clientOrderId", order.client_order_id or "")),
        symbol=sym,
        status=str(raw.get("status", "NEW")),
        filled_quantity=executed_qty,
        avg_filled_price=avg_filled,
        raw=raw,
    )


async def cancel_order_via(
    rest_client: "BinanceRestClient",
    symbol: str,
    order_id: str,
) -> bool:
    """Cancel a working order (DELETE /fapi/v1/order). Returns True on CANCELED."""
    sym = _normalize_symbol(symbol)
    try:
        oid = int(order_id)
    except (TypeError, ValueError):
        return False

    raw = await rest_client.delete(
        "/fapi/v1/order",
        params={"symbol": sym, "orderId": oid},
        signed=True,
    )
    if isinstance(raw, dict) and "error" in raw:
        return False
    return isinstance(raw, dict) and raw.get("status") == "CANCELED"


async def list_trades_via(
    rest_client: "BinanceRestClient",
    symbol: str | None = None,
    limit: int = 500,
) -> list[OrderResponse]:
    """List recent orders for the account (GET /fapi/v1/allOrders).

    When `symbol` is None, returns []  -- Binance's allOrders endpoint
    requires a symbol. (Shioaji `list_trades` returns all; we keep
    Binance's constraint and document it.)
    """
    if symbol is None:
        return []

    sym = _normalize_symbol(symbol)
    params: dict[str, Any] = {
        "symbol": sym,
        "limit": min(max(1, limit), 1000),
    }
    raw = await rest_client.get("/fapi/v1/allOrders", params=params, signed=True)

    if isinstance(raw, dict) and "error" in raw:
        return []
    if not isinstance(raw, list):
        return []

    out: list[OrderResponse] = []
    for entry in raw:
        try:
            avg_raw = entry.get("avgPrice", "0") or "0"
            avg = float(avg_raw)
            avg_filled = avg if avg > 0 else None
            executed_qty = int(float(entry.get("executedQty", "0") or "0"))
            out.append(
                OrderResponse(
                    order_id=str(entry.get("orderId", "")),
                    client_order_id=str(entry.get("clientOrderId", "")),
                    symbol=str(entry.get("symbol", sym)),
                    status=str(entry.get("status", "")),
                    filled_quantity=executed_qty,
                    avg_filled_price=avg_filled,
                    raw=entry,
                )
            )
        except (TypeError, ValueError, KeyError):
            continue
    return out


__all__ = [
    "Order",
    "OrderResponse",
    "place_order_via",
    "cancel_order_via",
    "list_trades_via",
]
