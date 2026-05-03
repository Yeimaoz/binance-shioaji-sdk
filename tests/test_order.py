"""Tests for lcz_binance_sdk.order public API."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeContract:
    def __init__(self, symbol: str = "BTCUSDT") -> None:
        self.symbol = symbol


class _FakeRest:
    """Minimal async REST stub. Records every call; response queue per (method, path)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses: dict[tuple[str, str], list[Any]] = {}

    def queue(self, method: str, path: str, *responses: Any) -> None:
        self._responses.setdefault((method.upper(), path), []).extend(responses)

    def _next(self, method: str, path: str) -> Any:
        bucket = self._responses.get((method, path), [])
        if not bucket:
            raise AssertionError(f"No response queued for {method} {path}")
        return bucket.pop(0)

    async def get(self, path: str, params: dict | None = None, signed: bool = False, weight: int = 1) -> Any:
        self.calls.append({"method": "GET", "path": path, "params": params, "signed": signed})
        return self._next("GET", path)

    async def post(self, path: str, params: dict | None = None, signed: bool = False, weight: int = 1) -> Any:
        self.calls.append({"method": "POST", "path": path, "params": params, "signed": signed})
        return self._next("POST", path)

    async def delete(self, path: str, params: dict | None = None, signed: bool = False, weight: int = 1) -> Any:
        self.calls.append({"method": "DELETE", "path": path, "params": params, "signed": signed})
        return self._next("DELETE", path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_order_dataclass_frozen() -> None:
    from lcz_binance_sdk.order import Order

    o = Order(price=50000.0, quantity=1, action="long", price_type="LMT")
    assert o.price == 50000.0
    assert o.time_in_force == "GTC"
    assert o.reduce_only is False
    with pytest.raises(FrozenInstanceError):
        o.price = 60000.0  # type: ignore[misc]


def test_order_response_dataclass() -> None:
    from lcz_binance_sdk.order import OrderResponse

    r = OrderResponse(
        order_id="123",
        client_order_id="cli-1",
        symbol="BTCUSDT",
        status="FILLED",
        filled_quantity=2,
        avg_filled_price=51000.0,
        raw={"orderId": 123},
    )
    assert r.order_id == "123"
    assert r.filled_quantity == 2
    assert r.raw == {"orderId": 123}


@pytest.mark.asyncio
async def test_place_order_via_market_happy_path() -> None:
    from lcz_binance_sdk.order import Order, place_order_via

    rest = _FakeRest()
    rest.queue(
        "POST",
        "/fapi/v1/order",
        {
            "orderId": 99,
            "clientOrderId": "abc",
            "status": "FILLED",
            "avgPrice": "50000.5",
            "executedQty": "1",
        },
    )
    order = Order(price=0, quantity=1, action="long", price_type="MKT")
    resp = await place_order_via(rest, _FakeContract("BTC"), order)

    assert resp.order_id == "99"
    assert resp.status == "FILLED"
    assert resp.avg_filled_price == 50000.5
    assert resp.filled_quantity == 1
    # Symbol auto-USDT suffixed; MARKET path must not carry price/timeInForce
    sent = rest.calls[0]["params"]
    assert sent["symbol"] == "BTCUSDT"
    assert sent["side"] == "BUY"
    assert sent["type"] == "MARKET"
    assert "price" not in sent
    assert "timeInForce" not in sent
    assert rest.calls[0]["signed"] is True


@pytest.mark.asyncio
async def test_place_order_via_limit_carries_price_and_tif() -> None:
    from lcz_binance_sdk.order import Order, place_order_via

    rest = _FakeRest()
    rest.queue(
        "POST",
        "/fapi/v1/order",
        {"orderId": 7, "clientOrderId": "x", "status": "NEW", "avgPrice": "0", "executedQty": "0"},
    )
    order = Order(
        price=49000.0,
        quantity=2,
        action="short",
        price_type="LMT",
        time_in_force="IOC",
        reduce_only=True,
        client_order_id="cli-7",
    )
    resp = await place_order_via(rest, _FakeContract("ETHUSDT"), order)

    sent = rest.calls[0]["params"]
    assert sent["symbol"] == "ETHUSDT"
    assert sent["side"] == "SELL"
    assert sent["type"] == "LIMIT"
    assert sent["price"] == "49000.0"
    assert sent["timeInForce"] == "IOC"
    assert sent["reduceOnly"] == "true"
    assert sent["newClientOrderId"] == "cli-7"
    assert resp.status == "NEW"
    assert resp.avg_filled_price is None  # 0 -> None


@pytest.mark.asyncio
async def test_place_order_via_4xx_returns_rejected() -> None:
    from lcz_binance_sdk.order import Order, place_order_via

    rest = _FakeRest()
    rest.queue("POST", "/fapi/v1/order", {"error": "HTTP 400", "detail": {"code": -2010}})
    order = Order(price=50000.0, quantity=1, action="long", price_type="LMT")
    resp = await place_order_via(rest, _FakeContract("BTCUSDT"), order)

    assert resp.status == "REJECTED"
    assert resp.order_id == ""
    assert resp.raw is not None
    assert resp.raw.get("error") == "HTTP 400"


@pytest.mark.asyncio
async def test_place_order_via_invalid_args_raise() -> None:
    from lcz_binance_sdk.order import Order, place_order_via

    rest = _FakeRest()
    bad_action = Order(price=0, quantity=1, action="buy", price_type="MKT")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await place_order_via(rest, _FakeContract(), bad_action)

    bad_lmt = Order(price=0, quantity=1, action="long", price_type="LMT")
    with pytest.raises(ValueError):
        await place_order_via(rest, _FakeContract(), bad_lmt)

    bad_qty = Order(price=10, quantity=0, action="long", price_type="LMT")
    with pytest.raises(ValueError):
        await place_order_via(rest, _FakeContract(), bad_qty)


@pytest.mark.asyncio
async def test_cancel_order_via() -> None:
    from lcz_binance_sdk.order import cancel_order_via

    rest = _FakeRest()
    rest.queue("DELETE", "/fapi/v1/order", {"status": "CANCELED"})
    rest.queue("DELETE", "/fapi/v1/order", {"error": "HTTP 404"})
    rest.queue("DELETE", "/fapi/v1/order", {"status": "NEW"})

    assert await cancel_order_via(rest, "BTC", "123") is True
    assert rest.calls[0]["params"] == {"symbol": "BTCUSDT", "orderId": 123}
    assert await cancel_order_via(rest, "BTCUSDT", "456") is False
    assert await cancel_order_via(rest, "BTCUSDT", "789") is False
    # invalid order_id -> False without REST call
    before = len(rest.calls)
    assert await cancel_order_via(rest, "BTCUSDT", "not-an-int") is False
    assert len(rest.calls) == before


@pytest.mark.asyncio
async def test_list_trades_via_requires_symbol_and_parses() -> None:
    from lcz_binance_sdk.order import list_trades_via

    rest = _FakeRest()
    # No symbol -> [] without REST call
    assert await list_trades_via(rest) == []
    assert rest.calls == []

    rest.queue(
        "GET",
        "/fapi/v1/allOrders",
        [
            {"orderId": 1, "clientOrderId": "a", "symbol": "BTCUSDT", "status": "FILLED",
             "avgPrice": "100", "executedQty": "2"},
            {"orderId": 2, "clientOrderId": "b", "symbol": "BTCUSDT", "status": "NEW",
             "avgPrice": "0", "executedQty": "0"},
        ],
    )
    out = await list_trades_via(rest, "BTC", limit=2000)
    assert len(out) == 2
    assert out[0].avg_filled_price == 100.0
    assert out[1].avg_filled_price is None
    # limit clamped to 1000
    assert rest.calls[0]["params"]["limit"] == 1000


@pytest.mark.asyncio
async def test_list_trades_via_handles_error_payload() -> None:
    from lcz_binance_sdk.order import list_trades_via

    rest = _FakeRest()
    rest.queue("GET", "/fapi/v1/allOrders", {"error": "HTTP 401"})
    assert await list_trades_via(rest, "BTC") == []
